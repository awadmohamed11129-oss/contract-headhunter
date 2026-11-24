"""The Home screen and the small UI helpers around it: first-run guide, plain failure message
with "Try again", matching that starts by itself, the "Match N jobs now?" question, dropped
files, copy ID / Open in Sheet. Fake Gemini, no network."""

from datetime import date
from pathlib import Path

from jobmatch.app.service import AppError, AppService
from jobmatch.app.ui import RunJob, profile_age, run_job
from jobmatch.app.ui_home import classify_dropped, guide_state, set_guide_state
from test_app_ui import run_ui
from test_ingest import EN_CONTRACT, FR_FULL_SAME_URL
from test_ingest_only import make_service
from test_resumes import folder

KEY = {"GEMINI_API_KEY": "fake-key-for-tests"}


def keyed_service(app_settings, tmp_path: Path, fake=None) -> AppService:  # noqa: ANN001
    from test_talent import MarkerGemini

    fake = fake or MarkerGemini()
    service = AppService(
        app_settings, tmp_path / "app.env", provider_factory=lambda: fake, environ=dict(KEY)
    )
    service.fake = fake  # type: ignore[attr-defined]
    return service


async def drop(user, *paths: Path) -> None:  # noqa: ANN001
    """What dropping files on the window does: the hidden upload box receives them."""
    from nicegui.elements.upload_files import SmallFileUpload

    [upload] = user.find(marker="window-drop-upload").elements
    await upload.handle_uploads(  # type: ignore[attr-defined]
        [SmallFileUpload(p.name, "text/plain", p.read_bytes()) for p in paths]
    )


def test_dropped_files_are_told_apart() -> None:
    contractors = b"talent_id,full_name\nTAL-1,Ann\n"
    jobs = b"url,job_title\nhttps://x.example/1,Analyst\n"
    assert classify_dropped("list.csv", contractors) == "contractors"
    assert classify_dropped("jobs.csv", jobs) == "jobs"
    assert classify_dropped("Contractors.zip", b"PK") == "contractors"
    assert classify_dropped("people.xlsx", b"PK") == "contractors"
    assert classify_dropped("TAL-INT-ON-001.pdf", b"%PDF") == "contractors"  # a résumé
    assert classify_dropped("posting.pdf", b"%PDF") == "pdf"  # a posting or a résumé: ask
    assert classify_dropped("EMP-7.pdf", b"%PDF", "EMP-") == "contractors"  # prefix from config
    assert classify_dropped("TAL-7.pdf", b"%PDF", "EMP-") == "pdf"
    assert classify_dropped("posting.txt", b"url: x") == "jobs"
    assert classify_dropped("photo.png", b"") == ""


def test_profile_age_words() -> None:
    today = date(2026, 11, 18)
    text, old = profile_age(date(2026, 3, 1), today)  # type: ignore[misc]
    assert "Mar 1, 2026" in text and "2026-03-01" not in text and "8 months ago" in text and old
    text, old = profile_age(date(2026, 11, 10), today)  # type: ignore[misc]
    assert "this month" in text and not old
    assert profile_age(None, today) is None


def test_first_run_guide_shows_on_a_new_app_and_can_be_skipped(service: AppService) -> None:
    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="first-run-guide")
        await user.should_see("Load contractors")
        user.find(marker="skip-guide").click()
        await user.should_not_see(marker="first-run-guide")
        await user.open("/")
        await user.should_not_see(marker="first-run-guide")  # never shown again

    run_ui(service, scenario)
    assert guide_state(service) == "done"


def test_guide_is_not_shown_when_the_app_already_has_data(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service, _ = make_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="flow-contractors")
        await user.should_see("2", marker="flow-contractors-count")
        await user.should_not_see(marker="first-run-guide")

    run_ui(service, scenario)
    assert guide_state(service) == ""  # never written for an app that has data


def test_guide_started_stays_until_done(service: AppService) -> None:
    set_guide_state(service, "done")

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_not_see(marker="first-run-guide")

    run_ui(service, scenario)


