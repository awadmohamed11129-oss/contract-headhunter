"""Loading a contractor file into the app's contractor list (upsert on talent_id)."""

from pathlib import Path

import pytest

from conftest import CONFIG_DIR
from jobmatch.schemas import ContractorProfile
from jobmatch.sources.contractor_upsert import (
    ContractorFileError,
    fill_missing_ids,
    load_contractor_file,
    read_contractor_file,
    upsert_contractors,
)
from jobmatch.storage.csv_store import (
    CsvContractorProfileRepository,
    check_data_folder,
    master_path,
)


def person(talent_id: str, headline: str, **extra: object) -> ContractorProfile:
    return ContractorProfile(
        talent_id=talent_id,
        talent_name=f"Person {talent_id}",
        standardized_headline=headline,
        rate_expectation="Industry Standard",
        **extra,  # type: ignore[arg-type]
    )


def repo(path: Path) -> CsvContractorProfileRepository:
    return CsvContractorProfileRepository(path, lock_timeout=5)


def stored(path: Path) -> list[ContractorProfile]:
    return CsvContractorProfileRepository(path, lock_timeout=5).list_all()


def backups(path: Path) -> list[Path]:
    folder = path.parent / "backups"
    return sorted(folder.glob("contractors.*.csv")) if folder.exists() else []


def test_first_load_creates_the_list(tmp_path: Path) -> None:
    dest = tmp_path / "contractors" / "contractors.csv"
    report = upsert_contractors(
        [person("TAL-1", "Data Analyst"), person("TAL-2", "Analyste de données")],
        repo(dest),
    )  # fmt: skip
    assert (report.added, report.updated, report.unchanged) == (["TAL-1", "TAL-2"], [], 0)
    assert [p.standardized_headline for p in stored(dest)] == [
        "Data Analyst", "Analyste de données",
    ]  # fmt: skip
    assert backups(dest) == []  # nothing to back up the first time


def test_new_rows_added_changed_rows_updated_others_kept(tmp_path: Path) -> None:
    dest = tmp_path / "contractors.csv"
    upsert_contractors(
        [person("TAL-1", "Data Analyst"), person("TAL-2", "Recruiter"),
         person("TAL-3", "Rédactrice UX", languages=["fr"])],
        repo(dest),
    )  # fmt: skip
    report = upsert_contractors(
        [person("TAL-2", "Senior Recruiter"), person("TAL-3", "Rédactrice UX", languages=["fr"]),
         person("TAL-4", "Gestionnaire de projet")],
        repo(dest),
    )  # fmt: skip
    assert report.added == ["TAL-4"] and report.updated == ["TAL-2"]
    assert (report.unchanged, report.kept_not_in_file, report.file_rows) == (1, 1, 3)
    assert [(p.talent_id, p.standardized_headline) for p in stored(dest)] == [
        ("TAL-1", "Data Analyst"), ("TAL-2", "Senior Recruiter"),
        ("TAL-3", "Rédactrice UX"), ("TAL-4", "Gestionnaire de projet"),
    ]  # fmt: skip
    assert len(backups(dest)) == 1


def test_loading_the_same_file_again_changes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "contractors.csv"
    rows = [person("TAL-1", "Data Analyst")]
    upsert_contractors(rows, repo(dest))
    before = dest.read_bytes()
    report = upsert_contractors(rows, repo(dest))
    assert not report.changed and report.unchanged == 1
    assert dest.read_bytes() == before and backups(dest) == []


# ---- the master record (user decisions 2026-11-24): edits kept until the master changes ----


def lists(tmp_path: Path) -> tuple[CsvContractorProfileRepository, CsvContractorProfileRepository]:
    """The app's list and its master record, as the loader places them."""
    dest = tmp_path / "contractors" / "contractors.csv"
    return repo(dest), repo(master_path(dest))


def edit(lst: CsvContractorProfileRepository, talent_id: str, **changes: object) -> None:
    """A save from the Profile pop-up: no master record."""
    [row] = [p for p in lst.list_all() if p.talent_id == talent_id]
    upsert_contractors([row.model_copy(update=changes)], lst)


def test_master_path_sits_beside_the_list(tmp_path: Path) -> None:
    dest = tmp_path / "contractors" / "contractors.csv"
    assert master_path(dest) == tmp_path / "contractors" / "contractors_master.csv"


