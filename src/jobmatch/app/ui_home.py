"""The Home screen ("/"): one place for the whole pipeline.

    Contractors  ->  Jobs  ->  Matches  ->  Approved        (live counts, each opens its screen,
                                                             "+3 new" badges)
    ONE main action that follows the state                  (Add your key / Load ... / Find matches
                                                             for 4 new jobs / Review 6 matches /
                                                             All caught up)
    what else needs attention                               (one line each, with its button)
    Contractors and Jobs as one-line status rows            (the drop zones open on first run or
                                                             on "Change...")

Also here: the first-run checklist (key, contractors, jobs: ticks itself, goes away when all
three are done), the live progress card of a matching run (ui_progress.py), matching
that starts by itself after jobs are added, the plain failure message with "Try again", the
"Match N jobs now?" prompt and the sync with the remembered folders when the app opens.
The run itself (RunJob) and the file pickers stay in ui.py.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from nicegui import app as nicegui_app
from nicegui import run, ui
from nicegui.events import GenericEventArguments, UploadEventArguments

from jobmatch.app.service import (
    JOB_SUFFIXES,
    UPLOAD_SUFFIXES,
    AppError,
    AppService,
    ContractorFileInfo,
    LatestStatus,
    NewItems,
)
from jobmatch.app.ui import (
    _FOLDER_JS,
    JOB_FORM_CSS,
    NOTHING_PICKED,
    PAGE,
    file_picker,
    go_to_approved,
    job_form,
    pick_row,
    run_job,
)
from jobmatch.app.ui_help import (
    KEY_HELP,
    KEY_STEPS,
    KEY_URL,
    failure_card,
    help_icon,
    left_out_dialog,
    plain_when,
    plural,
    reasons_dialog,
    toast,
    window_drop,
)
from jobmatch.app.ui_progress import (
    RunPanel,
    busy_jobs,
    busy_text,
    outcome_text,
    review_job,
)
from jobmatch.app.ui_sync import LatestPanel, calm_line, link_dialog, row_text
from jobmatch.llm.usage import RunCheck
from jobmatch.sync_client import Progress, mask_secrets

logger = logging.getLogger("jobmatch.app")

HOME_CSS = """
.dg-flow { gap: 0; }
.dg-tile { flex: 1 1 0; min-width: 0; cursor: pointer; border-radius: 1.25rem; padding: 16px 18px;
  background: #FBFAFE; border: 2px solid #E4DFF3; transition: transform .15s, box-shadow .15s,
  border-color .15s; }
