"""The remembered Contractors folder, the start-up check and the state file: an older folder
never loads over newer data, the check works on its own picks, and a file that failed is not
tried again at every start. Fake Gemini, no network."""

from pathlib import Path

import pytest

from jobmatch.app.service import AppError, AppService
from jobmatch.sources.contractor_upsert import upsert_contractors
from jobmatch.storage.csv_store import CsvContractorProfileRepository
from test_ingest import EN_CONTRACT
from test_ingest_only import make_service
from test_resumes import folder, folder_files, pdf, people, zipped


def loaded_summaries(service: AppService) -> list[str]:
    return sorted(c.executive_summary or "" for c in service._loader().contractors.list_all())


def newer_list(tmp_path: Path) -> Path:
    path = tmp_path / "newer" / "list.csv"
    changed = [
        p.model_copy(update={"executive_summary": "Newest text. Marker77."}) for p in people()
    ]
    upsert_contractors(changed, CsvContractorProfileRepository(path, lock_timeout=5))
    return path


def test_the_folder_is_read_again_only_when_it_changed(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service, _ = make_service(app_settings, tmp_path)
    root = folder(tmp_path)
    service.pick_contractor_folder(root)
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    assert service._state()["contractors_sig"]  # saved by the run, not only by the start-up check

    assert service.refresh_contractors() is False  # same content: nothing to load again
    assert service.contractor_file is None
    pdf(root / "resume" / "TAL-CAN-0001.pdf", "a newer file")
    assert service.refresh_contractors() is True
    assert service.contractor_file is not None


def test_a_file_picked_by_hand_is_never_reverted_by_the_older_folder(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    service, _ = make_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    assert service.contractors_folder() is not None

    newer = newer_list(tmp_path)
    service.pick_contractor_file(newer.name, path=newer)
    assert service.contractors_folder() is None  # forgotten: it cannot win over the newer pick
    service.run(echo=lambda s: None, confirm=lambda c: True, match=True)
    assert loaded_summaries(service) == ["Newest text. Marker77."] * 2
    assert service.refresh_contractors() is False


def test_picks_by_hand_in_any_form_forget_the_folder(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service, _ = make_service(app_settings, tmp_path)
    root = folder(tmp_path)
    service.pick_contractor_folder(root)
    resume = pdf(tmp_path / "TAL-CAN-0001.pdf")
    service.pick_contractor_file(resume.name, path=resume)  # a single résumé
    assert service.contractors_folder() is None

    service.pick_contractor_folder(root)
    assert service.contractors_folder() == root
    files = folder_files(root)
    one = zipped(tmp_path / "one.zip", files, "Contractors")
    service.pick_contractor_file("Contractors.zip", data=one.read_bytes())  # an upload
    assert service.contractors_folder() is None  # the saved upload copy is never remembered

    service.pick_contractor_file("Contractors.zip", path=one)  # a real path from the picker
    assert service.contractors_folder() == one
    service.pick_contractor_zips([one, zipped(tmp_path / "two.zip", {"x.txt": b"x"}, "C")])
    assert service.contractors_folder() is None  # several zips: not remembered, old one dropped


def test_a_failed_pick_keeps_the_earlier_picks(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service, _ = make_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    earlier = dict(service.resumes)
    assert earlier
    bad = tmp_path / "Bad"
    bad.mkdir()
    (bad / "contractors.csv").write_text("talent_id,nickname\nTAL-1,x\n", encoding="utf-8")
    with pytest.raises(AppError, match="contractors.csv|nickname|column"):
        service.pick_contractor_folder(bad)
    assert service.resumes == earlier


def test_a_state_file_that_is_not_an_object_counts_as_empty(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    service, _ = make_service(app_settings, tmp_path)
    (tmp_path / "app_state.json").write_text("[1, 2]", encoding="utf-8")
    assert service._state() == {}
    service._save_state(last_jobs_at="t")
    assert service._state() == {"last_jobs_at": "t"}


def test_the_start_up_check_leaves_the_picks_on_screen_alone(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    service, _ = make_service(app_settings, tmp_path)
    root = folder(tmp_path)
    service.pick_contractor_folder(root)
    service.clear_contractor_picks()
    newer = newer_list(tmp_path)
    service.pick_contractor_file(newer.name, path=newer)  # picked while the check runs
    service._environ["JOBMATCH_CONTRACTORS_FOLDER"] = str(root)  # the check reads this folder

    summary = service.sync_on_start()
    assert summary.ran
    assert service.contractor_file == newer  # still picked, not wiped by the check


def test_a_file_that_failed_is_not_tried_again_at_every_start(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    service, fake = make_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.clear_contractor_picks()
    service.add_jobs_file("analyst.txt", EN_CONTRACT.encode())
    bad = service.add_jobs_file("broken.txt", b"url: not a link\ntitle:\n---\n").dest
    first = service.sync_on_start()
    assert first.ran and bad.exists()  # the good file was stored; the bad one stays
    assert service._state()["inbox_failed"]

    again = service.sync_on_start()
    assert not again.ran  # nothing to retry: the failed file is unchanged
    bad.write_text(
        "url: https://jobs.example.ca/9\ntitle: Analyst\n---\nText " * 3, encoding="utf-8"
    )
    assert service.sync_on_start().ran  # changed: tried again
    assert fake.calls == 0


def test_links_from_a_hand_edited_env_must_be_web_addresses(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    service, _ = make_service(app_settings, tmp_path)
    service._environ["JOBMATCH_LINK_INTAKE_FORM"] = "javascript:alert(1)"
    service._environ["JOBMATCH_LINK_INTAKE_SHEET"] = "https://sheets.example.com/x"
    links = service.links()
    assert links["intake_form"] == "" and links["intake_sheet"] == "https://sheets.example.com/x"


def test_the_talent_id_prefix_comes_from_the_config(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service, _ = make_service(app_settings, tmp_path)
    assert service.talent_id_prefix() == "TAL-"
