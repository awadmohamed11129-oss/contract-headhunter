"""Contractor folders and résumés (user decision 2026-11-09): the reviewer picks one folder
with a contractor file and a resume/ folder of <talent_id>.pdf; the app copies the PDFs into
data/contractors/resumes/ and shows them from the Talent card. No network, no Gemini call for
a résumé."""

import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobmatch.app.service import AppError, AppService
from jobmatch.config import Settings
from jobmatch.schemas import ContractorProfile, Job
from jobmatch.sources.contractor_upsert import upsert_contractors
from jobmatch.sources.resumes import (
    ContractorFolderError,
    read_contractor_folder,
    resumes_dir,
    store_resumes,
    stored_resume,
    unpack_zips,
)
from jobmatch.storage.csv_store import CsvContractorProfileRepository, CsvJobRepository, CsvStore
from test_app_ui import run_ui
from test_ingest import EN_CONTRACT
from test_talent import MarkerGemini

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def pdf(path: Path, text: str = "CV") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% " + text.encode() + b"\n%%EOF\n")
    return path


def people() -> list[ContractorProfile]:
    return [
        ContractorProfile(
            talent_id="TAL-CAN-0001", talent_name="Alex Martin", rate_expectation="90",
            standardized_headline="Data Analyst",
            executive_summary="Builds dashboards in Power BI for public agencies. Marker95.",
        ),
        ContractorProfile(
            talent_id="TAL-CAN-0002", talent_name="Émilie Tremblay", rate_expectation="95",
            standardized_headline="Analyste de données",
            executive_summary="Tableaux de bord Power BI pour la Ville de Québec. Marker90.",
        ),
    ]  # fmt: skip


def folder(tmp_path: Path, resume_name: str = "resume") -> Path:
    root = tmp_path / "Contractors"
    upsert_contractors(
        people(), CsvContractorProfileRepository(root / "contractors.csv", lock_timeout=5)
    )
    pdf(root / resume_name / "TAL-CAN-0001.pdf", "Alex")
    pdf(root / resume_name / "tal-can-0002.PDF", "Émilie")  # case does not matter
    pdf(root / resume_name / "Jane Doe CV.pdf")  # not a talent ID: skipped
    return root


# ---- the folder ----


def test_reads_the_folder(tmp_path: Path) -> None:
    root = folder(tmp_path, "Resumes")
    (root / "~$contractors.xlsx").write_bytes(b"lock")  # Excel's lock file: ignored
    (root / ".DS_Store").write_bytes(b"")
    picked = read_contractor_folder(root)
    assert picked.contractor_file.name == "contractors.csv"
    assert sorted(picked.resumes) == ["Jane Doe CV", "TAL-CAN-0001", "tal-can-0002"]


def test_folder_mistakes(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ContractorFolderError, match="no contractor file"):
        read_contractor_folder(empty)
    root = folder(tmp_path)
    (root / "old-export.xlsx").write_bytes(b"x")
    with pytest.raises(ContractorFolderError, match="more than one contractor file"):
        read_contractor_folder(root)
    (root / "old-export.xlsx").unlink()
    pdf(root / "Resumes" / "x.pdf")
    with pytest.raises(ContractorFolderError, match="keep one"):
        read_contractor_folder(root)
    with pytest.raises(ContractorFolderError, match="not a folder"):
        read_contractor_folder(root / "contractors.csv")


def test_no_resume_folder_is_fine(tmp_path: Path) -> None:
    root = folder(tmp_path)
    for p in (root / "resume").iterdir():
        p.unlink()
    (root / "resume").rmdir()
    assert read_contractor_folder(root).resumes == {}


# ---- storing ----


def test_store_add_keep_replace(tmp_path: Path) -> None:
    data = tmp_path / "data"
    src = tmp_path / "in"
    known = ["TAL-CAN-0001", "TAL-CAN-0002"]
    files = {
        "TAL-CAN-0001": pdf(src / "a.pdf", "v1"),
        "tal-can-0002": pdf(src / "b.pdf"),
        "Jane Doe CV": pdf(src / "c.pdf"),
        "TAL-CAN-0003": pdf(src / "d.pdf"),  # not in the list
    }
    first = store_resumes(files, known, data, NOW)
    assert (first.added, first.replaced, first.unchanged, first.unmatched) == (2, 0, 0, 2)
    stored = sorted(p.name for p in resumes_dir(data).glob("*.pdf"))
    assert stored == ["TAL-CAN-0001.pdf", "TAL-CAN-0002.pdf"]

    again = store_resumes(files, known, data, NOW)
    assert (again.added, again.replaced, again.unchanged) == (0, 0, 2)

    files["TAL-CAN-0001"] = pdf(src / "a2.pdf", "v2")
    changed = store_resumes(files, known, data, NOW)
    assert (changed.added, changed.replaced, changed.unchanged) == (0, 1, 1)
    assert b"v2" in (resumes_dir(data) / "TAL-CAN-0001.pdf").read_bytes()
    [old] = (resumes_dir(data) / "old").iterdir()  # the earlier copy is kept
    assert old.name == "TAL-CAN-0001-20261109T150000Z.pdf" and b"v1" in old.read_bytes()


