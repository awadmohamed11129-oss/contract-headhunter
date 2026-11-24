"""Home's next step, "new since last time", plain dates and the matching progress that is read
from the run's own steps. Fake Gemini, no network."""

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobmatch.app import ui_progress
from jobmatch.app.service import AppService, FinishedJob
from jobmatch.app.ui import run_summary
from jobmatch.app.ui_help import plain_dates_in, plain_day, plain_when
from jobmatch.app.ui_progress import RunTracker, busy_jobs, outcome_text
from jobmatch.llm.judge import JudgeRunReport
from jobmatch.pipeline import RunOnceReport
from jobmatch.schemas import Decision
from jobmatch.storage.csv_store import CsvJobRepository
from test_app_ui import run_ui
from test_ingest import EN_CONTRACT, FR_FULL_SAME_URL
from test_resumes import folder
from test_talent import talent  # noqa: F401 (fixture)
from test_ui_home import keyed_service


def test_dates_are_plain() -> None:
    assert plain_day(date(2026, 12, 26)) == "Dec 26, 2026"
    assert plain_dates_in("Available from 2026-12-26") == "Available from Dec 26, 2026"
    assert plain_dates_in("Booked 2026-13-45") == "Booked 2026-13-45"  # not a date: as written
    now = datetime(2026, 11, 24, 15, 0)
    assert plain_when(datetime(2026, 11, 24, 9, 12), now) == "today 9:12 am"
    assert plain_when(datetime(2026, 11, 23, 16, 5), now) == "yesterday 4:05 pm"
    assert plain_when(datetime(2026, 11, 24, 0, 5), now) == "today 12:05 am"
    assert plain_when(datetime(2026, 12, 26, 9, 12), now) == "Dec 26, 2026"


def test_new_since_last_time(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.note_app_opened()  # the first start: nothing can be new yet
    assert service.new_items().people == set() and service.new_items().jobs == set()

    service.pick_contractor_folder(folder(tmp_path))
    service.add_jobs_file("analyst.txt", EN_CONTRACT.encode())
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)

    # The first load is the baseline: even after a restart none of it is "new".
    again = AppService(
        app_settings, tmp_path / "app.env", provider_factory=service._provider_factory, environ={}
    )
    again.note_app_opened()
    assert again.new_items().people == set() and again.new_items().jobs == set()

    # What arrives after the first load is new, until its screen is opened.
    again.add_jobs_file("second.txt", FR_FULL_SAME_URL.replace("1/", "2/").encode())
    again.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    found = again.new_items()
    assert len(found.jobs) == 1 and found.people == set()
    again.mark_seen("jobs")  # the Jobs screen was opened: that job is no longer new
    assert again.new_items().jobs == set()


def test_a_list_loaded_by_an_older_version_counts_as_before(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.note_app_opened()
    service.pick_contractor_folder(folder(tmp_path))
    service.add_jobs_file("analyst.txt", EN_CONTRACT.encode())
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)
    state = service._state()
    for key in ("people_baseline_at", "jobs_baseline_at"):  # as if the state file predates them
        state.pop(key)
    (service.env_path.parent / "app_state.json").write_text(json.dumps(state), encoding="utf-8")
    again = AppService(
        app_settings, tmp_path / "app.env", provider_factory=service._provider_factory, environ={}
    )
    again.note_app_opened()
    found = again.new_items()
    assert len(found.people) == 2 and len(found.jobs) == 1


def test_the_tracker_reads_the_runs_own_steps(service: AppService, monkeypatch) -> None:  # noqa: ANN001
    clock = {"now": 100.0}
    monkeypatch.setattr(ui_progress, "monotonic", lambda: clock["now"])
    track = RunTracker(service)
    assert not track.active and track.fraction() == 0.0

    track.on_progress(0.2, "Screening jobs: 0 of 3")  # sent to Gemini: 3 jobs
    assert track.active and track.headline() == "Job 1 of 3" and track.pill() == "Matching 1 of 3"
    assert track.eta_text() == "Working out how long this takes…"  # nothing finished yet
    for done in (1, 2):  # ten seconds a job
        clock["now"] += 10
        track.on_progress(0.3, f"Screening jobs: {done} of 3")
    assert track.headline() == "Job 3 of 3" and track.per_job() == pytest.approx(10.0)
    # 10 s for the job in progress + the review calls, guessed at 85 s each until one is timed
    expected = 10 + track.batches * ui_progress.FIRST_GUESS
    assert track.seconds_left() == pytest.approx(expected)
    assert track.eta_text() == f"about {math.ceil(expected / 60)} min left"
    before = track.fraction()
    clock["now"] += 5
    assert before < track.fraction() < 1.0  # creeps inside the step, never reaches the end

    clock["now"] += 10
    track.on_progress(0.6, "Screening jobs: 3 of 3")
    assert track.pill() == "Matching: final checks" and "closer look" in track.headline()
    track.on_progress(0.9, "Saving shortlists")
    assert track.headline() == "Saving your results…" and track.eta_text() == "Almost done"
    assert track.fraction() <= 0.97