def test_without_a_master_record_the_file_wins_once(tmp_path: Path) -> None:
    """Decision 1a: the first import after the rule shipped replaces differing rows as
    before, then records the master."""
    lst, master = lists(tmp_path)
    upsert_contractors([person("TAL-1", "Data Analyst")], lst)  # stored before the rule
    edit(lst, "TAL-1", seniority="Senior")
    report = upsert_contractors([person("TAL-1", "Data Analyst")], lst, master)
    assert report.updated == ["TAL-1"] and report.kept_edits == []
    assert stored(lst.path) == [person("TAL-1", "Data Analyst")]
    assert stored(master.path) == [person("TAL-1", "Data Analyst")]


def test_unchanged_master_keeps_the_edit(tmp_path: Path) -> None:
    lst, master = lists(tmp_path)
    rows = [person("TAL-1", "Data Analyst"), person("TAL-2", "Rédactrice UX", languages=["fr"])]
    upsert_contractors(rows, lst, master)
    edit(lst, "TAL-2", standardized_headline="Rédactrice UX principale", seniority="Senior")
    edited = stored(lst.path)
    report = upsert_contractors(rows, lst, master)  # the same master file again
    assert report.kept_edits == ["TAL-2"] and not report.changed
    assert (report.unchanged, report.file_rows) == (1, 2)
    assert stored(lst.path) == edited
    assert stored(master.path) == rows  # the record never takes an edit


def test_changed_master_takes_only_the_changed_fields(tmp_path: Path) -> None:
    """Decision 2b: an edit to another field survives a change in the master."""
    lst, master = lists(tmp_path)
    upsert_contractors([person("TAL-1", "Analyste de données", languages=["fr"])], lst, master)
    edit(lst, "TAL-1", standardized_headline="Analyste BI", seniority="Senior")
    newer = person("TAL-1", "Analyste de données", languages=["fr", "en"])
    report = upsert_contractors([newer], lst, master)
    assert report.updated == ["TAL-1"] and report.kept_edits == []
    [row] = stored(lst.path)
    assert row.languages == ["fr", "en"]  # from the master
    assert (row.standardized_headline, row.seniority) == ("Analyste BI", "Senior")  # edits
    assert stored(master.path) == [newer]


def test_a_field_changed_in_both_takes_the_master(tmp_path: Path) -> None:
    lst, master = lists(tmp_path)
    upsert_contractors([person("TAL-1", "Data Analyst")], lst, master)
    edit(lst, "TAL-1", standardized_headline="BI Analyst", seniority="Senior")
    upsert_contractors([person("TAL-1", "Senior Data Analyst")], lst, master)
    [row] = stored(lst.path)
    assert (row.standardized_headline, row.seniority) == ("Senior Data Analyst", "Senior")


def test_master_record_adds_new_people_and_keeps_missing_ones(tmp_path: Path) -> None:
    lst, master = lists(tmp_path)
    upsert_contractors([person("TAL-1", "Recruiter"), person("TAL-2", "Comptable")], lst, master)
    report = upsert_contractors(
        [person("TAL-2", "Comptable"), person("TAL-3", "Gestionnaire de projet")], lst, master
    )
    assert report.added == ["TAL-3"] and report.kept_not_in_file == 1
    assert [p.talent_id for p in stored(lst.path)] == ["TAL-1", "TAL-2", "TAL-3"]
    assert [p.talent_id for p in stored(master.path)] == ["TAL-1", "TAL-2", "TAL-3"]


def test_a_save_without_master_leaves_the_record_alone(tmp_path: Path) -> None:
    lst, master = lists(tmp_path)
    upsert_contractors([person("TAL-1", "Data Analyst")], lst, master)
    before = master.path.read_bytes()
    edit(lst, "TAL-1", standardized_headline="Analyste de données")
    assert master.path.read_bytes() == before


def test_a_broken_master_record_is_reported_by_the_backup_check(tmp_path: Path) -> None:
    lst, master = lists(tmp_path)
    upsert_contractors([person("TAL-1", "Data Analyst")], lst, master)
    assert check_data_folder(tmp_path, Path("contractors/contractors.csv"), lock_timeout=5) == []
    master.path.write_text("not,the,right,header\n1,2,3,4\n", encoding="utf-8")
    problems = check_data_folder(tmp_path, Path("contractors/contractors.csv"), lock_timeout=5)
    assert problems and problems[0].startswith("contractors_master.csv")