def test_not_a_pdf_is_skipped(tmp_path: Path) -> None:
    fake = tmp_path / "in" / "TAL-CAN-0001.pdf"
    fake.parent.mkdir()
    fake.write_bytes(b"<html>not a pdf</html>")
    report = store_resumes({"TAL-CAN-0001": fake}, ["TAL-CAN-0001"], tmp_path / "data", NOW)
    assert (report.added, report.unmatched) == (0, 1)


def test_stored_resume_only_for_known_ids(tmp_path: Path) -> None:
    pdf(resumes_dir(tmp_path) / "TAL-CAN-0001.pdf")
    known = ["TAL-CAN-0001"]
    assert stored_resume(tmp_path, "TAL-CAN-0001", known) is not None
    assert stored_resume(tmp_path, "TAL-CAN-0002", known) is None
    assert stored_resume(tmp_path, "../TAL-CAN-0001", known) is None


# ---- the app ----


@pytest.fixture
def app_with_job(
    app_settings: Settings, store: CsvStore, make_job: Callable[..., Job], tmp_path: Path
) -> tuple[AppService, MarkerGemini]:
    fake = MarkerGemini()
    service = AppService(
        app_settings, tmp_path / "app.env", provider_factory=lambda: fake, environ={}
    )
    CsvJobRepository(store).add_new([
        make_job(job_id="paste:1", source_id="1", title_norm="Analyste de données (contrat)",
                 responsibilities=["Tableaux de bord Power BI"], language="fr"),
    ])  # fmt: skip
    return service, fake


def test_pick_folder_and_run(app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path):
    service, fake = app_with_job
    root = folder(tmp_path)
    info = service.pick_contractor_folder(root)
    assert (info.contractors, info.resumes, info.unmatched) == (2, 2, ["Jane Doe CV"])
    report = service.run(echo=lambda s: None, confirm=lambda c: True)
    assert report.resumes is not None
    assert (report.resumes.added, report.resumes.unmatched) == (2, 1)
    assert "Jane" not in report.model_dump_json()  # file names stay on screen only
    assert service.contractor_file is None and service.resumes == {}
    assert {t.talent_id: t.has_resume for t in service.talent_overview()} == {
        "TAL-CAN-0001": True, "TAL-CAN-0002": True,
    }  # fmt: skip
    assert service.resume_path("TAL-CAN-0002") is not None

    # A new résumé only: copied, the old one kept, and no call to Gemini (no rescan).
    # Nothing is learned from a résumé: the contractor list stays byte for byte the same.
    stored = service.settings.paths.contractors_csv
    before = stored.read_bytes()
    calls = fake.calls
    pdf(root / "resume" / "TAL-CAN-0001.pdf", "Alex, updated. Python, Kubernetes, PMP.")
    service.pick_contractor_folder(root)
    report = service.run(echo=lambda s: None, confirm=lambda c: True)
    assert report.resumes is not None and report.resumes.replaced == 1
    assert report.contractors is not None and not report.contractors.changed
    assert fake.calls == calls
    assert stored.read_bytes() == before


def test_folder_mistake_is_shown(app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path):
    service, _ = app_with_job
    with pytest.raises(AppError, match="no contractor file"):
        service.pick_contractor_folder(tmp_path)


def test_browser_upload_takes_file_and_resumes(
    app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path
) -> None:
    service, _ = app_with_job
    root = folder(tmp_path)
    # Résumés first, then the file: the IDs in the file count as known.
    info = service.pick_contractor_file(
        "TAL-CAN-0002.pdf", data=(root / "resume" / "tal-can-0002.PDF").read_bytes()
    )
    assert (info.path, info.resumes, info.unmatched) == (None, 0, ["TAL-CAN-0002"])
    csv = root / "contractors.csv"
    info = service.pick_contractor_file(csv.name, data=csv.read_bytes())
    assert (info.contractors, info.resumes, info.unmatched) == (2, 1, [])
    with pytest.raises(AppError, match="résumés"):
        service.pick_contractor_file("notes.docx", data=b"x")
    service.run(echo=lambda s: None, confirm=lambda c: True)
    assert service.resume_path("TAL-CAN-0002") is not None
    assert service.resume_path("TAL-CAN-0001") is None


