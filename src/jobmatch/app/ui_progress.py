"""Matching that never looks frozen (the progress card on Home, the pill in the header).

A search takes about a minute and a half per job. While it runs the person sees:

    Job 2 of 5: Brand Designer              about 3 min left
    [=========-------------------]          (a bar over the jobs, creeping between steps)
    the plain sentences the run already writes, as a short live feed
    each job as it finishes: its best match and a Review link

All of it is read from what the run already reports: its progress callback ("Screening jobs:
2 of 5"), its plain sentences, and the answers Gemini saved for finished jobs. Nothing is
sent to the run and nothing in the pipeline changed: the run has no way to be stopped, so
there is no Stop button.

Also here: the OS-level nudge when a search ends in the desktop app (the taskbar button
flashes on Windows, a notification on macOS; no new package, best effort).
"""

import logging
import math
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic, time
from typing import Any

from nicegui import app as nicegui_app
from nicegui import run, ui

from jobmatch.app.service import AppService, FinishedJob, PlannedJob
from jobmatch.app.ui_help import plural

logger = logging.getLogger("jobmatch.app")

SCREEN = re.compile(r"Screening jobs: (\d+) of (\d+)")  # pipeline.py, one per job sent
REVIEW = re.compile(r"Deep reviews: (\d+) of up to (\d+)")  # one per batch of shortlists
FIRST_GUESS = 85.0  # seconds a job takes, until one has been timed
FEED_LINES = 4  # plain sentences kept under the bar
REVIEW_JOB_KEY = "review_job"  # app.storage.client: the job Review mode shows first

PROGRESS_CSS = """
.dg-spin .q-icon { animation: dg-spin 1.6s linear infinite; }
@keyframes dg-spin { to { transform: rotate(360deg); } }
.dg-pill { background: rgba(255,255,255,.18); border-radius: 9999px !important; padding: 2px 14px; }
.dg-pill:hover { background: rgba(255,255,255,.28); }
.dg-feed { border-left: 3px solid #E4DFF3; padding-left: 10px; }
.dg-done-row { border-radius: .9rem; background: #fff; border: 1.5px solid #E4DFF3;
  padding: 4px 6px 4px 12px; }
"""


