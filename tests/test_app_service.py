"""The desktop app's logic (app/service.py), without any UI. Fake Gemini, no network."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from jobmatch.app.service import (
    REVIEWER_ENV,
    AppError,
    AppService,
    classify_jobs_file,
)
from jobmatch.config import Settings
from jobmatch.llm.usage import RunCheck
from jobmatch.schemas import ContractorProfile, Decision, Job, ReasonCode
from jobmatch.secrets_file import read_env_file
from jobmatch.sources.contractor_upsert import upsert_contractors
from jobmatch.storage.csv_store import CsvContractorProfileRepository, CsvReviewRepository, CsvStore
from test_pipeline import add_jobs, contractor_file

NOW = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
FAKE_KEY = "AIzaFAKE-test-only"


# ---- jobs files ----


@pytest.mark.parametrize(
    ("name", "text", "kind"),
    [
        ("links.txt", "# from alerts\nhttps://jobs.example.ca/1\nhttp://x.ca/2  # note\n", "links"),
        ("poste.txt", "url: https://emplois.example.ca/9\ntitle: Analyste\n---\nTexte", "manual"),
        ("mixed.txt", "https://x.ca/1\nSenior Analyst at Example\n", "manual"),
        ("page.html", "<html></html>", "manual"),
        ("posting.PDF", "%PDF-1.7", "manual"),
    ],
)
def test_jobs_file_kind(name: str, text: str, kind: str) -> None:
    assert classify_jobs_file(name, text.encode("utf-8")) == kind


def test_other_file_types_are_refused() -> None:
    with pytest.raises(AppError, match=".txt, .html or .pdf"):
        classify_jobs_file("jobs.docx", b"x")


def test_jobs_files_go_to_the_inbox_without_overwriting(service: AppService) -> None:
    data = b"https://jobs.example.ca/1\nhttps://jobs.example.ca/2\n# done\n"
    first = service.add_jobs_file("links.txt", data, now=NOW)
    again = service.add_jobs_file("links.txt", data, now=NOW)
    assert first.kind == "links" and first.links == 2
    assert first.dest.parent == service.data_dir / "inbox" / "links"
    assert first.dest != again.dest and first.dest.read_bytes() == data
    paste = service.add_jobs_file("poste.txt", "url: https://x.ca/9\ntitle: Rédacteur\n".encode())
    assert paste.kind == "manual" and paste.dest.parent.name == "manual"
    with pytest.raises(AppError, match="empty"):
        service.add_jobs_file("empty.txt", b"  \n")


# ---- contractor file ----


def test_contractor_file_is_checked_when_picked(service: AppService, tmp_path: Path) -> None:
    path = contractor_file(tmp_path)
    info = service.pick_contractor_file(path.name, path=path)
    assert info.contractors == 1 and service.contractor_file == path

    upload = service.pick_contractor_file("export.csv", data=path.read_bytes())
    assert upload.path.parent == service.data_dir / "contractors" / "uploads"

    with pytest.raises(AppError, match="workbook"):
        service.pick_contractor_file("people.txt", data=b"x")
    with pytest.raises(AppError, match="bad.csv"):
        service.pick_contractor_file("bad.csv", data=b"talent_id,nickname\nTAL-1,x\n")


# ---- settings ----


def test_key_and_reviewer_are_saved_to_the_env_file(
    service: AppService, env: dict[str, str]
) -> None:
    assert not service.has_key() and service.reviewer() == "reviewer"
    service.save_key(f"  {FAKE_KEY}  ")
    service.save_reviewer("  Camille   Roy ")
    assert service.has_key() and service.reviewer() == "Camille Roy"
    saved = read_env_file(service.env_path)
    assert saved == {"GEMINI_API_KEY": FAKE_KEY, REVIEWER_ENV: "Camille Roy"}
    assert env["GEMINI_API_KEY"] == FAKE_KEY
    with pytest.raises(AppError, match="empty"):
        service.save_key("   ")


# ---- run, results, decisions, export ----


def test_run_then_results_in_review_order(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    add_jobs(store, make_job)  # 2 data jobs (C01 fits), 1 recruiting job (nobody fits)
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    lines: list[str] = []
    report = service.run(echo=lines.append, confirm=lambda check: False)
    assert report.jobs_matched == 2 and report.jobs_no_match == 1
    assert service.contractor_file is None  # loaded once
    assert any("total" in line for line in lines)  # token line per call

    results = service.results()
    assert [r.outcome for r in results] == ["fits", "fits", "no_match"]
    first = results[0].matches[0]
    assert (first.name, first.match.talent_id, first.decision) == ("Alex Martin", "TAL-1", None)
    assert service.quota().requests == 3


def test_decisions_are_stored_and_the_latest_shows(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    add_jobs(store, make_job)
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    service.run(echo=lambda s: None, confirm=lambda c: False)
    first = service.results()[0]
    match_id = first.matches[0].match.match_id

    with pytest.raises(AppError, match="reason"):
        service.decide(match_id, Decision.REJECTED)
    service.decide(match_id, Decision.APPROVED)
    service.decide(match_id, Decision.REJECTED, ReasonCode.SENIORITY, "  trop junior ")
    reviews = CsvReviewRepository(store).list_all()
    assert [r.decision for r in reviews] == [Decision.APPROVED, Decision.REJECTED]
    assert reviews[-1].notes == "trop junior" and reviews[-1].reviewer == "reviewer"
    # A rejection is hidden behind "Show rejected", with its decision (0.4).
    [job] = [r for r in service.results() if r.job.job_id == first.job.job_id]
    assert job.matches == []
    latest = job.rejected[0].decision
    assert latest is not None and latest.reason_code is ReasonCode.SENIORITY


def test_quota_question_reaches_the_caller(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    add_jobs(store, make_job)
    assert service.llm is not None
    limits = service.llm.limits.model_copy(update={"rpd": 2})
    service.llm = service.llm.model_copy(update={"limits": limits})
    service.settings = service.settings.model_copy(update={"llm": service.llm})
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    asked: list[RunCheck] = []
    report = service.run(echo=lambda s: None, confirm=lambda c: asked.append(c) or False)
    assert asked and asked[0].verdict == "exceeds" and report.stopped
    assert [r.outcome for r in service.results()] == ["not_judged"] * 3


def test_missing_key_is_a_plain_message(app_settings: Settings, tmp_path: Path) -> None:
    store = CsvStore(app_settings.paths.data_dir, lock_timeout=5)
    job = Job(
        job_id="paste:1", source="paste", source_id="1", url="https://x.ca/1",
        title_raw="Data Analyst", responsibilities=["Build dashboards"], first_seen_at=NOW,
    )  # fmt: skip
    from jobmatch.storage.csv_store import CsvJobRepository

    CsvJobRepository(store).add_new([job])
    real = AppService(app_settings, tmp_path / "app.env", environ={})  # real Gemini, no key
    path = contractor_file(tmp_path)
    real.pick_contractor_file(path.name, path=path)
    with pytest.raises(AppError, match="Gemini key in Settings"):
        real.run(echo=lambda s: None, confirm=lambda c: False)


def test_export_writes_the_spreadsheet(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    add_jobs(store, make_job)
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    service.run(echo=lambda s: None, confirm=lambda c: False)
    done = service.export()
    assert done.path.exists() and done.rows == 3 and done.jobs == 3
    assert "Alex Martin" in done.path.read_text(encoding="utf-8-sig")


def test_reset_makes_a_match_undecided_and_keeps_history(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    add_jobs(store, make_job)
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    service.run(echo=lambda s: None, confirm=lambda c: False)
    match_id = service.results()[0].matches[0].match.match_id
    service.decide(match_id, Decision.APPROVED)
    service.clear_decision(match_id)
    assert service.results()[0].matches[0].decision is None
    history = [r.decision for r in CsvReviewRepository(store).list_all()]
    assert history == [Decision.APPROVED, Decision.CLEARED]  # append-only record
    service.decide(match_id, Decision.NEEDS_INFO)
    latest = service.results()[0].matches[0].decision
    assert latest is not None and latest.decision is Decision.NEEDS_INFO


def test_profile_fields_are_the_csv_row_in_file_order(service: AppService, tmp_path: Path) -> None:
    from jobmatch.schemas import ContractorProfile
    from jobmatch.sources.contractor_upsert import upsert_contractors

    upsert_contractors(
        [ContractorProfile(
            talent_id="TAL-7", talent_name="Élise Tremblay", rate_expectation="95",
            standardized_headline="Rédactrice UX",
            executive_summary="Écrit des parcours | simples et clairs.",
            core_strengths=["UX writing", "Microcopie"], languages=["fr", "en"],
        )],
        CsvContractorProfileRepository(service.settings.paths.contractors_csv, lock_timeout=5),
    )  # fmt: skip
    fields = dict(service.contractor_fields("TAL-7"))
    columns = [c for c, _ in service.contractor_fields("TAL-7")]
    assert columns[:3] == ["talent_id", "talent_name", "location"]  # the file's own order
    assert fields["talent_name"] == ["Élise Tremblay"]
    assert fields["core_strengths"] == ["UX writing", "Microcopie"]  # list cell split
    assert fields["executive_summary"] == ["Écrit des parcours | simples et clairs."]  # text kept
    assert fields["location"] == []  # empty cell
    with pytest.raises(AppError, match="TAL-404"):
        service.contractor_fields("TAL-404")


def test_progress_moves_forward_to_done(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    add_jobs(store, make_job)
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    seen: list[tuple[float, str]] = []
    service.run(
        echo=lambda s: None, confirm=lambda c: False, progress=lambda f, s: seen.append((f, s))
    )
    shares = [f for f, _ in seen]
    assert shares == sorted(shares) and shares[0] == 0.0 and shares[-1] == 1.0
    stages = [s for _, s in seen]
    assert "Importing jobs" in stages and "Screening jobs: 3 of 3" in stages
    assert "Deep reviews: 1 of up to 2" in stages  # 2 jobs with a shortlist: one batch
    assert stages[-1] == "Done"


# ---- import messages ----


def csv_with(tmp_path: Path, raw: bytes) -> Path:
    path = tmp_path / "people" / "contractors.csv"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(raw)
    return path


def test_a_csv_that_is_not_utf8_gets_a_plain_message(service: AppService, tmp_path: Path) -> None:
    good = contractor_file(tmp_path).read_text(encoding="utf-8").replace("Alex Martin", "Émile Roy")
    for raw in (
        good.encode("cp1252"),  # saved as "CSV" from Excel
        good.encode("utf-8").decode("cp1252", errors="replace").encode("utf-8"),  # mojibake
        good.replace("É", "�").encode("utf-8"),
    ):
        with pytest.raises(AppError, match="Save the file as CSV UTF-8 and try again"):
            service.pick_contractor_file("contractors.csv", path=csv_with(tmp_path, raw))
    service.pick_contractor_file("contractors.csv", path=csv_with(tmp_path, good.encode("utf-8")))


def test_names_without_a_resume_and_same_names(service: AppService, tmp_path: Path) -> None:
    root = tmp_path / "Contractors"
    upsert_contractors(
        [
            ContractorProfile(talent_id="TAL-1", talent_name="Alex Martin", rate_expectation="90"),
            ContractorProfile(
                talent_id="TAL-2", talent_name="Émilie Tremblay", rate_expectation="90"
            ),
            ContractorProfile(
                talent_id="TAL-3", talent_name=" alex  MARTIN", rate_expectation="90"
            ),
        ],
        CsvContractorProfileRepository(root / "contractors.csv", lock_timeout=5),
    )
    (root / "resumes").mkdir()
    (root / "resumes" / "TAL-2.pdf").write_bytes(b"%PDF-1.4\n")
    info = service.pick_contractor_folder(root)
    assert info.missing_resumes == ["Alex Martin", " alex  MARTIN"]
    assert info.same_name == ["Alex Martin"]  # once, in file order
    service.run(echo=lambda s: None, confirm=lambda c: False, match=False)
    flagged = {t.talent_id: t.same_name_ids for t in service.talent_overview()}
    assert flagged == {"TAL-1": ["TAL-3"], "TAL-2": [], "TAL-3": ["TAL-1"]}
    # Stored résumés count: picking the file again names only those still without one.
    again = service.pick_contractor_file("contractors.csv", path=root / "contractors.csv")
    assert again.missing_resumes == ["Alex Martin", " alex  MARTIN"]


# ---- remembered folders and links ----


def test_the_contractors_folder_is_remembered(service: AppService, tmp_path: Path) -> None:
    with pytest.raises(AppError, match="remembered"):
        service.reimport_contractors()
    path = contractor_file(tmp_path)
    root = path.parent
    service.pick_contractor_folder(root)
    assert service.contractors_folder() == root
    assert read_env_file(service.env_path)["JOBMATCH_CONTRACTORS_FOLDER"] == str(root)
    service.clear_contractor_picks()
    info = service.reimport_contractors()
    assert info.contractors == 1 and service.contractor_file == path
    service.forget_contractors_folder()
    assert service.contractors_folder() is None
    service.pick_contractor_folder(root)
    root.rename(tmp_path / "moved")
    with pytest.raises(AppError, match="not there any more"):
        service.reimport_contractors()


def test_links_are_validated_and_saved(service: AppService) -> None:
    assert service.links() == {"intake_form": "", "intake_sheet": "", "job_collector_sheet": ""}
    service.save_link("intake_form", "  https://forms.example.ca/abc?x=1  ")
    assert service.links()["intake_form"] == "https://forms.example.ca/abc?x=1"
    assert read_env_file(service.env_path)["JOBMATCH_LINK_INTAKE_FORM"].endswith("?x=1")
    with pytest.raises(AppError, match="http"):
        service.save_link("intake_sheet", "docs.google.com/spreadsheets/d/1")
    with pytest.raises(AppError, match="Unknown"):
        service.save_link("other", "https://x.ca")
    service.save_link("intake_form", "")
    assert service.links()["intake_form"] == ""


def test_jobs_folder_imports_only_new_files(service: AppService, tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    with pytest.raises(AppError, match="No jobs folder"):
        service.import_jobs_folder()
    with pytest.raises(AppError, match="Not a folder"):
        service.set_jobs_folder(tmp_path / "nope")
    service.set_jobs_folder(jobs)
    assert service.jobs_folder() == jobs
    (jobs / "links.txt").write_text("https://jobs.example.ca/1\n", encoding="utf-8")
    (jobs / "notes.docx").write_bytes(b"x")  # not a job file
    (jobs / ".hidden.txt").write_text("https://jobs.example.ca/9\n", encoding="utf-8")
    (jobs / "empty.txt").write_text("\n", encoding="utf-8")
    first = service.import_jobs_folder()
    assert first.new_files == 1 and len(first.problems) == 1 and "empty.txt" in first.problems[0]
    assert len(list((service.data_dir / "inbox" / "links").iterdir())) == 1
    again = service.import_jobs_folder()
    assert again.new_files == 0 and again.problems == []  # seen, even the empty one
    (jobs / "links.txt").write_text("https://jobs.example.ca/1\nhttps://jobs.example.ca/2\n")
    assert service.import_jobs_folder().new_files == 1  # a changed file is new
    service.set_jobs_folder(None)
    assert service.jobs_folder() is None


# ---- sync on start, waiting jobs, home summary ----


def test_sync_on_start_reports_a_missing_folder(service: AppService, tmp_path: Path) -> None:
    root = contractor_file(tmp_path).parent
    service.pick_contractor_folder(root)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    service.set_jobs_folder(jobs)
    root.rename(tmp_path / "gone")
    jobs.rmdir()
    summary = service.sync_on_start()
    assert not summary.ran and len(summary.problems) == 2
    assert "not there any more" in summary.problems[0]


def test_home_summary_follows_the_pipeline(
    service: AppService, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> None:
    empty = service.home_summary()
    assert (empty.contractors, empty.jobs, empty.jobs_waiting, empty.matches_waiting) == (0,) * 4
    assert empty.last_run_at is None and empty.last_contractors_at is None
    add_jobs(store, make_job)
    path = contractor_file(tmp_path)
    service.pick_contractor_file(path.name, path=path)
    service.run(echo=lambda s: None, confirm=lambda c: False, match=False)
    before = service.home_summary()
    assert (before.contractors, before.jobs, before.jobs_waiting) == (1, 3, 3)
    assert before.matches_waiting == 0 and before.last_contractors_at is not None
    assert before.last_run_at is not None
    service.run(echo=lambda s: None, confirm=lambda c: False)
    after = service.home_summary()
    assert (after.jobs_waiting, after.matches_waiting) == (0, 2)  # two jobs have a candidate
    service.decide(service.results()[0].matches[0].match.match_id, Decision.APPROVED)
    assert service.home_summary().matches_waiting == 1


def test_home_summary_on_a_fresh_empty_data_dir(service: AppService) -> None:
    assert not service.data_dir.exists() or not any(service.data_dir.iterdir())
    summary = service.home_summary()
    assert (summary.contractors, summary.jobs, summary.jobs_waiting) == (0, 0, 0)
    assert summary.matches_waiting == 0 and summary.last_run_at is None


def test_talent_overview_carries_availability_and_profile_age(service: AppService) -> None:
    upsert_contractors(
        [
            ContractorProfile(
                talent_id="TAL-9",
                talent_name="Jo Lee",
                rate_expectation="90",
                availability="From 2026-12-01",
                profile_updated=date(2026, 11, 2),
            ),
            ContractorProfile(talent_id="TAL-8", talent_name="Sam Roy", rate_expectation="90"),
        ],
        CsvContractorProfileRepository(service.settings.paths.contractors_csv, lock_timeout=5),
    )
    by_id = {t.talent_id: t for t in service.talent_overview()}
    assert by_id["TAL-9"].availability == "From 2026-12-01"
    assert by_id["TAL-9"].profile_updated == date(2026, 11, 2)
    assert by_id["TAL-8"].availability is None and by_id["TAL-8"].profile_updated is None