def test_talent_card_shows_the_resume(
    app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path
) -> None:
    service, _ = app_with_job
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True)
    (resumes_dir(service.data_dir) / "TAL-CAN-0002.pdf").unlink()  # one without a résumé

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/talent")
        await user.should_see(marker="resume:TAL-CAN-0001")
        await user.should_see(marker="resume:TAL-CAN-0002")  # grey, but picks a PDF here
        [none] = user.find(marker="resume:TAL-CAN-0002").elements
        assert none.enabled and none.props.get("color") == "grey-7"
        assert len(user.find(marker="resume:TAL-CAN-0002-upload").elements) == 1
        [one] = user.find(marker="resume:TAL-CAN-0001").elements
        assert one.enabled
        user.find(marker="resume:TAL-CAN-0001").click()
        await user.should_see(marker="resume-frame")
        served = await user.http_client.get("/resume/TAL-CAN-0001")
        assert served.status_code == 200
        assert served.headers["content-type"] == "application/pdf"
        assert served.content.startswith(b"%PDF-")
        for missing in ("TAL-CAN-0002", "TAL-CAN-0099", "..%2Fapp.env"):
            assert (await user.http_client.get(f"/resume/{missing}")).status_code == 404

    run_ui(service, scenario)


def test_resumes_are_never_read_for_content() -> None:
    """Résumés are only copied and served: no PDF text is extracted, so nothing from a
    résumé can reach the contractor list or Gemini (user decision 2026-11-09)."""
    import jobmatch.sources.resumes as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "pypdf" not in source and "extract_text" not in source


def test_results_resume_button(
    app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path
) -> None:
    """User request 2026-11-10: the Résumé button on a Results match opens the stored résumé,
    as on the Talent screen, and is greyed out when there is none."""
    service, _ = app_with_job
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True)
    (resumes_dir(service.data_dir) / "TAL-CAN-0002.pdf").unlink()
    [job] = service.results()
    views = {v.match.talent_id: v for v in job.matches}
    assert views["TAL-CAN-0001"].has_resume and not views["TAL-CAN-0002"].has_resume

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/results")
        with_one = views["TAL-CAN-0001"].match.match_id
        without = views["TAL-CAN-0002"].match.match_id
        [none] = user.find(marker=f"resume:{without}").elements
        assert not none.enabled
        user.find(marker=f"resume:{with_one}").click()
        await user.should_see(marker="resume-frame")

    run_ui(service, scenario)


# ---- zip (Google Drive's "Download") ----


def zipped(zip_path: Path, files: dict[str, bytes | Path], top: str = "") -> Path:
    """A zip holding `files` ({name inside: bytes or a file}), all under the folder `top`."""
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, content in files.items():
            data = content if isinstance(content, bytes) else content.read_bytes()
            archive.writestr(f"{top}/{name}" if top else name, data)
    return zip_path


def folder_files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def test_unpack_a_zip_with_a_top_folder(tmp_path: Path) -> None:
    root = folder(tmp_path)
    archive = zipped(tmp_path / "Contractors.zip", folder_files(root), top="Contractors")
    out = tmp_path / "out"
    out.mkdir()
    unpacked = unpack_zips([archive], out)
    assert unpacked == out / "Contractors"
    picked = read_contractor_folder(unpacked)
    assert picked.contractor_file.name == "contractors.csv"
    assert sorted(picked.resumes) == ["Jane Doe CV", "TAL-CAN-0001", "tal-can-0002"]


def test_unpack_a_zip_without_a_top_folder(tmp_path: Path) -> None:
    root = folder(tmp_path)
    archive = zipped(tmp_path / "flat.zip", folder_files(root))
    archive_files = {"__MACOSX/._contractors.csv": b"x"}
    with zipfile.ZipFile(archive, "a") as extra:  # macOS junk is skipped
        for name, data in archive_files.items():
            extra.writestr(name, data)
    out = tmp_path / "out"
    out.mkdir()
    assert unpack_zips([archive], out) == out


def test_several_zips_are_merged(tmp_path: Path) -> None:
    root = folder(tmp_path)
    files = folder_files(root)
    first = zipped(
        tmp_path / "c-001.zip", {"contractors.csv": files["contractors.csv"]}, "Contractors"
    )
    second = zipped(
        tmp_path / "c-002.zip",
        {k: v for k, v in files.items() if k.startswith("resume/")},
        "Contractors",
    )
    out = tmp_path / "out"
    out.mkdir()
    unpacked = unpack_zips([first, second], out)
    assert sorted(read_contractor_folder(unpacked).resumes) == [
        "Jane Doe CV", "TAL-CAN-0001", "tal-can-0002",
    ]  # fmt: skip