class RunTracker:
    """What a matching run is doing, worked out from its own progress callback (called in the
    worker thread; the screens read these plain attributes). One per RunJob."""

    def __init__(self, service: AppService) -> None:
        self.service = service
        self.reset()

    def reset(self, waiting_before: int = 0) -> None:
        self.began = time()  # clock time: judged answers newer than this belong to the run
        self.waiting_before = waiting_before  # matches waiting for a decision before the run
        self.total = 0  # jobs being sent to Gemini
        self.screened = 0  # of them, answered
        self.reviews = 0  # review batches answered
        self.saving = False
        self.plan: list[PlannedJob] = []
        self.marks: list[float] = []  # monotonic time of the start and of each screened job
        self.review_marks: list[float] = []
        self.step_since = monotonic()  # when the step now in progress began
        self.finished: list[FinishedJob] = []
        self._polled = 0.0
        self._polling = False

    # -- fed by the run (worker thread) --

    def on_progress(self, share: float, stage: str) -> None:
        now = monotonic()
        if m := SCREEN.fullmatch(stage):
            done, total = int(m.group(1)), int(m.group(2))
            if not self.total:
                self.total = total
                try:
                    self.plan = self.service.matching_plan()[:total]
                except Exception:  # noqa: BLE001 (the titles are a nicety; the bar still works)
                    logger.exception("matching_plan_failed")
                    self.plan = []
            self.screened = done
            self.marks.append(now)
            self.step_since = now
        elif m := REVIEW.fullmatch(stage):
            self.reviews = int(m.group(1))
            self.review_marks.append(now)
            self.step_since = now
        elif stage.startswith("Saving"):
            self.saving = True
            self.step_since = now

    # -- read by the screens --

    @property
    def active(self) -> bool:
        return self.total > 0

    @property
    def batches(self) -> int:
        """At most this many review calls follow the screening."""
        size = max(1, getattr(self.service.llm, "review_batch_size", 1))
        return math.ceil(self.total / size)

    @property
    def number(self) -> int:
        """The job being worked on, 1-based (the last one while the closer look goes on)."""
        return min(self.screened + 1, self.total)

    def title(self) -> str:
        from jobmatch.app.ui import title_case  # noqa: PLC0415 (ui.py imports this module)

        if self.screened < len(self.plan):
            return title_case(self.plan[self.screened].title)
        return ""

    def headline(self) -> str:
        if self.saving:
            return "Saving your results…"
        if self.screened >= self.total:
            return f"All {plural(self.total, 'job')} read. A closer look at the best people…"
        title = self.title()
        return f"Job {self.number} of {self.total}" + (f": {title}" if title else "")

    def pill(self) -> str:
        if self.saving:
            return "Matching: saving"
        if self.screened >= self.total:
            return "Matching: final checks"
        return f"Matching {self.number} of {self.total}"

    def per_job(self) -> float | None:
        """Measured seconds per finished job (None until one has finished)."""
        if len(self.marks) < 2:
            return None
        return (self.marks[-1] - self.marks[0]) / (len(self.marks) - 1)

    def review_seconds(self) -> float:
        """Seconds one review call takes: measured once one has finished, else a guess (a
        review reads a whole shortlist, so it is slower than a screening)."""
        starts = [self.marks[-1]] if self.marks and self.screened >= self.total else []
        chain = starts + self.review_marks
        if len(chain) > 1:
            return (chain[-1] - chain[0]) / (len(chain) - 1)
        return FIRST_GUESS

    def seconds_left(self, now: float | None = None) -> float | None:
        per_job = self.per_job()
        if per_job is None or self.saving:
            return None
        now = monotonic() if now is None else now
        waited = now - self.step_since
        per_review = self.review_seconds()
        if self.screened < self.total:
            current = max(per_job - waited, per_job * 0.15)
            return current + (self.total - self.screened - 1) * per_job + self.batches * per_review
        remaining = max(self.batches - self.reviews, 0)
        if not remaining:
            return 0.0
        return max(remaining * per_review - waited, per_review * 0.15)

    def eta_text(self) -> str:
        if self.saving:
            return "Almost done"
        left = self.seconds_left()
        if left is None:
            return "Working out how long this takes…" if self.screened == 0 else ""
        if left < 45:
            return "less than a minute left"
        return f"about {max(1, math.ceil(left / 60))} min left"

    def fraction(self, now: float | None = None) -> float:
        """The bar: whole steps done, plus a slow creep inside the step in progress, so a long
        job never looks stuck. Never reaches 1 by itself: the end of the run does that."""
        if not self.total:
            return 0.0
        now = monotonic() if now is None else now
        typical = self.per_job() or FIRST_GUESS
        creep = 0.9 * (1 - math.exp(-(now - self.step_since) / typical))
        return min((self.screened + self.reviews + creep) / (self.total + self.batches), 0.97)

    def refresh_now(self) -> None:
        """Look once, here and now (the run just ended: its last jobs are saved)."""
        try:
            self.finished = self.service.judged_since(datetime.fromtimestamp(self.began - 2, UTC))
        except Exception:  # noqa: BLE001 (the list is a nicety)
            logger.exception("judged_since_failed")

    async def poll(self, force: bool = False) -> bool:
        """Look for the jobs Gemini has answered since the run began. True when the list
        changed. At most one look every few seconds."""
        now = monotonic()
        if self._polling or (not force and now - self._polled < 3):
            return False
        self._polling, self._polled = True, now
        try:
            since = datetime.fromtimestamp(self.began - 2, UTC)
            found = await run.io_bound(self.service.judged_since, since)
        except Exception:  # noqa: BLE001 (a missed look is harmless: the next one tries again)
            logger.exception("judged_since_failed")
            return False
        finally:
            self._polling = False
        changed = [f.model_dump() for f in found] != [f.model_dump() for f in self.finished]
        self.finished = found
        return changed