def test_a_failed_search_says_it_plainly_and_offers_try_again(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    def no_key():  # noqa: ANN202
        raise AppError("Add your Gemini key in Settings first.")

    service = AppService(app_settings, tmp_path / "app.env", provider_factory=no_key, environ={})
    service.pick_contractor_folder(folder(tmp_path))
    service.add_jobs_file("analyst.txt", EN_CONTRACT.encode())

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        user.find(marker="find-matches").click()
        await user.should_see(marker="failure-card", retries=60)
        await user.should_see("There is no Gemini key yet.")
        await user.should_see(marker="try-again")

    run_ui(service, scenario)
    job = run_job(service)
    assert isinstance(job, RunJob) and job.error is not None


def test_a_job_file_starts_matching_by_itself(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    posting = tmp_path / "analyst.txt"
    posting.write_text(EN_CONTRACT, encoding="utf-8")

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await drop(user, posting)
        await user.should_see("checked:", retries=120)  # no click on Find matches

    run_ui(service, scenario)
    assert service.fake.calls >= 1  # type: ignore[attr-defined]


def test_several_job_files_ask_before_matching(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text(EN_CONTRACT, encoding="utf-8")
    second.write_text(FR_FULL_SAME_URL.replace("1/", "2/"), encoding="utf-8")

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await drop(user, first, second)
        await user.should_see(marker="match-offer", retries=120)
        await user.should_see("now?")
        user.find(marker="match-offer-later").click()

    run_ui(service, scenario)
    assert service.fake.calls == 0  # type: ignore[attr-defined]  # "Not now": nothing sent


def test_talent_shows_copy_id_and_open_in_sheet_only_with_a_sheet_link(
    app_settings,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    service, _ = make_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)

    async def without(user) -> None:  # noqa: ANN001
        await user.open("/talent")
        await user.should_see(marker="copy-id:TAL-CAN-0001")
        await user.should_not_see(marker="open-sheet:TAL-CAN-0001")

    run_ui(service, without)
    service.save_link("intake_sheet", "https://sheets.example.com/contractors")

    async def with_link(user) -> None:  # noqa: ANN001
        await user.open("/talent")
        await user.should_see(marker="open-sheet:TAL-CAN-0001")

    run_ui(service, with_link)


def test_settings_remembers_folders_and_links(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service, _ = make_service(app_settings, tmp_path)
    jobs_dir = tmp_path / "jobs-in"
    jobs_dir.mkdir()

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/settings")
        await user.should_see("Folders and links")
        user.find(marker="setting-jobs-folder").type(str(jobs_dir))
        user.find(marker="setting-jobs-folder-save").click()
        user.find(marker="setting-link:intake_form").type("https://forms.example.com/in")
        user.find(marker="setting-links-save").click()
        await user.should_see("Links saved.")

    run_ui(service, scenario)
    assert service.jobs_folder() == jobs_dir
    assert service.links()["intake_form"] == "https://forms.example.com/in"


def test_a_pdf_not_named_by_a_talent_id_is_asked_about_and_never_auto_matched(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    service = keyed_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    cv = tmp_path / "Jane Doe CV.pdf"
    cv.write_bytes(b"%PDF-1.4 a resume")

    async def cancel(user) -> None:  # noqa: ANN001
        await user.open("/")
        await drop(user, cv)
        await user.should_see("Is this a job post or a resume?")
        user.find(marker="pdf-cancel").click()
        await user.should_see(marker="find-matches")  # back on the screen, nothing added

    run_ui(service, cancel)
    assert not list((service.data_dir / "inbox").rglob("*.pdf"))  # nothing was stored

    async def as_resume(user) -> None:  # noqa: ANN001
        await user.open("/")
        await drop(user, cv)
        await user.should_see(marker="pdf-resume")
        user.find(marker="pdf-resume").click()
        await user.should_see("Skipped (not named by a talent ID)")

    run_ui(service, as_resume)
    assert not list((service.data_dir / "inbox").rglob("*.pdf"))

    async def as_job(user) -> None:  # noqa: ANN001
        await user.open("/")
        await drop(user, cv)
        await user.should_see(marker="pdf-job")
        user.find(marker="pdf-job").click()
        await user.should_see("Saved:", retries=120)  # saved only; never "Done:" (matched)

    run_ui(service, as_job)
    assert service.fake.calls == 0  # type: ignore[attr-defined]


def test_one_new_job_with_older_ones_waiting_asks_first(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    service.add_jobs_file("old.txt", EN_CONTRACT.encode())
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)  # stored, not matched
    assert len(service.jobs_waiting()) == 1
    newer = tmp_path / "new.txt"
    newer.write_text(FR_FULL_SAME_URL.replace("1/", "2/"), encoding="utf-8")

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await drop(user, newer)
        await user.should_see("Match 2 jobs now?", retries=120)
        user.find(marker="match-offer-later").click()

    run_ui(service, scenario)
    assert service.fake.calls == 0  # type: ignore[attr-defined]  # the backlog was not sent


def test_the_start_up_check_blocks_the_buttons_until_it_ends(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    import threading

    release = threading.Event()

    class Slow(AppService):
        def sync_on_start(self):  # noqa: ANN201
            release.wait(10)
            return super().sync_on_start()

    from test_talent import MarkerGemini

    service = Slow(
        app_settings, tmp_path / "app.env", provider_factory=MarkerGemini, environ=dict(KEY)
    )

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="checking-folders", retries=60)
        [button] = user.find(marker="find-matches").elements
        assert not button.enabled and run_job(service).syncing
        assert not run_job(service).start(match=True)
        release.set()
        await user.should_not_see(marker="checking-folders", retries=60)
        assert button.enabled and not run_job(service).syncing

    try:
        run_ui(service, scenario)
    finally:
        release.set()