def test_zip_mistakes(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    evil = zipped(tmp_path / "evil.zip", {"../escaped.txt": b"x"}, "Contractors")
    with pytest.raises(ContractorFolderError, match="unsafe"):
        unpack_zips([evil], out)
    absolute = zipped(tmp_path / "abs.zip", {"/etc/passwd": b"x"})
    with pytest.raises(ContractorFolderError, match="unsafe"):
        unpack_zips([absolute], out)
    assert not (tmp_path / "escaped.txt").exists()
    empty = zipped(tmp_path / "empty.zip", {"notes.txt": b"x"}, "Contractors")
    with pytest.raises(ContractorFolderError, match="no contractor file"):
        unpack_zips([empty], out)
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    with pytest.raises(ContractorFolderError, match="not a valid zip"):
        unpack_zips([broken], out)


def test_pick_a_zip_like_the_folder(
    app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path
) -> None:
    service, _ = app_with_job
    archive = zipped(tmp_path / "Contractors.zip", folder_files(folder(tmp_path)), "Contractors")
    info = service.pick_contractor_folder(archive)  # a zip where a folder is expected
    assert (info.contractors, info.resumes, info.unmatched) == (2, 2, ["Jane Doe CV"])
    assert service.contractors_folder() == archive
    unpacked = service.contractor_file.parent
    assert unpacked.is_dir()
    report = service.run(echo=lambda s: None, confirm=lambda c: True)
    assert report.resumes is not None and report.resumes.added == 2
    assert not unpacked.exists()  # the temp copy is deleted after the run
    assert service.resume_path("TAL-CAN-0001") is not None


def test_pick_several_zips_and_a_browser_zip(
    app_with_job: tuple[AppService, MarkerGemini], tmp_path: Path
) -> None:
    service, _ = app_with_job
    files = folder_files(folder(tmp_path))
    csv_zip = zipped(tmp_path / "a.zip", {"contractors.csv": files["contractors.csv"]}, "C")
    pdf_zip = zipped(tmp_path / "b.zip", {k: v for k, v in files.items() if "/" in k}, "C")
    info = service.pick_contractor_zips([csv_zip, pdf_zip])
    assert (info.contractors, info.resumes, info.missing_resumes) == (2, 2, [])
    assert service.contractors_folder() is None  # several zips are not remembered
    service.clear_contractor_picks()

    full = zipped(tmp_path / "full.zip", files, "Contractors")
    upload = service.pick_contractor_file("Contractors.zip", data=full.read_bytes())
    assert upload.contractors == 2 and upload.path is not None
    with pytest.raises(AppError, match="no contractor file"):
        service.pick_contractor_file("only-pdfs.zip", data=pdf_zip.read_bytes())
    assert service.contractor_file == upload.path  # the earlier pick is kept


# ---- sync on start ----


def test_sync_on_start_stores_what_is_new_without_gemini(
    app_settings: Settings, tmp_path: Path
) -> None:
    fake = MarkerGemini()
    service = AppService(
        app_settings, tmp_path / "app.env", provider_factory=lambda: fake, environ={}
    )
    nothing = service.sync_on_start()
    assert not nothing.ran and nothing.problems == [] and nothing.jobs_waiting == 0

    root = folder(tmp_path)
    (root / "resume" / "tal-can-0002.PDF").unlink()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "analyst.txt").write_text(EN_CONTRACT, encoding="utf-8")
    service.pick_contractor_folder(root)
    service.set_jobs_folder(jobs)
    service.clear_contractor_picks()

    first = service.sync_on_start()
    assert first.ran and first.people_added == 2 and first.people_updated == 0
    assert first.new_job_files == 1 and first.new_jobs == 1 and first.jobs_waiting == 1
    assert first.missing_resumes == ["Émilie Tremblay"] and first.problems == []
    assert service.contractor_file is None  # nothing left picked
    assert service.resume_path("TAL-CAN-0001") is not None
    [waiting] = service.jobs_waiting()
    assert waiting.title_raw == "Senior Business Analyst (12-month contract)"

    second = service.sync_on_start()  # nothing changed: nothing is run
    assert not second.ran and second.new_jobs == 0 and second.jobs_waiting == 1
    pdf(root / "resume" / "TAL-CAN-0002.pdf", "Émilie")
    third = service.sync_on_start()  # a new résumé is picked up
    assert third.ran and third.people_added == 0 and third.missing_resumes == []
    assert service.resume_path("TAL-CAN-0002") is not None
    assert fake.calls == 0  # never a Gemini call


@pytest.mark.parametrize(
    "member", ["Contractors/D:evil.pdf", "Contractors/resume.pdf.", "Contractors/ok /a.pdf"]
)
def test_zip_names_with_a_colon_or_a_trailing_dot_or_space_are_refused(
    tmp_path: Path, member: str
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    bad = zipped(tmp_path / "bad.zip", {member: b"x"})
    with pytest.raises(ContractorFolderError, match="unsafe"):
        unpack_zips([bad], out)
    assert not any(out.rglob("*"))