def busy_jobs(report: Any) -> int:
    """How many jobs this run could not check because Google was busy (a 503, the per-minute
    limit, no answer in time): 0 for every other kind of trouble, which keeps its own words."""
    judge = getattr(report, "judge", None)
    if judge is None or not judge.failed or not judge.busy:
        return 0
    return report.jobs_not_judged or judge.failed


def busy_text(count: int) -> str:
    """The one plain sentence for a run that hit a busy Google (no codes)."""
    return (
        f"{plural(count, 'job')} could not be checked because Google was busy: "
        "press Find matches again in a minute."
    )


def outcome_text(job: Any) -> str:
    """What the search that just ended did, in plain words: "3 new jobs checked: 3 with
    matches". The run's own summary counts every stored job (Wilson's run_summary, which says
    "6 jobs with suggestions" when only 3 were new), so this one counts the jobs this run sent
    to Gemini. Anything else (saving without matching, nothing sent) keeps his summary. When
    Google was busy it says so, and what to do ("1 job could not be checked because Google was
    busy: press Find matches again in a minute.")."""
    from jobmatch.app.ui import run_summary  # noqa: PLC0415 (ui.py imports this module)

    report = job.report
    found = job.track.finished
    if report is None:
        return ""
    busy = busy_jobs(report)
    if report.ingest_only or not (found or busy):
        return run_summary(report)
    if not found:
        return busy_text(busy)
    matched = sum(1 for f in found if f.matches)
    parts = [f"{matched} with matches"] if matched else []
    if len(found) - matched:
        parts.append(
            "no match" if len(found) - matched == 1 else f"{len(found) - matched} with no match"
        )
    if report.jobs_not_judged and not busy:
        parts.append(f"{report.jobs_not_judged} not checked yet")
    text = f"{plural(len(found), 'new job')} checked: {', '.join(parts)}."
    if busy:
        text = f"{text} {busy_text(busy)}"
    return f"{text} {report.stopped}." if report.stopped else text


# ---- the card on Home ----