.dg-tile:hover { transform: translateY(-2px); box-shadow: 0 8px 22px rgba(89,59,157,.16); }
.dg-tile.hot { border-color: #593B9D; background: #F4EFFC; }
.dg-tile .num { font-size: 34px; font-weight: 800; line-height: 1; color: #2A1F4D;
  letter-spacing: -.03em; }
.dg-tile .lbl { font-weight: 700; color: #4B3499; }
.dg-tile .sub { font-size: 12.5px; color: #6B6585; min-height: 16px; }
.dg-arrow { align-self: center; color: #B9AEDB; padding: 0 6px; flex: 0 0 auto; }
@media (max-width: 700px) { .dg-flow { flex-wrap: wrap; gap: 8px; } .dg-arrow { display: none; }
  .dg-tile { flex: 1 1 40%; } }
.dg-main { padding: 10px 34px; font-size: 17px; border-radius: 1.2rem !important; }
.dg-card { padding: 18px 20px; }
.dg-card .dg-ico { width: 38px; height: 38px; border-radius: 12px; background: #F0EAFB;
  color: #593B9D; display: inline-flex; align-items: center; justify-content: center; }
.dg-drophint { border: 2px dashed #D6CCEE; border-radius: 1rem; padding: 9px 12px; color: #7A7396;
  font-size: 13px; text-align: center; }
.dg-guide { background: linear-gradient(135deg, #F4EFFC 0%, #FFFFFF 70%);
  border: 2px solid #CFC2EE !important; }
.dg-step { display: flex; align-items: flex-start; gap: 10px; flex: 1 1 0; min-width: 190px; }
.dg-step .dot { width: 34px; height: 34px; border-radius: 50%; display: inline-flex; flex: 0 0 auto;
  align-items: center; justify-content: center; font-weight: 800; background: #E4DFF3;
  color: #6B5BA6; }
.dg-step.now .dot { background: #593B9D; color: #fff; box-shadow: 0 0 0 5px rgba(89,59,157,.18); }
.dg-step.done .dot { background: #2E9D5B; color: #fff; }
.dg-step .t { font-weight: 700; color: #2A1F4D; line-height: 1.2; }
.dg-step .d { font-size: 12.5px; color: #6B6585; line-height: 1.25; }
.dg-spot { outline: 3px solid rgba(89,59,157,.55); outline-offset: 3px;
  animation: spot 1.6s ease-in-out infinite alternate; }
@keyframes spot { to { outline-color: rgba(89,59,157,.15); } }
.dg-attn { border-radius: 1rem; background: #FBFAFE; border: 1.5px solid #E4DFF3;
  padding: 8px 8px 8px 14px; }
.dg-run { border-radius: 1.25rem; background: #FBFAFE; border: 2px solid #E4DFF3; }
.dg-compact { border-radius: 1.25rem; background: #FBFAFE; border: 2px solid #E4DFF3;
  padding: 10px 16px; }
.dg-compact .dg-ico { width: 34px; height: 34px; border-radius: 11px; background: #F0EAFB;
  color: #593B9D; display: inline-flex; align-items: center; justify-content: center; }
"""

GUIDE_FILE = ".first-run"  # in the data folder: "started" while the guide may show, "done" after


# ---- the numbers on the flow strip ----


@dataclass
class Numbers:
    contractors: int
    jobs: int
    jobs_waiting: int
    matches_waiting: int  # recommended, no decision yet
    approved: int
    has_matches: bool
    last_run_at: datetime | None = None  # the last search or save
    last_contractors_at: datetime | None = None  # a contractor file was last loaded
    last_jobs_at: datetime | None = None  # jobs were last imported
    jobs_left_out: int = 0  # stored by the import, not listed (the Jobs count leaves them out)


def home_numbers(service: AppService) -> Numbers:
    """Live counts for the flow strip (from the service's home summary when it has one)."""
    summary = None
    if hasattr(service, "home_summary"):
        try:
            summary = service.home_summary()
        except Exception:  # noqa: BLE001 (the counts below still work)
            logger.exception("home_summary_failed")
    overview = service.jobs_overview()
    approved = sum(1 for o in overview for c in o.candidates if not c.removed)
    has_matches = any(o.state in ("matched", "no_match") for o in overview)
    if summary is not None:
        return Numbers(
            summary.contractors,
            summary.jobs,
            summary.jobs_waiting,
            summary.matches_waiting,
            approved,
            has_matches,
            summary.last_run_at,
            summary.last_contractors_at,
            summary.last_jobs_at,
            summary.jobs_left_out,
        )
    waiting = sum(o.state == "waiting" for o in overview)
    to_decide = sum(1 for r in service.results() for m in r.matches if m.decision is None)
    jobs, contractors = service.data_counts()
    return Numbers(contractors, jobs, waiting, to_decide, approved, has_matches)


# ---- the first-run guide state ----


def guide_state(service: AppService) -> str:
    try:
        return (service.data_dir / GUIDE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_guide_state(service: AppService, value: str) -> None:
    try:
        (service.data_dir / GUIDE_FILE).write_text(value, encoding="utf-8")
    except OSError:
        logger.warning("guide_state_not_saved")


def guide_visible(service: AppService, numbers: Numbers) -> bool:
    """Shown on a brand-new app (no contractors and no jobs) and until its three steps are
    done or it is skipped. An app that already holds data never shows it."""
    state = guide_state(service)
    if state == "done":
        return False
    if state == "started":
        return True
    if numbers.contractors == 0 and numbers.jobs == 0:
        set_guide_state(service, "started")
        return True
    return False


# ---- what a dropped file is ----


def classify_dropped(name: str, data: bytes, id_prefix: str = "TAL-") -> str:
    """ "contractors", "jobs", "pdf" or "" (not a file this screen takes). A .csv is told apart
    by its header: the contractor list has a talent_id column, the jobs file does not. A PDF
    named by a talent ID (`id_prefix`, from the config) is a résumé; any other PDF could be a
    job post or a résumé, so it is "pdf": the person is asked."""
    low = name.lower()
    stem = low.rsplit(".", 1)[0]
    if low.endswith((".zip", ".xlsx")):
        return "contractors"
    if low.endswith(".csv"):
        lines = data[:4000].decode("utf-8", errors="ignore").lower().splitlines()
        return "contractors" if lines and "talent_id" in lines[0] else "jobs"
    if low.endswith(".pdf"):
        return "contractors" if stem.startswith(id_prefix.lower()) else "pdf"
    if low.endswith(tuple(s.lower() for s in JOB_SUFFIXES)):
        return "jobs"
    return ""


class NewestFirst:
    """The "What the app did" list: plain sentences, the newest one on top."""

    MAX = 400

    def __init__(self) -> None:
        self.box = (
            ui.column()
            .classes("w-full h-[28vh] min-h-[160px] overflow-auto gap-1")
            .mark("what-the-app-did")
        )

    def push(self, text: str, bold: bool = False) -> None:
        with self.box:
            label = ui.label(mask_secrets(text)).classes("text-sm" + (" font-bold" if bold else ""))
        label.move(target_index=0)
        for old in list(self.box)[self.MAX :]:
            old.delete()

    def clear(self) -> None:
        self.box.clear()


# ---- the screen ----

# Sync with the remembered folders runs once per app start (per service), not per page visit.
_SYNCED: dict[int, Any] = {}


def home_page(service: AppService, native: bool) -> None:
    Home(service, native).build()


class Home:
    def __init__(self, service: AppService, native: bool) -> None:
        self.service = service
        self.native = native
        self.job = run_job(service)
        self.contractors_picked = False
        self.jobs_added = 0
        self.batch_jobs = 0  # jobs added since matching last started or was offered
        self.hold_match = False  # a job came from a dropped PDF: ask before matching
        self.batch_since: datetime | None = None  # when the jobs of this batch were added
        self.was_syncing = False
        self.getting = False  # "Getting latest...": the do good link is being asked
        self.progress = Progress()  # what that download is doing, for the card above the tiles
        self.offer_after_save = False
        self.auto_timer: ui.timer | None = None
        self.seen = {"lines": 0, "finished": self.job.finished, "asking": False}
        self.guide_key: tuple | None = None
        self.guide_shown = False  # the first-run checklist is on screen (it replaces the tiles)
        self.opened = {"contractors": False, "jobs": False}  # drop zones opened by "Change..."
        self.row_buttons: dict[str, tuple[ui.button, ui.button]] = {}  # (refresh icon, Get latest)
        self._n: Numbers | None = None

    # -- layout --

    def numbers(self) -> Numbers:
        """The counts for this redraw (worked out once; refresh_state() starts afresh)."""
        if self._n is None:
            self._n = home_numbers(self.service)
        return self._n

    def refresh_state(self) -> None:
        """Redraw everything that depends on the data or on the state of a run."""
        self._n = None
        self.flow.refresh()
        self.primary.refresh()
        self.attention.refresh()
        self._restyle_run_button()
        self.show_count()
        self.show_jobs_count()
        self._layout()

    def build(self) -> None:
        service = self.service
        ui.add_css(JOB_FORM_CSS)
        ui.add_css(HOME_CSS)
        with ui.column().classes(f"{PAGE} gap-5") as self.page:
            self.guide = ui.refreshable(self._guide)
            self.guide()
            self.flow = ui.refreshable(self._flow)
            self.flow()
            self.latest_panel = LatestPanel()
            self.latest_box = self.latest_panel.build()
            self.panel = RunPanel(self.job, review_job)
            self.run_panel = self.panel.build()
            self.stage, self.bar = self.panel.stage, self.panel.bar
            self.status, self.after = self.panel.status, self.panel.after
            self._actions()  # THE next step, then the quiet buttons
            self.attention = ui.refreshable(self._attention)
            self.attention()

            with ui.element("div").classes("w-full grid grid-cols-1 lg:grid-cols-2 gap-4"):
                self._contractors_card()
                self._jobs_card()
                self.sync_line = ui.refreshable(self._sync_line)
                self.sync_line()

            self.problems = ui.column().classes("w-full gap-2")
            self._spot(self._steps())
            self._links()
            self._details()

        # Drop files anywhere on the window (idea 7).
        window_drop(self.dropped)
        self._wire()
        self._layout()
        ui.timer(0.25, self.update)
        ui.timer(1.0, self._tick_guide)
        ui.timer(1.0, self._poll_done)
        if hasattr(service, "sync_on_start"):
            ui.timer(0.4, self._sync, once=True)

    # -- first-run checklist --

    def _steps(self) -> list[str]:
        n = home_numbers(self.service)
        done = [
            self.service.has_key(),
            n.contractors > 0 or self.contractors_picked,
            n.jobs > 0 or self.jobs_added > 0,
        ]
        now = next((i for i, d in enumerate(done) if not d), 3)
        return ["done" if d else "now" if i == now else "todo" for i, d in enumerate(done)]

    def _guide(self) -> None:
        """Three steps instead of the tiles on a brand-new app: each ticks itself, and the card
        goes away when all three are done (or when it is skipped)."""
        self.guide_shown = False
        n = home_numbers(self.service)
        if not guide_visible(self.service, n):
            return
        steps = self._steps()
        if all(s == "done" for s in steps):
            set_guide_state(self.service, "done")
            return
        self.guide_shown = True
        self.guide_key = tuple(steps)
        linked = self._latest().has_link
        text = [
            (
                "Add your key",
                "The key lets the app read each job against your contractors. It is free "
                "and stays on this computer.",
            ),
            (
                "Load contractors",
                "Comes from your do good link."
                if linked
                else "Choose the folder with your contractor list.",
            ),
            (
                "Load jobs",
                "Comes from your do good link."
                if linked
                else "Add a file, or type one in. Matching starts by itself.",
            ),
        ]
        with ui.card().classes("dg-guide w-full gap-3").mark("first-run-guide"):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                with ui.column().classes("gap-0"):
                    ui.label("Welcome! Let's find your first matches.").classes("text-h6")
                    ui.label("Three quick steps. Each one ticks itself when it is done.").classes(
                        "text-sm text-grey-8"
                    )
                ui.button("Skip", on_click=self._skip_guide).props(
                    "flat no-caps color=grey-8"
                ).mark("skip-guide")
            self._link_hint()
            with ui.row().classes("w-full gap-4"):
                for i, (state, (title, desc)) in enumerate(zip(steps, text, strict=True), 1):
                    with ui.element("div").classes(f"dg-step {state}").mark(f"guide-step-{i}"):
                        ui.html(
                            f'<span class="dot">{"✓" if state == "done" else i}</span>',
                            sanitize=False,
                        )
                        with ui.column().classes("gap-0"):
                            ui.label(title).classes("t")
                            ui.label(desc).classes("d")
                            if i == 1 and state != "done":
                                with ui.row().classes("gap-2 pt-2 items-center"):
                                    ui.button("Add your key", on_click=self.ask_key).props(
                                        "unelevated dense no-caps color=primary"
                                    ).classes("px-3").mark("guide-add-key")
                                    ui.button("Where do I get one?", on_click=self.key_help).props(
                                        "flat dense no-caps color=primary"
                                    ).mark("guide-key-help")
        self._spot(steps)

    def _spot(self, steps: list[str]) -> None:
        """The card of the current step gets a soft pulsing outline (steps 2 and 3)."""
        cards = (getattr(self, "contractor_card", None), getattr(self, "job_card", None))
        for step, card in enumerate(cards, 1):
            if card is None:  # the guide is drawn before the cards exist
                continue
            if steps[step] == "now":
                card.classes(add="dg-spot")
            else:
                card.classes(remove="dg-spot")

    async def _skip_guide(self) -> None:
        set_guide_state(self.service, "done")
        await self.guide.refresh()  # waits: the rows below depend on the guide being gone
        self._spot(["done", "done", "done"])
        self.refresh_state()

    async def _tick_guide(self) -> None:
        if not self.guide_shown:
            return
        if tuple(self._steps()) != self.guide_key:
            await self.guide.refresh()
            self.refresh_state()

    # -- the key (a small pop-up, so nobody has to go to Settings) --

    def key_help(self) -> None:
        """Where to get a Gemini key: three steps (the same page and button names as
        doc/FIRST_LAUNCH.md), and the page itself one click away."""
        with self.page, ui.dialog() as dialog, ui.card().classes("gap-2 max-w-md").mark("key-help"):
            ui.label("Where do I get a key?").classes("text-h6")
            for number, text in KEY_STEPS:
                with ui.row().classes("items-start gap-3 no-wrap"):
                    ui.label(str(number)).classes("text-sm font-bold text-primary shrink-0").style(
                        "width: 1.2rem"
                    )
                    ui.label(text).classes("text-sm")
            ui.label(KEY_HELP).classes("text-sm text-grey-8")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Close", on_click=dialog.close).props("flat no-caps")
                ui.button(
                    "Open Google AI Studio",
                    icon="open_in_new",
                    on_click=lambda: ui.navigate.to(KEY_URL, new_tab=True),
                ).props("unelevated no-caps color=primary").mark("key-help-open")
        dialog.on("hide", dialog.delete)
        dialog.open()

    def ask_key(self) -> None:
        with self.page, ui.dialog() as dialog, ui.card().classes("gap-2 w-[460px] max-w-full"):
            ui.label("Add your Gemini key").classes("text-h6")
            ui.label(
                "The key lets the app read each job against your contractors. It stays on "
                "this computer and is never shown again."
            ).classes("text-sm")
            field = (
                ui.input("Paste your key", password=True, password_toggle_button=True)
                .props("outlined dense autofocus")
                .classes("w-full")
                .mark("key-dialog-input")
            )

            async def save() -> None:
                try:
                    self.service.save_key(field.value or "")
                except AppError as exc:
                    ui.notify(str(exc), type="warning")
                    return
                dialog.close()
                toast("Key saved. You are ready to find matches.", icon="vpn_key", seconds=5)
                await self.guide.refresh()  # waits: the rows below depend on the guide being gone
                self.refresh_state()

            field.on("keydown.enter", save)
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("Where do I get one?", on_click=self.key_help).props(
                    "flat dense no-caps color=primary"
                ).mark("key-dialog-help")
                with ui.row().classes("gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                    ui.button("Save key", icon="save", on_click=save).props(
                        "unelevated no-caps color=primary"
                    ).mark("key-dialog-save")
        dialog.on("hide", dialog.delete)
        dialog.open()

    # -- flow strip and attention list --

    def _flow(self) -> None:
        n = self.numbers()
        if self.guide_shown or (n.contractors == 0 and n.jobs == 0):
            return  # nothing to count yet: the first-run checklist (or the main action) is the page
        try:
            new = self.service.new_items()
        except Exception:  # noqa: BLE001 (the badges are a nicety)
            logger.exception("new_items_failed")
            new = NewItems()
        hot = (
            "contractors"
            if n.contractors == 0
            else "jobs"
            if n.jobs == 0
            else "jobs"
            if n.jobs_waiting
            else "matches"
            if n.matches_waiting
            else ""
        )
        tiles = [
            ("contractors", "Contractors", n.contractors, "groups",
             lambda: ui.navigate.to("/talent"),
             "people on your list" if n.contractors else "none yet", len(new.people)),
            ("jobs", "Jobs", n.jobs, "work_outline", lambda: ui.navigate.to("/jobs"),
             f"{n.jobs_waiting} not checked yet" if n.jobs_waiting else "all checked"
             if n.jobs else "none yet", len(new.jobs)),
            ("matches", "Matches", n.matches_waiting, "auto_awesome",
             lambda: ui.navigate.to("/review" if n.matches_waiting else "/results"),
             "waiting for your decision" if n.matches_waiting else "nothing waiting", 0),
            ("approved", "Approved", n.approved, "verified",
             go_to_approved if n.approved else (lambda: ui.navigate.to("/results")),
             "people you approved" if n.approved else "none yet", 0),
        ]  # fmt: skip
        with ui.row().classes("dg-flow w-full items-stretch no-wrap").mark("flow"):
            for i, (key, label, count, icon, go, sub, fresh) in enumerate(tiles):
                if i:
                    ui.icon("arrow_forward", size="24px").classes("dg-arrow")
                tile = (
                    ui.element("div")
                    .classes("dg-tile" + (" hot" if key == hot else ""))
                    .on("click", go)
                    .mark(f"flow-{key}")
                )
                with tile, ui.column().classes("gap-1 w-full"):
                    with ui.row().classes("items-center gap-2 no-wrap w-full"):
                        ui.icon(icon, size="20px").classes("text-primary")
                        ui.label(label).classes("lbl")
                        if fresh:
                            ui.space()
                            ui.label(f"+{fresh} new").classes("dg-new").mark(f"flow-{key}-new")
                    ui.label(str(count)).classes("num").mark(f"flow-{key}-count")
                    sub_label = ui.label(sub).classes("sub")
                    if key == "jobs" and n.jobs_waiting and self.job.report is not None:
                        busy = busy_jobs(self.job.report)
                        if busy:  # the reason for "not checked yet", on hover
                            sub_label.tooltip(busy_text(busy))

    def _attention(self) -> None:
        """What else needs a look. The main action already says its own news, so it is not
        repeated here (no "6 matches waiting" under a "Review 6 matches" button)."""
        n = self.numbers()
        kind = self.primary_kind(n)
        items: list[tuple[str, str, str, Any]] = []  # icon, text, button, action
        if n.matches_waiting and kind != "review":
            items.append(
                (
                    "how_to_vote",
                    f"{plural(n.matches_waiting, 'match', 'matches')} waiting for your decision.",
                    "Review",
                    lambda: ui.navigate.to("/review"),
                )
            )
        sync = _SYNCED.get(id(self.service))
        unreadable = sync.unreadable_files if sync is not None else []
        folder_problems = [
            p for p in (sync.problems if sync is not None else []) if p not in unreadable
        ]
        if unreadable:
            items.append(
                (
                    "description",
                    f"{plural(len(unreadable), 'job file')} could not be read.",
                    "See why",
                    lambda: self.show_unreadable(unreadable),
                )
            )
        if folder_problems:
            items.append(("folder_off", "; ".join(folder_problems[:2]), "Open Settings",
                          lambda: ui.navigate.to("/settings")))  # fmt: skip
        if sync is not None and sync.missing_resumes:
            names = ", ".join(sync.missing_resumes[:4])
            more = len(sync.missing_resumes) - 4
            items.append(
                (
                    "description",
                    f"No résumé file for {names}" + (f" and {more} more" if more > 0 else "") + ".",
                    "",
                    None,
                )
            )
        with ui.column().classes("w-full gap-2").mark("attention"):
            linked = self._latest().has_link  # the rows say it ("+2 new")
            if (
                sync is not None
                and sync.ran
                and (sync.people_added or sync.new_jobs)
                and not linked
            ):
                bits = []
                if sync.people_added:
                    bits.append(f"{plural(sync.people_added, 'new person', 'new people')}")
                if sync.new_jobs:
                    bits.append(plural(sync.new_jobs, "new job"))
                with ui.row().classes("dg-attn items-center gap-3 w-full").mark("sync-note"):
                    ui.icon("sync", size="20px").classes("text-primary")
                    ui.label("Found in your folders: " + ", ".join(bits) + ".").classes("flex-1")
            if not items:
                return
            ui.label("Also needs your attention").classes("text-xs text-grey-7 uppercase font-bold")
            for icon, text, button, action in items:
                with ui.row().classes("dg-attn items-center gap-3 w-full no-wrap"):
                    ui.icon(icon, size="20px").classes("text-primary")
                    ui.label(text).classes("flex-1")
                    if button and action:
                        ui.button(button, on_click=action).props(
                            "flat no-caps dense color=primary"
                        ).mark("attention-action")

    # -- contractors --

    def _contractors_card(self) -> None:
        with ui.card().classes("dg-card w-full gap-2") as self.contractor_card:
            with ui.row().classes("items-center gap-3 no-wrap w-full"):
                with ui.element("span").classes("dg-ico"):
                    ui.icon("groups", size="22px")
                ui.label("Contractors").classes("text-h6 flex-1")
                self.hide_contractors = (
                    ui.button(icon="expand_less", on_click=lambda: self._close("contractors"))
                    .props('flat round dense size=sm color=grey-7 aria-label="Hide"')
                    .tooltip("Hide")
                    .mark("hide-contractors")
                )
                help_icon(
                    "The people you can match to jobs. Choose the folder that holds your "
                    "contractor list (a .csv or .xlsx file) and, if you have them, a folder "
                    "called resumes with one PDF per person. A .zip of that folder works too. "
                    "People already on the list are updated, not added twice."
                )
            self.count = ui.label().classes("text-sm text-grey-8").mark("contractor-count")
            self.show_count()
            self.picked = ui.label().classes("text-sm").mark("contractor-picked")
            self.missing = ui.label().classes("text-sm text-orange-9").mark("resumes-missing")
            self.skipped = ui.label().classes("text-sm text-orange-9").mark("resumes-skipped")
            self.same_name = ui.label().classes("text-sm text-orange-9").mark("same-name-note")
            if self.native:
                chooser, self.folder_note = pick_row(
                    "Choose folder…", "folder_open", "contractor-folder"
                )
                chooser.on_click(self._browse_folder)
            else:
                chooser, self.folder_note = pick_row(
                    "Choose folder…", "folder_open", "contractor-folder"
                )
                self._browser_folder(chooser)
            for label in (self.picked, self.missing, self.skipped, self.same_name):
                label.move(target_index=-1)
                label.set_visibility(False)
            ui.label("or drop the list (or a .zip of the folder) on this window").classes(
                "dg-drophint"
            )
        self.contractor_row = self._compact_row("contractors")
        self.contractor_note = (
            ui.label(
                "New sign-ups appear here once their résumé has been read, usually within the hour."
            )
            .classes("text-xs text-grey-7 lg:col-span-2 -mt-2 px-4")
            .mark("contractors-note")
        )

    def _compact_row(self, kind: str) -> ui.row:
        """Contractors / Jobs as one line: "30 contractors, updated today 9:10 am", Change…
        (opens the drop zones) and a small refresh (reads the remembered folders again)."""
        people = kind == "contractors"
        with (
            ui.row()
            .classes("dg-compact w-full lg:col-span-2 items-center gap-3 no-wrap")
            .mark(f"{kind}-row") as row
        ):
            with ui.element("span").classes("dg-ico"):
                ui.icon("groups" if people else "work_outline", size="22px")
            ui.label("Contractors" if people else "Jobs").classes("font-bold")
            status = ui.refreshable(lambda: self._status_line(kind))
            status()
            ui.button("Change…", on_click=lambda: self._open(kind)).props(
                "outline dense no-caps"
            ).classes("bg-white px-3 shrink-0").mark(f"change-{kind}")
            refresh = (
                ui.button(icon="sync", on_click=self.refresh_folders)
                .props(
                    'flat round dense size=sm color=primary aria-label="Check your folders again"'
                )
                .tooltip("Check your folders again")
                .mark(f"refresh-{kind}")
            )
            latest = (
                ui.button("Get latest", icon="sync", on_click=self.refresh_folders)
                .props("flat dense no-caps color=primary")
                .classes("px-2 shrink-0")
                .mark(f"get-latest-{kind}")
            )
            latest.set_visibility(False)
            self.row_buttons[kind] = (refresh, latest)
        if people:
            self.contractor_status = status
        else:
            self.jobs_status = status
        return row

    def _status_line(self, kind: str) -> None:
        n = self.numbers()
        people = kind == "contractors"
        count = n.contractors if people else n.jobs
        at = n.last_contractors_at if people else n.last_jobs_at
        latest = self._latest()
        part = latest.contractors if people else latest.jobs
        with ui.row().classes("flex-1 min-w-0 items-center gap-2 no-wrap"):
            if self.getting:
                text = plural(count, "contractor" if people else "job")
            else:
                text = row_text(kind, count, part, latest.has_link, at)
            ui.label(text).classes("text-sm text-grey-8 min-w-0 truncate").mark(f"{kind}-status")
            if self.getting:
                ui.spinner("dots", size="sm", color="primary")
                ui.label("Getting latest…").classes("text-sm text-primary shrink-0").mark(
                    f"{kind}-getting"
                )
            elif latest.has_link and part.from_link and part.new:
                ui.badge(f"+{part.new} new").props("color=primary").classes("shrink-0").mark(
                    f"{kind}-new"
                )
            if not people and n.jobs_left_out and not self.getting:
                ui.button(
                    f"{plural(n.jobs_left_out, 'job')} left out: see why",
                    on_click=self.show_left_out,
                ).props("flat dense no-caps color=primary").classes("shrink-0 px-1").mark(
                    "jobs-left-out"
                )

    def show_unreadable(self, problems: list[str]) -> None:
        """The job files the app could not read, each with its reason."""
        with self.page:
            reasons_dialog(
                "Job files that could not be read",
                "Fix the file, then add it again. Nothing else was affected.",
                [(text, "") for text in problems],
            )

    def show_left_out(self) -> None:
        """Which jobs the import left off the list, and why (the number the Jobs screen
        leaves out of its count)."""
        with self.page:
            left_out_dialog(self.service.jobs_left_out())

    def _latest(self) -> LatestStatus:
        """What the do good link says about the rows (an empty status when none is saved)."""
        if not hasattr(self.service, "latest_status"):
            return LatestStatus()
        try:
            return self.service.latest_status()
        except Exception:  # noqa: BLE001 (the rows still show their counts)
            logger.exception("latest_status_failed")
            return LatestStatus()

    def _sync_line(self) -> None:
        """One calm sentence when the list could not be reached; the last copy keeps working."""
        line = "" if self.getting else calm_line(self._latest())
        if not line:
            return
        with (
            ui.row()
            .classes("dg-attn items-center gap-3 w-full lg:col-span-2 no-wrap")
            .mark("sync-problem")
        ):
            ui.icon("cloud_off", size="20px").classes("text-orange-9")
            ui.label(line).classes("flex-1 text-sm")

    def _link_hint(self) -> None:
        """First run, step zero: paste a do good link and everything loads by itself."""
        if not hasattr(self.service, "has_sync_link"):
            return
        with ui.row().classes("w-full items-center gap-2 no-wrap").mark("guide-link-hint"):
            ui.icon("link", size="20px").classes("text-primary")
            if self.service.has_sync_link():
                ui.label(
                    f"Your do good link is saved ({self.service.sync_link_hint()}). "
                    "Your contractors and jobs load by themselves."
                ).classes("flex-1 text-sm")
                if self.getting:
                    ui.spinner("dots", size="sm", color="primary")
                    ui.label("Getting latest…").classes("text-sm text-primary shrink-0")
                else:  # the Contractors / Jobs rows (and their button) are hidden on a first run
                    ui.button("Get latest", icon="sync", on_click=self.refresh_folders).props(
                        "flat dense no-caps color=primary"
                    ).classes("px-2 shrink-0").mark("guide-get-latest")
                return
            ui.label("Have a do good link? Paste it and everything loads by itself.").classes(
                "flex-1 text-sm"
            )
            ui.button("Paste your do good link", on_click=self.ask_link).props(
                "unelevated dense no-caps color=primary"
            ).classes("px-3").mark("guide-paste-link")

    def ask_link(self) -> None:
        link_dialog(self.page, self.service, self._after_link_saved)

    async def _after_link_saved(self) -> None:
        with self.page:  # the pop-up's own context is gone by now (it closed)
            await self.guide.refresh()
            for _ in range(300):  # the check made while the app opened ends first (up to 30 s)
                if not (self.job.running or self.job.syncing):
                    break
                await asyncio.sleep(0.1)
            await self.refresh_folders()

    def _open(self, kind: str) -> None:
        self.opened[kind] = True
        self._layout()

    def _close(self, kind: str) -> None:
        self.opened[kind] = False
        self._layout()

    def _layout(self) -> None:
        """Contractors and Jobs are one-line rows once they hold something; the full card (with
        the drop zone) shows on the first run, while empty, after "Change…", or after a pick."""
        n = self.numbers()
        if self.guide_shown and all(step == "done" for step in self._steps()):
            self.guide_shown = False  # the card redraws itself a moment later; do not wait for it
        empty = {"contractors": n.contractors == 0, "jobs": n.jobs == 0}
        full = {k: self.guide_shown or empty[k] or self.opened[k] for k in empty}
        for kind, card, row, hide in (
            ("contractors", self.contractor_card, self.contractor_row, self.hide_contractors),
            ("jobs", self.job_card, self.job_row, self.hide_jobs),
        ):
            card.set_visibility(full[kind])
            row.set_visibility(not full[kind])
            hide.set_visibility(not (self.guide_shown or empty[kind]))
            # a card on its own takes the whole row (the other one is a one-line row)
            if full[kind] and not all(full.values()):
                card.classes(add="lg:col-span-2")
            else:
                card.classes(remove="lg:col-span-2")
        linked = self._latest().has_link
        self.contractor_note.set_visibility(linked and not full["contractors"])
        for refresh, latest in self.row_buttons.values():
            refresh.set_visibility(not linked)
            latest.set_visibility(linked)
            latest.set_enabled(not self.getting)
        self.contractor_status.refresh()
        self.jobs_status.refresh()
        self.sync_line.refresh()

    def show_count(self) -> None:
        n = self.service.contractor_count()
        self.count.text = f"{plural(n, 'contractor')} on your list." if n else "No contractors yet."

    def reset_contractors(self) -> None:
        self.folder_note.text = NOTHING_PICKED

    def show(self, info: ContractorFileInfo, source: str = "") -> None:
        self.contractors_picked = True
        self.opened["contractors"] = True
        what = []
        if info.path is not None:
            # a zip is unpacked into a stored copy: name what the person gave, not the copy
            label = source if source.lower().endswith(".zip") else info.path.name
            what.append(f"{label}: {plural(info.contractors, 'contractor')}")
        what.append(plural(info.resumes, "résumé"))
        self.picked.text = " · ".join(what) + ". Saved when you click Find matches."
        self.picked.set_visibility(True)
        missing = list(getattr(info, "missing_resumes", []) or [])
        self.missing.text = (
            "No résumé file for: " + ", ".join(missing[:12]) + (" …" if len(missing) > 12 else "")
        )
        self.missing.set_visibility(bool(missing))
        self.skipped.text = f"Skipped (not named by a talent ID): {', '.join(info.unmatched)}"
        self.skipped.set_visibility(bool(info.unmatched))
        same = list(getattr(info, "same_name", []) or [])
        self.same_name.text = "Same name, different ID (maybe a duplicate): " + ", ".join(same)
        self.same_name.set_visibility(bool(same))
        self.problems.clear()
        self.guide.refresh()
        self.refresh_state()

    def add_contractor_file(self, name: str, data: bytes) -> None:
        try:
            info = self.service.pick_contractor_file(name, data=data)
        except AppError as exc:
            self.problem(str(exc), lambda: self.add_contractor_file(name, data), "That file")
            return
        self.show(info, name)

    async def _browse_folder(self) -> None:
        from nicegui import app as nicegui_app  # noqa: PLC0415

        window = nicegui_app.native.main_window
        if window is None:
            ui.notify("The folder dialog is not available.", type="negative")
            return
        import webview  # noqa: PLC0415 (only in the desktop app)

        chosen = await window.create_file_dialog(webview.FileDialog.FOLDER)
        if not chosen:
            return
        try:
            info = self.service.pick_contractor_folder(Path(chosen[0]))
        except AppError as exc:
            self.problem(str(exc), self._browse_folder, "That folder")
            return
        self.folder_note.text = str(chosen[0])
        self.folder_note.tooltip(self.folder_note.text)
        self.show(info)

    def _browser_folder(self, chooser: ui.button) -> None:
        """The browser's own folder chooser: only the top-level contractor file and the PDFs
        in resume/ are sent, then checked one by one."""

        async def contractor(e: UploadEventArguments) -> None:
            self.add_contractor_file(e.file.name, await e.file.read())

        def chosen(e: GenericEventArguments) -> None:
            self.service.clear_contractor_picks()
            folder, files = str(e.args.get("folder", "")), int(e.args.get("files", 0))
            contractor_files = int(e.args.get("contractor_files", 0))
            self.folder_note.text = folder or NOTHING_PICKED
            if contractor_files != 1:
                self.problem(
                    f"{folder}: expected exactly one contractor file (.xlsx or .csv) at the top "
                    f"of the folder, found {contractor_files}.",
                    None,  # a folder chooser needs a direct click: the button itself is the retry
                    "That folder",
                )
            elif not files:
                ui.notify(f"{folder}: nothing to load.", type="warning")

        upload = (
            ui.upload(on_upload=contractor, auto_upload=True, multiple=True)
            .props(f'accept="{",".join(UPLOAD_SUFFIXES)}"')
            .classes("hidden")
            .mark("contractor-folder-upload")
        )
        folder_input = (
            ui.element("input").props("type=file webkitdirectory multiple").classes("hidden")
        )
        folder_input.on(
            "change", chosen, js_handler=_FOLDER_JS.replace("UPLOAD_ID", str(upload.id))
        )
        # Opened in the browser itself: a file chooser needs the click to be direct.
        chooser.on("click", js_handler=f"() => getHtmlElement({folder_input.id}).click()")

    # -- jobs --

    def _jobs_card(self) -> None:
        service = self.service
        with ui.card().classes("dg-card w-full gap-2") as self.job_card:
            with ui.row().classes("items-center gap-3 no-wrap w-full"):
                with ui.element("span").classes("dg-ico"):
                    ui.icon("work_outline", size="22px")
                ui.label("Jobs").classes("text-h6 flex-1")
                self.hide_jobs = (
                    ui.button(icon="expand_less", on_click=lambda: self._close("jobs"))
                    .props('flat round dense size=sm color=grey-7 aria-label="Hide"')
                    .tooltip("Hide")
                    .mark("hide-jobs")
                )
                help_icon(
                    "Add job postings: a jobs file (a CSV with one row per posting, from the "
                    "template), a saved posting (.txt, .html or .pdf), or type one in by hand. "
                    "Matching starts by itself once they are added. A job that is already "
                    "loaded is skipped: to change one, delete it on the Jobs screen and add "
                    "it again."
                )
            self.jobs_count = ui.label().classes("text-sm text-grey-8").mark("jobs-count")
            self.show_jobs_count()
            self.added = ui.column().classes("gap-0")
            self.reset_jobs = file_picker(
                self.native,
                JOB_SUFFIXES,
                "Jobs files",
                self.add_jobs,
                multiple=True,
                marker="jobs-files",
            )
            with ui.row().classes("items-center gap-2"):
                ui.button(
                    "Add a job by hand",
                    icon="edit_note",
                    on_click=lambda: job_form(service, self._job_typed),
                ).props("outline no-caps").classes("bg-white").mark("add-job")
                ui.button("Get CSV template", icon="download", on_click=self._template).props(
                    "flat no-caps"
                ).mark("job-template")
            self.pending = ui.refreshable(self._pending)
            self.pending()
            self.added.move(target_index=-1)
            ui.label("or drop job files on this window").classes("dg-drophint")
        self.job_row = self._compact_row("jobs")

    def show_jobs_count(self) -> None:
        jobs = self.numbers().jobs  # the same number as the tile and the Jobs screen
        self.jobs_count.text = f"{plural(jobs, 'job')} loaded." if jobs else "No jobs yet."

    def add_jobs(
        self, name: str, data: bytes, path: Path | None = None, guessed: bool = False
    ) -> None:
        """`guessed`: the file is a dropped PDF, so it is never matched without asking."""
        try:
            info = self.service.add_jobs_file(name, data)
        except AppError as exc:
            self.problem(str(exc), lambda: self.add_jobs(name, data, path), "That file")
            return
        self.problems.clear()
        if info.jobs is not None:
            what = plural(info.jobs, "job")
        else:
            what = plural(info.links, "link") if info.kind == "links" else "a posting"
        self.jobs_added += 1
        self.opened["jobs"] = True
        self.batch_jobs += info.jobs if info.jobs is not None else (info.links or 1)
        self.batch_since = self.batch_since or datetime.now(UTC)
        self.hold_match = self.hold_match or guessed
        with self.added:
            ui.label(f"Added {name}: {what}.").classes("text-sm")
            for problem in info.problems:
                ui.label(
                    f"Not added: {problem}. Fix the row in your file, then add the file again."
                ).classes("text-sm text-orange-9").mark("jobs-row-problem")
        self.guide.refresh()
        self.refresh_state()
        self.schedule_match()

    def _job_typed(self, again: bool = False) -> None:
        self.jobs_added += 1
        self.opened["jobs"] = True
        self.batch_jobs += 1
        self.batch_since = self.batch_since or datetime.now(UTC)
        self.pending.refresh()
        self.guide.refresh()
        self.refresh_state()
        if not again:
            self.schedule_match()

    def _pending(self) -> None:
        from jobmatch.app.ui import confirm_delete  # noqa: PLC0415

        entries = self.service.pending_entries()
        if not entries:
            return
        ui.label(f"Typed in by you ({len(entries)}), saved when matching starts:").classes(
            "text-sm font-medium"
        )
        for e in entries:
            with ui.row().classes("items-center gap-1 no-wrap text-sm"):
                ui.icon("edit_note", size="18px").classes("text-grey-7")
                ui.label(" · ".join(p for p in (e.title, e.company) if p))

                def remove(name: str = e.name, title: str = e.title) -> None:
                    def go() -> None:
                        try:
                            self.service.remove_entry(name)
                        except AppError as exc:
                            ui.notify(str(exc), type="warning")
                        self.pending.refresh()

                    confirm_delete(f"Remove {title}?", ["This job is not saved yet."], go)

                ui.button(icon="close", on_click=remove).props(
                    'flat round dense size=sm aria-label="Remove entry"'
                ).mark(f"remove-entry:{e.name}").tooltip("Remove this job")

    async def _template(self) -> None:
        """A new copy every time, saved where the reviewer chooses. The browser preview
        downloads it."""
        service = self.service
        if not self.native:
            ui.download(service.job_template(), "jobs-template.csv")
            return
        import webview  # noqa: PLC0415 (only in the desktop app)

        window = nicegui_app.native.main_window
        if window is None:
            ui.notify("The save dialog is not available.", type="negative")
            return
        chosen = await window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename="jobs-template.csv"
        )
        if not chosen:
            return
        dest = Path(chosen if isinstance(chosen, str) else chosen[0])
        if dest.suffix.lower() != ".csv":
            dest = dest.with_suffix(".csv")
        try:
            path = service.job_template(dest)
        except OSError as exc:
            ui.notify(f"Could not save the template: {exc}", type="negative")
            return
        ui.notify(f"Template saved: {path}", type="positive", multi_line=True)

    # -- drag and drop (idea 7) --

    async def dropped(self, name: str, data: bytes) -> None:
        kind = classify_dropped(name, data, self.service.talent_id_prefix())
        if kind == "contractors":
            self.add_contractor_file(name, data)
        elif kind == "jobs":
            self.add_jobs(name, data, None)
        elif kind == "pdf":
            self.ask_pdf(name, data)
        else:
            self.problem(
                f"{name} is not a file type this app can read. Drop a contractor list "
                "(.csv, .xlsx or .zip) or job files (.txt, .csv, .pdf or .html).",
                None,
                "That file",
            )

    def ask_pdf(self, name: str, data: bytes) -> None:
        """A PDF not named by a talent ID is never guessed: a résumé must not be saved as a job
        and sent to Gemini."""
        with self.page, ui.dialog() as dialog, ui.card().classes("gap-2").mark("pdf-kind"):
            ui.label("Is this a job post or a resume?").classes("text-h6")
            ui.label(name).classes("text-sm text-grey-8")

            def choose(as_job: bool) -> None:
                dialog.close()
                if as_job:
                    self.add_jobs(name, data, None, guessed=True)
                else:
                    self.add_contractor_file(name, data)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps").mark("pdf-cancel")
                ui.button("Resume", on_click=lambda: choose(False)).props(
                    "outline no-caps color=primary"
                ).mark("pdf-resume")
                ui.button("Job post", on_click=lambda: choose(True)).props(
                    "unelevated no-caps color=primary"
                ).mark("pdf-job")
        dialog.on("hide", dialog.delete)
        dialog.open()

    # -- failures (idea 2) --

    def problem(self, raw: str, retry: Any, what: str) -> None:
        """Replace any earlier failure with a plain one and, when it can be redone, a
        "Try again" button."""
        self.problems.clear()
        with self.problems:

            def again() -> None:
                self.problems.clear()
                if retry is not None:
                    retry()

            failure_card(raw, again if retry is not None else None, what=f"{what} did not work.")

    # -- the next step: ONE main action that follows the state --

    def primary_kind(self, n: Numbers) -> str:
        """What to do next: key, load / load_people / load_jobs, find, review or caught_up."""
        pending = self.batch_jobs + len(self.service.pending_entries())
        has_people = n.contractors > 0 or self.contractors_picked
        has_jobs = n.jobs > 0 or self.jobs_added > 0 or pending > 0
        if not self.service.has_key():
            return "key"
        if not has_people and not has_jobs:
            return "load"
        if not has_people:
            return "load_people"
        if not has_jobs:
            return "load_jobs"
        if n.jobs_waiting or pending or self.contractors_picked:
            return "find"
        if n.matches_waiting:
            return "review"
        return "caught_up"

    def _big(self, text: str, icon: str, on_click: Any, marker: str) -> ui.button:
        return (
            ui.button(text, icon=icon, on_click=on_click)
            .props("unelevated color=primary no-caps size=lg")
            .classes("dg-main")
            .mark(marker)
        )

    def _primary(self) -> None:
        """The big button under the tiles. "Find matches" is the one button that already
        exists (run_button): it takes this place by itself when matching is the next step."""
        n = self.numbers()
        kind = self.primary_kind(n)
        if self.job.running or self.guide_shown or kind == "find":
            return  # (the first-run checklist is the next step on a brand-new app)
        with ui.column().classes("items-center gap-1 text-center").mark("primary-action"):
            if kind == "key":
                self._big("Add your key", "vpn_key", self.ask_key, "add-key")
                ui.label(
                    "The key lets the app read each job against your contractors. It is free."
                ).classes("text-sm text-grey-8")
            elif kind in ("load", "load_people", "load_jobs"):
                text = {
                    "load": "Load contractors and jobs",
                    "load_people": "Load your contractors",
                    "load_jobs": "Load your jobs",
                }[kind]
                self._big(text, "upload_file", lambda: self._open_missing(kind), "load-data")
                ui.label("Drop your files anywhere on this window, or choose them below.").classes(
                    "text-sm text-grey-8"
                )
            elif kind == "review":
                from jobmatch.app.ui_review import progress_note  # noqa: PLC0415

                left = progress_note(self.service, n.matches_waiting)
                waiting = plural(n.matches_waiting, "match", "matches")
                with ui.column().classes("items-center gap-1").mark("review-area"):
                    self._big(
                        "Continue reviewing" if left else f"Review {waiting}",
                        "playlist_add_check",
                        lambda: ui.navigate.to("/review"),
                        "review-button",
                    )
                    ui.label(left or "One at a time: approve, ask for info, or reject.").classes(
                        "text-sm text-grey-8"
                    ).mark("review-left")
            else:  # caught_up
                with ui.row().classes("items-center gap-2").mark("caught-up"):
                    ui.icon("task_alt", size="32px").classes("text-positive")
                    ui.label("All caught up").classes("text-h5")
                bits = []
                if n.last_run_at:
                    bits.append(f"Last checked {plain_when(n.last_run_at)}")
                if n.approved:
                    bits.append(f"{n.approved} approved")
                ui.label(", ".join(bits) or "Nothing is waiting for you.").classes(
                    "text-sm text-grey-8"
                ).mark("caught-up-note")

    def _open_missing(self, kind: str) -> None:
        """Show the pickers for what is still missing, and point at them."""
        n = self.numbers()
        wanted = []
        if kind in ("load", "load_people") and n.contractors == 0:
            wanted.append("contractors")
        if kind in ("load", "load_jobs") and n.jobs == 0:
            wanted.append("jobs")
        for key in wanted:
            self.opened[key] = True
        self._layout()
        cards = {"contractors": self.contractor_card, "jobs": self.job_card}
        for key in wanted:
            cards[key].classes(add="dg-spot")
            ui.timer(4.0, lambda c=cards[key]: c.classes(remove="dg-spot"), once=True)
        if wanted:
            ui.run_javascript(
                f"getHtmlElement({cards[wanted[0]].id}).scrollIntoView("
                "{behavior: 'smooth', block: 'center'})"
            )

    def _restyle_run_button(self) -> None:
        """Find matches is the main button when matching is the next step (and then says how
        many jobs); otherwise it is a quieter button beside Save without matching."""
        n = self.numbers()
        big = self.primary_kind(n) == "find"
        self.run_row.set_visibility(not self.job.running)
        count = n.jobs_waiting + self.batch_jobs
        self.run_button.text = (
            f"Find matches for {plural(count, 'new job')}" if big and count else "Find matches"
        )
        self.run_button.props(remove="unelevated outline size").props(
            "unelevated size=lg" if big else "outline size=md"
        )
        if big:
            self.run_button.classes(add="dg-main", remove="bg-white")
        else:
            self.run_button.classes(remove="dg-main", add="bg-white")

    def _actions(self) -> None:
        with ui.column().classes("w-full items-center gap-2 py-1"):
            self.primary = ui.refreshable(self._primary)
            self.primary()
            with ui.row().classes("items-center justify-center gap-4") as self.run_row:
                self.run_button = (
                    ui.button("Find matches", icon="auto_awesome")
                    .props("unelevated color=primary no-caps size=lg")
                    .classes("dg-main")
                    .mark("find-matches")
                )
                self.ingest_button = (
                    ui.button("Save without matching", icon="move_to_inbox")
                    .props("flat no-caps color=grey-8")
                    .mark("ingest")
                )
                help_icon(
                    "Find matches saves what you added and asks Gemini to find the best "
                    "contractors for each new job. Save without matching only stores the "
                    "lists, so you can check them first; nothing is sent to Gemini."
                )
            self._restyle_run_button()
            self.checking = ui.label("Checking your folders…").classes("text-xs text-grey-7")
            self.checking.mark("checking-folders")
            self.checking.set_visibility(False)

    def _links(self) -> None:
        try:
            links = self.service.links() if hasattr(self.service, "links") else {}
        except Exception:  # noqa: BLE001 (the buttons are only a convenience)
            links = {}
        buttons = [
            ("intake_form", "Contractor form", "assignment_ind"),
            ("intake_sheet", "Contractor Sheet", "table_chart"),
            ("job_collector_sheet", "Jobs Sheet", "table_chart"),
        ]
        shown = [(k, t, i) for k, t, i in buttons if links.get(k)]
        if not shown:
            return
        with ui.row().classes("w-full justify-center items-center gap-2").mark("home-links"):
            ui.label("Open:").classes("text-sm text-grey-7")
            for key, text, icon in shown:
                ui.button(
                    text, icon=icon, on_click=lambda u=links[key]: ui.navigate.to(u, new_tab=True)
                ).props("flat no-caps dense color=primary").mark(f"link:{key}")

    def _details(self) -> None:
        with (
            ui.expansion("What the app did", icon="receipt_long")
            .props("dense")
            .classes("w-full text-sm text-grey-8")
        ):
            self.log = NewestFirst()
            self.quota_label = ui.label().classes("text-xs text-grey-7")
        self.show_quota()

    def show_quota(self) -> None:
        q = self.service.quota()
        self.quota_label.text = f"Gemini today: {q.requests} of {q.rpd} free requests used."

    def _wire(self) -> None:
        job = self.job
        if job.running or job.lines:  # a run going on, or the last one: shown again
            # The last search's result card is for matches still waiting; once everything is
            # decided, "All caught up" says it and the card would only point at empty reviews.
            if not job.running and job.report is not None and self.numbers().matches_waiting:
                self.run_panel.set_visibility(True)
                self.status.text = outcome_text(job)
                self.bar.value = job.share
                self.stage.text = ""
                self.panel.tick()
            self.update()
        self.run_button.on_click(lambda: self.start(match=True))
        self.ingest_button.on_click(lambda: self.start(match=False))

    def schedule_match(self) -> None:
        """Matching starts by itself a moment after jobs are added (idea 5). The pause lets
        several files dropped together count as one start."""
        if self.auto_timer is not None:
            self.auto_timer.cancel()
        with self.page:
            self.auto_timer = ui.timer(1.2, self._auto_start, once=True)

    async def _auto_start(self) -> None:
        service = self.service
        if self.job.syncing:  # the start-up check ends first
            self.schedule_match()
            return
        if self.job.running:
            toast("Jobs saved. They are checked when the current search ends.", icon="info")
            return
        if not service.has_key():
            toast("Jobs saved. Add your Gemini key in Settings to start matching.", icon="info")
            return
        if not (service.contractor_count() or self.contractors_picked):
            toast("Jobs saved. Add your contractors to start matching.", icon="info")
            return
        n, self.batch_jobs = self.batch_jobs, 0
        hold, self.hold_match = self.hold_match, False
        since, self.batch_since = self.batch_since or datetime.now(UTC), None
        if n > 1 or hold or await run.io_bound(self._backlog, since) > 0:
            # Several jobs at once, a guessed PDF, or older jobs still waiting (a search would
            # send them all too): save, then ask before sending anything to Gemini.
            self.offer_after_save = True
            toast(f"Saving {plural(n, 'job')}…", icon="move_to_inbox", seconds=4)
            self.start(match=False)
            return
        toast("Matching started. You can keep using the app.", icon="auto_awesome", seconds=6)
        self.start(match=True)

    def offer_match(self, n: int) -> None:
        """ "Match N jobs now?" Matching runs in the background: the rest of the app stays usable
        and the header shows its progress."""
        if n <= 0 or self.job.running or not self.service.has_key():
            return
        if not self.service.contractor_count():
            return
        with self.page, ui.dialog() as dialog, ui.card().classes("gap-2").mark("match-offer"):
            ui.label(f"Match {plural(n, 'job')} now?").classes("text-h6")
            ui.label(
                "Gemini checks each job against your contractors, one request per job. It runs "
                "in the background and you can keep using the app. Or leave it for later: "
                "the jobs stay saved."
            ).classes("text-sm text-grey-8 max-w-md")

            def go() -> None:
                dialog.close()
                self.start(match=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Not now", on_click=dialog.close).props("flat no-caps").mark(
                    "match-offer-later"
                )
                ui.button(f"Match {plural(n, 'job')} now", icon="auto_awesome", on_click=go).props(
                    "unelevated no-caps color=primary"
                ).mark("match-offer-now")
        dialog.open()

    def _backlog(self, since: datetime) -> int:
        """Jobs stored before `since` that a search would also check (0 = only the new ones).
        New contractors are matched to every job, so then all older jobs count."""
        unmatched_only = bool(self.service.contractor_count()) and not self.contractors_picked
        return self.service.jobs_before(since, unmatched_only=unmatched_only)

    def _waiting_count(self) -> int:
        try:
            return len(self.service.jobs_waiting())
        except Exception:  # noqa: BLE001 (falls back to the screen's own count)
            return home_numbers(self.service).jobs_waiting

    def start(self, match: bool) -> None:
        if self.job.syncing:
            ui.notify("Still checking your folders. Try again in a moment.", type="info")
            return
        if match and not self.job.running and self.service.needs_key():
            # Find matches before a key: the key step opens, with one plain line (a search
            # would only stop with an error). Save without matching needs no key.
            ui.notify("Add your key first: Find matches needs it.", type="info")
            self.ask_key()
            return
        if not self.job.start(match):
            ui.notify("A search is already running. It shows here.", type="warning")
            return
        self.after.clear()
        self.problems.clear()
        self.log.clear()
        self.panel.clear()
        self.seen["lines"] = 0
        self.bar.value = 0
        self.bar.set_visibility(True)
        self.run_panel.set_visibility(True)
        self.refresh_state()  # the main action steps aside: the card above shows the run
        self.update()

    def ask(self, check: RunCheck) -> None:
        self.seen["asking"] = True
        with self.page, ui.dialog().props("persistent") as dialog, ui.card():
            ui.label("Use more of today's Gemini quota?").classes("text-h6")
            ui.label(check.message).classes("text-sm")
            if check.verdict == "exceeds":
                ui.label(
                    f"Yes sends the {plural(check.calls_that_fit, 'call')} that fit today; "
                    "the rest wait for the next search."
                ).classes("text-sm")

            def answer(yes: bool) -> None:
                self.job.answer(yes)
                dialog.close()
                self.seen["asking"] = False

            with ui.row():
                ui.button("Yes, go ahead", on_click=lambda: answer(True)).mark("quota-yes")
                ui.button("Not now", on_click=lambda: answer(False)).props("flat").mark("quota-no")
        dialog.open()

    def finished(self) -> None:
        """The run ended (seen once per run, even if it ended while on another tab)."""
        job = self.job
        self.run_button.enable()
        self.ingest_button.enable()
        self.run_row.set_visibility(True)
        self.bar.value = job.share
        self.show_quota()
        self.refresh_state()
        job.track.refresh_now()  # the last jobs to finish are listed too
        self.panel.tick()
        if job.error is not None:
            self.status.text = ""
            self.stage.text = ""
            self.bar.set_visibility(False)  # nothing is running: only the message and its button
            self.after.clear()
            with self.after:
                failure_card(
                    job.error,
                    lambda: self.start(match=job.match),
                    what="The search did not finish." if job.match else "Saving did not finish.",
                )
            return
        report = job.report
        if report is None:
            return
        # The picks are stored now: clear them from the screen.
        self.reset_contractors()
        self.reset_jobs()
        self.pending.refresh()
        for label in (self.picked, self.missing, self.skipped, self.same_name):
            label.set_visibility(False)
        self.contractors_picked = False
        self.opened = {"contractors": False, "jobs": False}
        self.added.clear()
        self.status.text = outcome_text(job)
        if job.track.active:
            self.stage.text = ""  # the plain summary says it; no "Screening jobs: 2 of 3"
        self.guide.refresh()
        self.refresh_state()
        if self.offer_after_save and report.ingest_only:
            self.offer_after_save = False
            self.offer_match(self._waiting_count())
        if not report.ingest_only:
            self.after.clear()
            with self.after:
                ui.button(
                    "See results", icon="arrow_forward", on_click=lambda: ui.navigate.to("/results")
                ).props("flat no-caps color=primary").mark("see-results")

    def update(self) -> None:
        job = self.job
        for line, bold in job.lines[self.seen["lines"] :]:
            self.log.push(line, bold)
        self.seen["lines"] = len(job.lines)
        if self.getting:
            self.latest_panel.tick(self.progress)
        syncing = job.syncing and not job.running
        self.checking.set_visibility(syncing and not self.getting)
        if syncing:
            self.run_button.disable()
            self.ingest_button.disable()
        elif self.was_syncing and not job.running:
            self.run_button.enable()
            self.ingest_button.enable()
        self.was_syncing = syncing
        if job.running:
            self.run_button.disable()
            self.ingest_button.disable()
            self.run_row.set_visibility(False)  # the card above says what is going on
            self.run_panel.set_visibility(True)
            self.bar.value = job.share
            self.stage.text = f"{job.stage} ({round(job.share * 100)}%)"
            self.status.text = job.working_text()
            self.panel.tick()
            if job.question is not None and not self.seen["asking"]:
                self.ask(job.question)
        elif job.finished != self.seen["finished"]:
            self.seen["finished"] = job.finished
            self.stage.text = f"{job.stage} ({round(job.share * 100)}%)" if job.stage else ""
            self.finished()

    async def _poll_done(self) -> None:
        """While matching: list each job as soon as Gemini's answer for it is saved."""
        track = self.job.track
        if self.job.running and self.job.match and track.active and await track.poll():
            self.panel.tick()

    # -- sync with the remembered folders when the app opens (phase 2) --

    async def _sync(self) -> None:
        service = self.service
        key = id(service)
        pending = hasattr(service, "sync_pending") and service.sync_pending()
        if (key in _SYNCED and not pending) or self.job.running or self.job.syncing:
            return  # (a check already going on does this work)
        _SYNCED[key] = None
        self.job.syncing = True  # Find matches, drops and auto-start wait until it ends
        linked = hasattr(service, "has_sync_link") and service.has_sync_link()
        try:
            if linked:
                self._getting(True)
                outcome = await run.io_bound(
                    partial(service.get_latest, adopt=pending, progress=self.progress)
                )
                summary = outcome.summary
            else:
                summary = await run.io_bound(service.sync_on_start)
        except Exception:  # noqa: BLE001 (never block the screen; details go to the log)
            logger.exception("sync_failed")
            return
        finally:
            self.job.syncing = False
            self._getting(False)
        _SYNCED[key] = summary
        try:
            # No "Match N jobs now?" pop-up here: the main button already says "Find matches
            # for N new jobs", right under the counts.
            await self.guide.refresh()  # first-run steps tick themselves
            self.refresh_state()
            if linked:
                self._latest_done(summary, asked=False)
        except Exception:  # noqa: BLE001 (the person already left this screen)
            return

    def _getting(self, on: bool) -> None:
        """The rows say "Getting latest..." (quietly) while the do good link is asked."""
        self.getting = on
        self._n = None  # the counts may have changed while the download ran
        with contextlib.suppress(Exception):  # the person already left this screen
            if on:
                self.progress.set("")
                self.latest_panel.tick(self.progress)
            self.latest_box.set_visibility(on)
            self._layout()
            if self.guide_shown:
                self.guide.refresh()  # its link line says "Getting latest…"

    async def refresh_folders(self) -> None:
        """ "Get latest" (a do good link is saved) or the small refresh: read the remembered
        folders again. Nothing is sent to Gemini; with a link, only the download is asked."""
        service = self.service
        if not hasattr(service, "sync_on_start"):
            return
        if self.job.running or self.job.syncing:
            toast("Still working. Try again in a moment.", icon="info", seconds=4)
            return
        linked = hasattr(service, "has_sync_link") and service.has_sync_link()
        if not linked and service.contractors_folder() is None and service.jobs_folder() is None:
            toast("No folder is remembered yet. Use Change… to choose one.", icon="info", seconds=5)
            return
        self.job.syncing = True
        try:
            if linked:
                self._getting(True)
                outcome = await run.io_bound(
                    partial(service.get_latest, adopt=True, progress=self.progress)
                )
                summary = outcome.summary
            else:
                summary = await run.io_bound(service.sync_on_start)
        except Exception:  # noqa: BLE001 (details go to the log)
            logger.exception("sync_failed")
            toast(
                "Could not check your folders. Details are in the app's log.",
                icon="error_outline",
            )
            return
        finally:
            self.job.syncing = False
            self._getting(False)
        if summary is None:  # another check was still going
            toast("Still working. Try again in a moment.", icon="info", seconds=4)
            return
        _SYNCED[id(service)] = summary
        await self.guide.refresh()  # waits: the rows depend on it
        self.refresh_state()
        if linked:
            self._latest_done(summary, asked=True)
            return
        news = self._news(summary)
        toast(
            "Checked your folders: " + (news or "nothing new") + ".",
            icon="sync",
            seconds=5,
        )

    @staticmethod
    def _news(summary: Any) -> str:
        """ "3 new people, 70 new jobs" (what the import stored; the same count the Jobs screen
        grows by)."""
        bits = []
        if summary.people_added:
            bits.append(plural(summary.people_added, "new person", "new people"))
        if summary.new_jobs:
            bits.append(plural(summary.new_jobs, "new job"))
        return ", ".join(bits)

    def _did(self, text: str) -> None:
        """One plain sentence for "What the app did" (never the link: it is masked)."""
        self.job.lines.append((mask_secrets(text), False))

    def _latest_done(self, summary: Any, *, asked: bool) -> None:
        """Get latest ended: ONE toast ("3 new people, 70 new jobs") with the button for what
        comes next, and one sentence in "What the app did". A quiet check at start says nothing
        when nothing is new; a click always answers."""
        calm = calm_line(self._latest())
        if calm:  # the calm line under the rows says it
            self._did(calm)
            return
        news = self._news(summary)
        if not news:
            self._did("Checked your do good link. Nothing new.")
            if asked:
                toast("Nothing new. You have the latest.", icon="sync", seconds=5)
            return
        self._did(f"Got your latest list: {news}.")
        steps = {
            "key": ("Add your key", self.ask_key),
            "find": ("Find matches", lambda: self.start(match=True)),
            "review": ("Review", lambda: ui.navigate.to("/review")),
        }
        label, action = steps.get(self.primary_kind(self.numbers()), (None, None))
        toast(news, label, action, icon="sync", seconds=12, marker="latest-toast")
