"""Get latest on screen: the link field on Settings, the Contractors and Jobs rows on Home
(where it comes from, the calm offline line) and the first-run hint. Fake Google side,
fake Gemini, no network."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from fake_sync_server import TOKEN, FakeGoogle, job_text
from jobmatch.app.service import AppService, LatestStatus, LinkTest, PartStatus
from jobmatch.app.ui_sync import calm_line, link_test_words, progress_words, row_text
from test_app_ui import run_ui

PEOPLE = [("TAL-INT-ON-001", "Ann Example"), ("TAL-INT-ON-002", "Bo Example")]


@pytest.fixture
def server() -> Iterator[FakeGoogle]:
    fake = FakeGoogle()
    fake.set_people(PEOPLE)
    fake.add_job("a.txt", job_text(1), "2026-11-20T10:00:00.000Z")
    yield fake
    fake.close()


def make(app_settings, tmp_path: Path) -> AppService:  # noqa: ANN001
    environ = {"JOBMATCH_DEV_ALLOW_LOCAL_SYNC": "1", "GEMINI_API_KEY": "fake-key-for-tests"}
    return AppService(app_settings, tmp_path / "app.env", environ=environ)


def test_the_plain_words() -> None:
    assert link_test_words(LinkTest(kind="ok", people=31, jobs=12)) == (
        "positive",
        "It works. 31 contractors and 12 jobs found.",
    )
    assert (
        "Jobs are not switched on" in link_test_words(LinkTest(kind="ok", people=1, jobs=None))[1]
    )
    assert "not recognised" in link_test_words(LinkTest(kind="bad_link"))[1]
    assert link_test_words(LinkTest(kind="offline"))[1].startswith("No internet")
    status = LatestStatus(has_link=True, problem="offline")
    assert calm_line(status) == "Could not reach your list, nothing has been downloaded yet."
    assert calm_line(LatestStatus(has_link=True)) == ""
    part = PartStatus(from_link=True)
    assert row_text("jobs", 1, part, True, None) == "1 job, from your job collector"
    assert row_text("jobs", 2, PartStatus(), True, None) == "2 jobs"  # a folder chosen by hand


def test_settings_saves_the_link_and_only_shows_its_end(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    service = make(app_settings, tmp_path)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/settings")
        await user.should_see("No do good link yet.")
        user.find(marker="sync-link-input").type(server.link)
        user.find(marker="sync-link-test").click()
        await user.should_see("It works. 2 contractors and 1 job found.", retries=40)
        user.find(marker="sync-link-save").click()
        await user.should_see("Your do good link is saved. It ends in …" + TOKEN[-4:], retries=40)
        await user.should_not_see(TOKEN)
        await user.should_not_see(server.link)

    run_ui(service, scenario)
    assert service.has_sync_link() and service.sync_pending()


def test_home_rows_say_where_the_list_comes_from_and_stay_calm_when_offline(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    service = make(app_settings, tmp_path)
    service.save_sync_link(server.link)
    service.get_latest(adopt=True)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see("2 contractors, from your intake form", marker="contractors-status")
        await user.should_see(marker="get-latest-contractors")
        server.close()
        user.find(marker="get-latest-contractors").click()
        await user.should_see(marker="sync-problem", retries=60)
        await user.should_see("showing the last copy from", marker="sync-problem")
        await user.should_see("2 contractors, from your intake form", marker="contractors-status")

    run_ui(service, scenario)
    assert service.contractor_count() == 2  # the last copy still works


def test_first_run_offers_the_link_and_loads_everything_after_it(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    service = make(app_settings, tmp_path)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see("Have a do good link? Paste it and everything loads by itself.")
        user.find(marker="guide-paste-link").click()
        user.find(marker="sync-link-input").type(server.link)
        user.find(marker="sync-link-save").click()
        await user.should_see(
            "2 contractors, from your intake form", marker="contractors-status", retries=80
        )

    run_ui(service, scenario)
    assert service.contractor_count() == 2 and not service.sync_pending()


def test_the_first_run_card_has_its_own_get_latest_because_the_rows_are_hidden(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    environ = {"JOBMATCH_DEV_ALLOW_LOCAL_SYNC": "1"}  # no Gemini key yet: the checklist stays
    service = AppService(app_settings, tmp_path / "app.env", environ=environ)
    service.save_sync_link(server.link)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="first-run-guide")
        await user.should_see(marker="guide-get-latest", retries=60)

    run_ui(service, scenario)


def test_progress_words_and_the_link_is_always_the_do_good_link() -> None:
    from jobmatch.sync_client import Progress

    progress = Progress()
    assert progress_words(progress) == "Getting your latest list…"
    progress.set("contractors", found=3)
    assert progress_words(progress) == "Getting your contractors… 3 found"
    progress.set("jobs", found=40, total=71)
    assert progress_words(progress) == "Getting your jobs… 40 of 71"
    progress.set("jobs", found=12)
    assert progress_words(progress) == "Getting your jobs… 12 found so far"
    progress.set("reading")
    assert progress_words(progress) == "Reading what arrived…"
    assert "do good link" in link_test_words(LinkTest(kind="bad_link"))[1]
    assert "do good link" in calm_line(LatestStatus(has_link=True, problem="bad_link"))


def test_first_get_latest_is_the_baseline_not_new(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    service = make(app_settings, tmp_path)
    service.note_app_opened()
    service.save_sync_link(server.link)
    service.get_latest(adopt=True)
    found = service.new_items()
    assert found.people == set() and found.jobs == set()
    status = service.latest_status()  # the "+N new" badges on the Home rows
    assert status.contractors.new == 0 and status.jobs.new == 0

    server.add_job("b.txt", job_text(2), "2026-11-21T10:00:00.000Z")  # a later load adds one
    service.get_latest()
    assert service.latest_status().jobs.new == 1 and service.latest_status().contractors.new == 0
    assert len(service.new_items().jobs) == 1