def _one_job(store, make_job) -> None:  # noqa: ANN001
    CsvJobRepository(store).add_new(
        [
            make_job(
                job_id="paste:1",
                source_id="1",
                title_norm="Data Analyst (contract)",
                responsibilities=["Build Power BI dashboards"],
            )
        ]
    )


def test_a_run_can_be_followed_without_touching_it(app_settings, store, make_job, tmp_path: Path):  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    _one_job(store, make_job)
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)  # people are stored

    plan = service.matching_plan()  # what the search is about to send, in order
    assert [p.job_id for p in plan] == ["paste:1"] and plan[0].title.startswith("Data Analyst")
    began = datetime.now(UTC) - timedelta(seconds=5)
    assert service.judged_since(began) == []

    service.run(echo=lambda s: None, confirm=lambda c: True)
    [done] = service.judged_since(began)  # read from the saved answer, nothing written
    assert done.job_id == "paste:1" and done.matches >= 1 and done.best_name
    assert service.matching_plan() == []  # nothing left to send
    assert service.matches_waiting() >= 1


def test_home_shows_one_next_step(app_settings, store, make_job, tmp_path: Path) -> None:  # noqa: ANN001
    service = keyed_service(app_settings, tmp_path)
    service.pick_contractor_folder(folder(tmp_path))
    _one_job(store, make_job)
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)

    async def find(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see("Find matches for 1 new job")
        await user.should_not_see(marker="review-button")
        await user.should_see(marker="contractors-row")  # one line, not a big card

    run_ui(service, find)

    service.run(echo=lambda s: None, confirm=lambda c: True)

    async def review(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="review-button")
        await user.should_not_see("matches waiting for your decision.")  # said once, by the button
        await user.should_see(marker="flow-matches")

    run_ui(service, review)

    while queue := service.review_queue():  # a decision can seat the next person
        for item in queue:
            service.decide(item.view.match.match_id, Decision.APPROVED)

    async def caught_up(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="caught-up")
        await user.should_see("All caught up")
        await user.should_see("approved", marker="caught-up-note")

    run_ui(service, caught_up)


def test_no_key_says_add_your_key(app_settings, store, make_job, tmp_path: Path) -> None:  # noqa: ANN001
    service = AppService(app_settings, tmp_path / "app.env", provider_factory=None, environ={})
    service.pick_contractor_folder(folder(tmp_path))
    _one_job(store, make_job)
    service.run(echo=lambda s: None, confirm=lambda c: True, match=False)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="add-key")
        user.find(marker="add-key").click()
        await user.should_see(marker="key-dialog-input")

    run_ui(service, scenario)


def test_a_fresh_app_shows_the_three_steps(service: AppService) -> None:
    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        await user.should_see(marker="first-run-guide")
        for n in (1, 2, 3):
            await user.should_see(marker=f"guide-step-{n}")
        await user.should_see("Add your key")
        await user.should_see("Load contractors")
        await user.should_see("Load jobs")
        await user.should_see(marker="guide-key-help")
        await user.should_not_see(marker="flow")  # no tiles on a brand-new app

    run_ui(service, scenario)


def _ended_run(report, finished) -> SimpleNamespace:  # noqa: ANN001, ANN202
    return SimpleNamespace(report=report, track=SimpleNamespace(finished=finished))