class RunPanel:
    """The progress card: headline and time left, the bar, the live feed, the finished jobs.
    Home owns it and calls tick() on its timer."""

    def __init__(self, job: Any, on_review: Callable[[str], None]) -> None:
        self.job = job
        self.on_review = on_review
        self.lines_seen = 0
        self.done_seen: list[str] = []

    def build(self) -> ui.column:
        with ui.column().classes("dg-run w-full max-w-3xl mx-auto px-5 py-4 gap-2") as self.box:
            with ui.row().classes("w-full items-baseline justify-between no-wrap gap-3"):
                self.headline = ui.label().classes("text-base font-bold min-w-0")
                self.headline.mark("run-headline")
                self.eta = ui.label().classes("text-sm text-grey-8 shrink-0").mark("run-eta")
            self.stage = ui.label("").classes("text-sm text-grey-8")
            self.bar = ui.linear_progress(value=0, show_value=False).props("rounded size=12px")
            self.bar.classes("w-full")
            self.status = ui.label("").classes("text-sm text-grey-8").mark("run-status")
            self.feed = ui.column().classes("dg-feed gap-0 w-full").mark("run-feed")
            self.done = ui.column().classes("gap-1 w-full").mark("run-done")
            self.after = ui.row().classes("w-full justify-center")
        self.box.set_visibility(False)
        return self.box

    def clear(self) -> None:
        self.lines_seen = 0
        self.done_seen = []
        self.feed.clear()
        self.done.clear()

    def tick(self) -> None:
        """Called while a run is going (and once when the card is shown again)."""
        job, track = self.job, self.job.track
        live = job.running and job.match and track.active
        for element in (self.headline, self.eta):
            element.set_visibility(live)
        self.stage.set_visibility(not live)
        if live:
            self.headline.text = track.headline()
            self.eta.text = track.eta_text()
            self.bar.value = track.fraction()
            self.status.text = (
                "Waiting for your answer about today's Gemini limit."
                if job.question is not None
                else "You can keep using the app: this carries on in the background."
            )
        self._feed(live)
        self._done()

    def _feed(self, live: bool) -> None:
        lines = [text for text, _bold in self.job.lines if text]
        self.feed.set_visibility(live and bool(lines))
        if len(lines) == self.lines_seen:
            return
        self.lines_seen = len(lines)
        self.feed.clear()
        with self.feed:
            for text in lines[-FEED_LINES:]:
                ui.label(text).classes("text-xs text-grey-7")

    def _done(self) -> None:
        from jobmatch.app.ui import title_case  # noqa: PLC0415 (ui.py imports this module)

        found = self.job.track.finished
        key = [f"{f.job_id}|{f.matches}|{f.best_score}" for f in found]
        if key == self.done_seen:
            return
        self.done_seen = key
        self.done.clear()
        with self.done:
            for f in found:
                with (
                    ui.row()
                    .classes("dg-done-row w-full items-center no-wrap gap-2")
                    .mark(f"run-done:{f.job_id}")
                ):
                    ui.icon("check_circle" if f.matches else "remove_circle_outline").classes(
                        "text-positive" if f.matches else "text-grey-6"
                    )
                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                        ui.label(title_case(f.title)).classes("text-sm font-medium truncate")
                        if f.matches:
                            who = f.best_name or "A contractor"
                            score = f" ({f.best_score})" if f.best_score is not None else ""
                            more = f" and {plural(f.matches - 1, 'other')}" if f.matches > 1 else ""
                            ui.label(f"Best new match: {who}{score}{more}").classes(
                                "text-xs text-grey-8"
                            )
                        else:
                            ui.label("No new match").classes("text-xs text-grey-7")
                    if f.matches:
                        ui.button(
                            "Review",
                            icon="playlist_add_check",
                            on_click=lambda j=f.job_id: self.on_review(j),
                        ).props("flat dense no-caps color=primary").mark(f"run-review:{f.job_id}")


def review_job(job_id: str) -> None:
    """Open Review mode on this job's matches first."""
    nicegui_app.storage.client[REVIEW_JOB_KEY] = job_id
    ui.navigate.to("/review")


# ---- the OS-level nudge when a search ends in the desktop app ----


def notify_os(title: str, text: str, window_title: str | None = None) -> None:
    """Best effort, never raises: the taskbar button flashes (Windows) or a notification shows
    (macOS) so that someone in another program notices. Uses what the OS already has."""
    try:
        if sys.platform == "win32":
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            from jobmatch.app_paths import APP_TITLE  # noqa: PLC0415

            hwnd = ctypes.windll.user32.FindWindowW(None, window_title or APP_TITLE)
            if not hwnd:
                return

            class FlashInfo(ctypes.Structure):
                _fields_ = (  # noqa: RUF012
                    ("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD),
                )

            flags = 0x3 | 0xC  # FLASHW_ALL (caption and taskbar) | FLASHW_TIMERNOFG (until used)
            info = FlashInfo(ctypes.sizeof(FlashInfo), hwnd, flags, 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        elif sys.platform == "darwin":
            subprocess.run(  # fixed arguments, the texts are passed as data, no shell
                [
                    "osascript",
                    "-e", "on run argv",
                    "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                    "-e", "end run",
                    text, title,
                ],
                check=False,
                timeout=5,
            )  # fmt: skip
    except Exception:  # noqa: BLE001 (a nudge that fails is not worth a message)
        logger.debug("os_notify_failed", exc_info=True)