def test_duplicate_talent_ids_in_the_file_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ContractorFileError, match="TAL-1"):
        upsert_contractors([person("TAL-1", "A"), person("TAL-1", "B")], repo(tmp_path / "c.csv"))


def test_csv_file_is_read_and_checked(tmp_path: Path) -> None:
    good = tmp_path / "good.csv"
    upsert_contractors([person("TAL-9", "Chargée de communication")], repo(good))
    rows = read_contractor_file(good, config_dir=CONFIG_DIR, lock_timeout=5)
    assert [r.talent_id for r in rows] == ["TAL-9"]

    bad = tmp_path / "bad.csv"
    bad.write_text("talent_id,nickname\nTAL-1,x\n", encoding="utf-8")
    with pytest.raises(ContractorFileError, match="bad.csv"):
        read_contractor_file(bad, config_dir=CONFIG_DIR, lock_timeout=5)


def test_other_file_types_and_missing_files_are_refused(tmp_path: Path) -> None:
    other = tmp_path / "people.txt"
    other.write_text("TAL-1", encoding="utf-8")
    with pytest.raises(ContractorFileError, match=".xlsx"):
        read_contractor_file(other, config_dir=CONFIG_DIR, lock_timeout=5)
    with pytest.raises(ContractorFileError, match="not found"):
        read_contractor_file(tmp_path / "nope.csv", config_dir=CONFIG_DIR, lock_timeout=5)


# ---- rows without a talent ID (TAL-CAN-…) ----

HEADER = "talent_id,talent_name,standardized_headline,rate_expectation\n"


def test_rows_without_an_id_get_the_next_tal_can_number(tmp_path: Path) -> None:
    stored = [person("TAL-BC-001", "Data Analyst"), person("TAL-ON-052", "Recruiter")]
    upload = tmp_path / "new.csv"
    upload.write_text(
        HEADER
        + "TAL-ON-049,Person TAL-ON-049,Rédacteur,80\n"
        + ",Camille Roy,Analyste de données,90\n"
        + ",Sam Lee,UX Writer,85\n",
        encoding="utf-8",
    )
    loaded = load_contractor_file(upload, config_dir=CONFIG_DIR, lock_timeout=5, existing=stored)
    assert loaded.given_ids == ["TAL-CAN-053", "TAL-CAN-054"]
    assert [r.talent_id for r in loaded.rows] == ["TAL-ON-049", "TAL-CAN-053", "TAL-CAN-054"]
    assert ",Camille Roy," in upload.read_text(encoding="utf-8")  # the file is never changed


def test_loading_the_same_file_again_reuses_the_given_ids(tmp_path: Path) -> None:
    dest = tmp_path / "contractors.csv"
    upload = tmp_path / "people.csv"
    upload.write_text(
        HEADER + ",Camille Roy,Analyste de données,90\n" + "TAL-BC-007,Person 7,Recruiter,70\n",
        encoding="utf-8",
    )
    first = load_contractor_file(upload, config_dir=CONFIG_DIR, lock_timeout=5)
    assert first.given_ids == ["TAL-CAN-008"]
    upsert_contractors(first.rows, repo(dest))

    # Same person again (spacing and case differ), plus a new person without an ID.
    upload.write_text(
        HEADER + ",  camille   ROY ,Analyste de données principale,95\n"
        + ",Sam Lee,UX Writer,85\n",
        encoding="utf-8",
    )  # fmt: skip
    again = load_contractor_file(
        upload, config_dir=CONFIG_DIR, lock_timeout=5, existing=stored(dest)
    )
    assert again.given_ids == ["TAL-CAN-008", "TAL-CAN-009"]
    report = upsert_contractors(again.rows, repo(dest))
    assert report.updated == ["TAL-CAN-008"] and report.added == ["TAL-CAN-009"]
    assert len(stored(dest)) == 3  # no duplicate of Camille


def test_fill_missing_ids_only_reuses_tal_can_ids() -> None:
    existing = [person("TAL-BC-003", "Data Analyst")]  # named "Person TAL-BC-003"
    rows = [{"talent_id": "", "talent_name": "Person TAL-BC-003"}]
    # A same-named contractor with an ID from the master list is not reused: new ID.
    assert fill_missing_ids(rows, existing, prefix="TAL-CAN-", width=3) == ["TAL-CAN-004"]