def test_the_result_counts_this_runs_jobs_not_every_stored_job() -> None:
    def found(n: int, matches: int) -> list[FinishedJob]:
        return [FinishedJob(job_id=f"j{i}", title="T", matches=matches) for i in range(n)]

    # Wilson's summary counts all 6 stored jobs; the run only checked the 3 new ones.
    report = RunOnceReport(run_id="r", jobs_matched=6, jobs_no_match=0)
    assert outcome_text(_ended_run(report, found(3, 2))) == "3 new jobs checked: 3 with matches."
    assert "6 jobs with suggestions" in run_summary(report)  # his function is unchanged
    mixed = found(2, 1) + found(1, 0)
    assert (
        outcome_text(_ended_run(report, mixed)) == "3 new jobs checked: 2 with matches, no match."
    )
    assert outcome_text(_ended_run(report, found(1, 0))) == "1 new job checked: no match."
    short = RunOnceReport(run_id="r", jobs_not_judged=2, stopped="Stopped: daily limit")
    assert outcome_text(_ended_run(short, found(1, 1))) == (
        "1 new job checked: 1 with matches, 2 not checked yet. Stopped: daily limit."
    )
    saved = RunOnceReport(run_id="r", ingest_only=True)  # saved without matching: his words
    assert outcome_text(_ended_run(saved, [])) == run_summary(saved)
    assert outcome_text(_ended_run(report, [])) == run_summary(report)  # nothing read back


def test_a_busy_google_is_said_plainly() -> None:
    def judged(failed: int, busy: int) -> JudgeRunReport:
        return JudgeRunReport(planned=3, cached=0, sent=3, ok=3 - failed, failed=failed, busy=busy)

    one = [FinishedJob(job_id=f"j{i}", title="T", matches=1) for i in range(2)]
    busy = RunOnceReport(run_id="r", jobs_not_judged=1, judge=judged(1, 1))
    sentence = (
        "1 job could not be checked because Google was busy: press Find matches again in a minute."
    )
    assert busy_jobs(busy) == 1
    assert outcome_text(_ended_run(busy, one)) == f"2 new jobs checked: 2 with matches. {sentence}"
    assert outcome_text(_ended_run(busy, [])) == sentence  # nothing was checked at all
    # Other trouble keeps its own words and is not called "busy".
    other = RunOnceReport(run_id="r", jobs_not_judged=1, judge=judged(1, 0))
    assert busy_jobs(other) == 0
    assert (
        outcome_text(_ended_run(other, one))
        == "2 new jobs checked: 2 with matches, 1 not checked yet."
    )


def test_the_finished_message_never_says_nothing_new_after_a_busy_google(
    app_settings,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    from jobmatch.app import ui as ui_module

    service = keyed_service(app_settings, tmp_path)
    job = ui_module.run_job(service)
    job.report = RunOnceReport(
        run_id="r", jobs_not_judged=1, judge=JudgeRunReport(
            planned=1, cached=0, sent=1, ok=0, failed=1, busy=1
        ),
    )  # fmt: skip

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        job.finished += 1  # a run just ended, on whichever tab is open
        await user.should_see("could not be checked because Google was busy", retries=20)
        await user.should_not_see("nothing new to review")

    run_ui(service, scenario)


def test_find_matches_without_a_key_opens_the_key_step(app_settings, tmp_path: Path) -> None:  # noqa: ANN001
    service = AppService(app_settings, tmp_path / "app.env", environ={})  # no key, no fake Gemini
    assert service.needs_key()

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        user.find(marker="find-matches").click()
        await user.should_see("Add your Gemini key")
        await user.should_see(marker="key-dialog-input")
        await user.should_not_see("did not finish")

    run_ui(service, scenario)


def test_the_profile_popup_is_a_read_view_until_edit(talent) -> None:  # noqa: ANN001, F811
    service, _ = talent
    service.save_profile("TAL-1", {}, "Call back Monday")

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/talent")
        user.find(marker="profile:TAL-1").click()
        await user.should_see("Profile: Person 1")
        await user.should_see("Call back Monday", marker="profile-note-view")
        await user.should_not_see(marker="profile-save")
        await user.should_not_see(marker="profile-note")
        user.find(marker="profile-edit").click()  # the same Edit as before: fields, note, Save
        await user.should_see(marker="profile-save")
        await user.should_see(marker="profile-note")
        await user.should_see(marker="profile-field:standardized_headline")
        await user.should_not_see(marker="profile-note-view")

    run_ui(service, scenario)
