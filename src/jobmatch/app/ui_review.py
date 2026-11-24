"""Review mode ("/review"): the undecided matches one at a time, like triaging an inbox.

    one match, large and centred: job, person, score, five facts, the "why" behind Details
    Approve / Needs info / Reject (big, always in the same place) and a quiet Skip
    keys: 1 approve, 2 needs info, 3 reject, right arrow skip, Z undo, ? the shortcut sheet
    after each verdict: the next match at once, and a toast with Undo (and "Write the email")
    at the end: "All caught up" with a roundup of this session

The decisions are stored exactly as on Results (AppService.decide / clear_decision), so nothing
here is a second copy of the truth: leave midway and Results and Home show what is left. Only
the session roundup (what was approved, skipped…) is kept in memory while the app runs.
"""

from dataclasses import dataclass, field

from nicegui import app as nicegui_app
from nicegui import ui
from nicegui.events import KeyEventArguments

from jobmatch.app import ui_email
from jobmatch.app.service import AppService, ReviewItem
from jobmatch.app.ui import (
    DECISION_TEXT,
    EDGE_BY_FILL,
    PAGE,
    RUN_ERRORS,
    TEXT_DARK,
    _meets_table,
    _profile_dialog,
    ask_reject_reason,
    export_to_excel,
    job_title,
    pay_text,
    resume_button,
    score_shade,
    title_case,
)
from jobmatch.app.ui_help import dismiss_toast, plain_dates_in, plural, toast
from jobmatch.app.ui_progress import REVIEW_JOB_KEY
from jobmatch.schemas import Decision, ReasonCode, RemoteType

REVIEW_CSS = """
.dg-rv { width: 100%; max-width: 820px; margin: 0 auto; }
.dg-rv-card { border-radius: 1.75rem; padding: 26px 30px; animation: rv-in .28s ease both; }
@keyframes rv-in { from { opacity: 0; transform: translateY(10px); } }
.dg-rv-score { width: 92px; height: 92px; border-radius: 50%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; flex: 0 0 auto; line-height: 1; }
.dg-rv-score .n { font-size: 34px; font-weight: 800; letter-spacing: -.03em; }
.dg-rv-score .t { font-size: 12px; font-weight: 700; text-transform: uppercase; margin-top: 3px; }
.dg-rv-name { font-size: 2.1rem; font-weight: 800; letter-spacing: -.03em; color: #2A1F4D;
  line-height: 1.1; }
.dg-fact { display: flex; gap: 10px; align-items: flex-start; padding: 8px 12px;
  border-radius: 1rem; background: #FBFAFE; border: 1.5px solid #ECE7F7; min-width: 0; }
.dg-fact .k { font-size: 11px; font-weight: 700; text-transform: uppercase; color: #7A7396;
  letter-spacing: .04em; }
.dg-fact .v { font-size: 15px; font-weight: 600; color: #1E1A33; line-height: 1.25; }
.dg-fact .s { font-size: 12.5px; color: #6B6585; line-height: 1.25; }
.dg-act { min-width: 0; flex: 1 1 0; height: 64px; font-size: 18px !important;
  border-radius: 1.2rem !important; border-width: 2px !important; }
.dg-act .key { margin-left: 10px; font: 700 12px "Space Mono", monospace; padding: 1px 7px;
  border-radius: 6px; background: rgba(255,255,255,.65); border: 1px solid rgba(0,0,0,.18); }
.dg-bar .q-linear-progress__track, .dg-bar .q-linear-progress__model { border-radius: 8px; }
.dg-details { border-radius: 1rem; background: #FBFAFE; border: 1.5px solid #ECE7F7;
  padding: 2px 8px; }
.dg-details .q-item { border-radius: .75rem; font-weight: 600; color: #4B3499; }
.dg-grown { font-size: 12px; font-weight: 700; color: #4B3499; background: #E9DFFB;
  border-radius: 9999px; padding: 1px 10px; }
.dg-tile-end { flex: 1 1 0; min-width: 120px; border-radius: 1.25rem; padding: 14px 16px;
  text-align: center; }
.dg-tile-end .n { font-size: 34px; font-weight: 800; line-height: 1; }
.dg-tile-end .l { font-size: 13px; font-weight: 700; margin-top: 4px; }
"""

SHEET_ROWS = [
    ("1", "Approve"),
    ("2", "Needs info"),
    ("3", "Reject (asks why)"),
    ("→", "Skip for now"),
    ("Z", "Undo the last verdict"),
    ("?", "This sheet"),
]
TILE_STYLE = {
    "approved": ("#B7EBC4", "#2E9D5B", "Approved"),
    "needs_info": ("#FBE7A1", "#C99A12", "Needs info"),
    "rejected": ("#F4B6BD", "#C0392B", "Rejected"),
    "skipped": ("#ECE9F2", "#A79FBC", "Skipped"),
}


@dataclass
class Done:
    """An approved match of this session, kept so its email can be written at the end."""

    item: ReviewItem


@dataclass
class ReviewSession:
    """What happened since Review mode was opened (kept while the app runs). The decisions
    themselves are in reviews.csv."""

    decided: dict[str, Decision] = field(default_factory=dict)  # match_id -> verdict (in order)
    approved: dict[str, Done] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)  # ("decide" | "skip", match_id)
    pinned: str | None = None  # an undone match comes back first
    finished: bool = False  # the end screen was reached
    prefer_job: str | None = None  # the job to start with (a "Review" link on the progress card)
    seen_total: int | None = None  # the total last shown, to notice people who joined the queue
    grown: int = 0  # people who joined the queue during this session (a decision seated them)

    def count(self, decision: Decision) -> int:
        return sum(d is decision for d in self.decided.values())


_SESSIONS: dict[int, ReviewSession] = {}


def session_for(service: AppService) -> ReviewSession:
    return _SESSIONS.setdefault(id(service), ReviewSession())


def progress_note(service: AppService, left: int) -> str | None:
    """Home: "4 left to review" when a review is under way (some verdicts given, not finished)."""
    session = _SESSIONS.get(id(service))
    if session is None or session.finished or not session.decided or not left:
        return None
    return f"{left} left to review"


def score_chip(service: AppService, item: ReviewItem) -> None:
    m = item.view.match
    fit = m.verdict.value == "fit"
    fill = score_shade(service, m.fit_score, fit)
    edge = EDGE_BY_FILL.get(fill, "#2E9D5B")
    with (
        ui.element("div")
        .classes("dg-rv-score")
        .style(f"background-color: {fill}; border: 2.5px solid {edge}; color: {TEXT_DARK};")
        .mark("review-score")
    ):
        ui.label("" if m.fit_score is None else str(m.fit_score)).classes("n")
        ui.label("fit" if fit else "partial").classes("t")


def fact(icon: str, key: str, value: str, sub: str | None = None, *, wide: bool = False) -> None:
    with (
        ui.element("div")
        .classes("dg-fact" + (" sm:col-span-2" if wide else ""))
        .mark(f"fact:{key}")
    ):
        ui.icon(icon, size="22px").classes("text-primary mt-1")
        with ui.column().classes("gap-0 min-w-0"):
            ui.label(key).classes("k")
            ui.label(value).classes("v")
            if sub:
                ui.label(sub).classes("s")


def review_page(service: AppService, native: bool) -> None:
    ReviewPage(service, native).build()


class ReviewPage:
    def __init__(self, service: AppService, native: bool) -> None:
        self.service = service
        self.native = native
        session = session_for(service)
        if session.finished and service.review_queue():
            session = _SESSIONS[id(service)] = ReviewSession()  # new matches: a fresh session
        self.session = session
        prefer = nicegui_app.storage.client.pop(REVIEW_JOB_KEY, None)
        if prefer:
            session.prefer_job = str(prefer)
        self.item: ReviewItem | None = None
        self.busy = False

    # -- layout --

    def build(self) -> None:
        ui.add_css(REVIEW_CSS)
        with ui.column().classes(f"{PAGE} gap-3") as self.root:
            self.stage = ui.refreshable(self._stage)
            self.stage()
        ui.keyboard(on_key=self.key, ignore=["input", "select", "textarea"])

    # -- the queue --

    def _pick(self) -> tuple[ReviewItem | None, int, int]:
        """(the match to show, undecided matches left, left without the skipped ones)."""
        queue = self.service.review_queue()
        s = self.session
        if s.pinned:
            pinned = next((i for i in queue if i.view.match.match_id == s.pinned), None)
            s.pinned = None
            if pinned is not None:
                if pinned.view.match.match_id in s.skipped:
                    s.skipped.remove(pinned.view.match.match_id)
                return pinned, len(queue), len(queue) - len(s.skipped)
        fresh = [i for i in queue if i.view.match.match_id not in s.skipped]
        if s.prefer_job:
            mine = [i for i in fresh if i.job.job_id == s.prefer_job]
            if mine:
                return mine[0], len(queue), len(fresh)
            s.prefer_job = None  # that job is done: carry on in the usual order
        return (fresh[0] if fresh else None), len(queue), len(fresh)

    def _stage(self) -> None:
        item, left, fresh = self._pick()
        self.item = item
        s = self.session
        total = len(s.decided) + left
        if s.seen_total is not None and total > s.seen_total:
            s.grown += total - s.seen_total  # a decision seated someone new in the queue
        s.seen_total = total
        with ui.column().classes("dg-rv gap-4").mark("review-stage"):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                with ui.row().classes("items-center gap-3 no-wrap"):
                    ui.label("Review matches").classes("text-h5")
                    ui.button(icon="keyboard", on_click=self.show_keys).props(
                        'flat round dense color=grey-7 aria-label="Keyboard shortcuts"'
                    ).tooltip("Keyboard shortcuts (?)").mark("review-keys")
                ui.button("Back to Home", icon="home", on_click=lambda: ui.navigate.to("/")).props(
                    "flat no-caps color=grey-8"
                ).mark("review-home")
            if total:
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"{len(s.decided)} of {total} reviewed").classes(
                            "text-sm font-medium text-grey-8"
                        ).mark("review-progress")
                        if s.grown:
                            ui.label(f"+{plural(s.grown, 'new candidate')}").classes(
                                "dg-grown"
                            ).mark("review-grown").tooltip(
                                "A decision brought another person into the list."
                            )
                    ui.linear_progress(value=len(s.decided) / total, show_value=False).props(
                        "rounded size=8px color=primary"
                    ).classes("w-full dg-bar").mark("review-bar")
            if item is None:
                s.finished = True
                self._end(left)
            else:
                s.finished = False
                self._card(item)

    # -- one match --

    def _card(self, item: ReviewItem) -> None:
        job, view, m = item.job, item.view, item.view.match
        who = view.name or m.talent_id
        with ui.card().classes("dg-rv-card w-full gap-4").mark("review-card"):
            with ui.column().classes("gap-0 min-w-0"):
                job_title(job)
                where = " · ".join(p for p in (job.company_raw, job.location_raw) if p)
                if where:
                    ui.label(where).classes("text-sm text-grey-8")
                ui.label(f"Candidate {item.position} of {item.of} for this job").classes(
                    "text-xs text-grey-7"
                )
            with ui.row().classes("w-full items-center no-wrap gap-5"):
                score_chip(self.service, item)
                with ui.column().classes("gap-1 min-w-0"):
                    ui.label(who).classes("dg-rv-name").mark("review-name")
                    if view.headline:
                        ui.label(view.headline).classes("text-grey-8 text-base")
                    with ui.row().classes("gap-2 pt-1"):
                        resume_button(m.talent_id, view.name, view.has_resume, "review-resume")
                        ui.button(
                            "Profile",
                            icon="badge",
                            on_click=lambda: _profile_dialog(self.service, m.talent_id, view.name),
                        ).props("outline dense no-caps").classes("bg-white pl-1 pr-3")
            self._facts(item)
            with ui.row().classes("w-full no-wrap gap-3 pt-1").mark("review-actions"):
                self._action("Approve", "1", "#C8EED0", "#2E9D5B", "check", self.approve)
                self._action(
                    "Needs info", "2", "#FCEFCD", "#C99A12", "help_outline", self.needs_info
                )
                self._action("Reject", "3", "#F0BFC4", "#C0392B", "close", self.reject)
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("Skip for now", icon="arrow_forward", on_click=self.skip).props(
                    "flat no-caps dense color=grey-7"
                ).mark("review-skip")
                if self.session.history:
                    ui.button("Undo", icon="undo", on_click=self.undo).props(
                        "flat no-caps dense color=grey-7"
                    ).mark("review-undo")
            with (
                ui.expansion("Details: why this match", icon="notes")
                .props("dense")
                .classes("dg-details w-full text-sm")
                .mark("review-details")
            ):
                ui.label(m.reason or "No reason given.").classes("text-sm whitespace-pre-wrap")
                if m.requirements_met:
                    _meets_table(m.requirements_met)
                for title, items in (("Missing", m.requirements_missing), ("Flags", m.red_flags)):
                    if items:
                        ui.label(title).classes("font-bold")
                        for text in items:
                            ui.label(f"• {text}").classes("text-sm")
                if not m.detailed:
                    ui.label("Only the reason above is known for this person.").classes(
                        "text-grey-7 text-sm"
                    )

    def _facts(self, item: ReviewItem) -> None:
        job, m, f = item.job, item.view.match, item.facts
        mode = "" if job.remote_type is RemoteType.UNKNOWN else job.remote_type.value.title()
        job_place = " · ".join(p for p in (job.location_raw, mode) if p)
        pay = pay_text(job)
        missing, flags = len(m.requirements_missing), len(m.red_flags)
        req = f"{len(m.requirements_met)} met" + (f" · {missing} missing" if missing else "")
        req_sub = plural(flags, "flag") + " to check" if flags else None
        with ui.element("div").classes("w-full grid grid-cols-1 sm:grid-cols-2 gap-3"):
            fact(
                "place",
                "Where",
                f.location or "Not stated",
                f"Job: {job_place}" if job_place else None,
            )
            fact("workspace_premium", "Experience", f.experience or "Not stated", f.languages)
            fact(
                "event_available",
                "Availability",
                plain_dates_in(f.availability) if f.availability else "Not stated",
            )
            fact(
                "payments",
                "Rate",
                f.rate or "Not stated",
                f"Job pays {pay}" if pay else None,
            )
            fact(
                "fact_check",
                "Requirements",
                req if m.detailed else "Not detailed",
                req_sub,
                wide=True,
            )

    def _action(self, text: str, key: str, fill: str, edge: str, icon: str, handler) -> None:
        with (
            ui.button(on_click=handler, color=None)
            .props("unelevated no-caps")
            .classes("dg-act")
            .style(f"background-color: {fill}; color: {TEXT_DARK}; border: 2px solid {edge};")
            .mark(f"review-{text.lower().replace(' ', '-')}")
        ):
            ui.icon(icon, size="26px").classes("mr-2")
            ui.label(text)
            ui.label(key).classes("key")

    # -- verdicts --

    async def key(self, e: KeyEventArguments) -> None:
        if not e.action.keydown or e.action.repeat or self.busy:
            return
        if e.modifiers.ctrl or e.modifiers.meta or e.modifiers.alt:
            return
        name = e.key.name.lower()
        if name not in {"1", "2", "3", "arrowright", "z", "?", "/"}:
            return
        try:  # a pop-up is open (reject reason, email, résumé, help): the keys belong to it
            if await ui.run_javascript("document.querySelector('.q-dialog') !== null", timeout=2):
                return
        except Exception:  # noqa: BLE001 (no answer from the page: do nothing)
            return
        if name in ("?", "/"):
            self.show_keys()
        elif name == "z":
            self.undo()
        elif self.item is None:
            return
        elif name == "1":
            self.approve()
        elif name == "2":
            self.needs_info()
        elif name == "3":
            await self.reject()
        elif name == "arrowright":
            self.skip()

    def approve(self) -> None:
        self._decide(Decision.APPROVED)

    def needs_info(self) -> None:
        self._decide(Decision.NEEDS_INFO)

    async def reject(self) -> None:
        if self.item is None or self.busy:
            return
        self.busy = True
        try:
            picked = await ask_reject_reason()
        finally:
            self.busy = False
        if picked is not None:
            reason, note = picked
            self._decide(Decision.REJECTED, reason, note)

    def _decide(self, decision: Decision, reason: ReasonCode | None = None, note: str = "") -> None:
        item = self.item
        if item is None:
            return
        m = item.view.match
        try:
            self.service.decide(m.match_id, decision, reason, note)
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="negative")
            return
        s = self.session
        s.decided[m.match_id] = decision
        s.history.append(("decide", m.match_id))
        if decision is Decision.APPROVED:
            s.approved[m.match_id] = Done(item)
        who = item.view.name or m.talent_id
        message = f"{DECISION_TEXT[decision][0]}: {who}"
        self.stage.refresh()
        if decision is Decision.APPROVED:
            toast(
                message,
                "Undo",
                self.undo,
                extra="Write the email",
                on_extra=lambda: self.write_email(item),
                seconds=9,
                marker="undo-toast",
                parent=self.root,
                top=True,
            )
        else:
            toast(
                message, "Undo", self.undo, seconds=7, marker="undo-toast", parent=self.root,
                top=True,
            )  # fmt: skip

    def skip(self) -> None:
        if self.item is None:
            return
        match_id = self.item.view.match.match_id
        self.session.skipped.append(match_id)
        self.session.history.append(("skip", match_id))
        self.stage.refresh()

    def undo(self) -> None:
        s = self.session
        if not s.history:
            ui.notify("Nothing to undo.", type="info")
            return
        kind, match_id = s.history.pop()
        if kind == "decide":
            try:
                self.service.clear_decision(match_id)
            except RUN_ERRORS as exc:
                ui.notify(str(exc), type="negative")
                s.history.append((kind, match_id))
                return
            s.decided.pop(match_id, None)
            s.approved.pop(match_id, None)
        elif match_id in s.skipped:
            s.skipped.remove(match_id)
        s.pinned = match_id
        s.finished = False
        dismiss_toast()
        self.stage.refresh()

    def write_email(self, item: ReviewItem) -> None:
        with self.root:  # the toast that called this is already gone
            ui_email.email_dialog(
                self.service,
                item.view,
                item.job,
                others=[o for o in item.others if o.match.match_id != item.view.match.match_id],
            )

    def show_keys(self) -> None:
        with self.root, ui.dialog() as dialog, ui.card().classes("gap-2").mark("review-keys-sheet"):
            ui.label("Keyboard shortcuts").classes("text-h6")
            with ui.grid(columns="auto 1fr").classes("gap-x-4 gap-y-2 items-center"):
                for key, what in SHEET_ROWS:
                    ui.label(key).classes("dg-act key text-center").style(
                        "height: auto; flex: none; margin: 0; background: #F3EEFB;"
                    )
                    ui.label(what)
            ui.button("Close", on_click=dialog.close).props("flat no-caps").classes("self-end")
        dialog.on("hide", dialog.delete)
        dialog.open()

    # -- the end screen --

    def _end(self, left: int) -> None:
        s = self.session
        done = len(s.decided)
        skipped = list(s.skipped)
        with ui.card().classes("dg-rv-card w-full gap-4 items-center").mark("review-end"):
            ui.icon("task_alt", size="56px").classes("text-positive")
            if done or left:
                ui.label("All caught up").classes("text-h5").mark("review-caught-up")
            else:
                ui.label("Nothing to review right now").classes("text-h5").mark("review-caught-up")
                ui.label("New matches show up here after Find matches.").classes("text-grey-8")
            if left:
                ui.label(
                    f"{plural(left, 'match', 'matches')} skipped and still waiting for you."
                ).classes("text-grey-8")
            if done or skipped:
                with ui.row().classes("w-full gap-3 no-wrap").mark("review-roundup"):
                    counts = {
                        "approved": s.count(Decision.APPROVED),
                        "needs_info": s.count(Decision.NEEDS_INFO),
                        "rejected": s.count(Decision.REJECTED),
                        "skipped": left,
                    }
                    for key, (fill, edge, label) in TILE_STYLE.items():
                        with (
                            ui.element("div")
                            .classes("dg-tile-end")
                            .style(
                                f"background: {fill}; border: 2px solid {edge}; color: {TEXT_DARK};"
                            )
                            .mark(f"roundup-{key}")
                        ):
                            ui.label(str(counts[key])).classes("n")
                            ui.label(label).classes("l")
            # The buttons come before the list of approved people, so a long list never
            # pushes them out of sight.
            with ui.row().classes("w-full justify-center gap-3 pt-2"):
                if left:
                    ui.button(
                        f"Review the {plural(left, 'skipped match', 'skipped matches')}",
                        icon="skip_previous",
                        on_click=self.review_skipped,
                    ).props("unelevated no-caps color=primary").mark("review-skipped")
                ui.button(
                    "Export to Excel",
                    icon="download",
                    on_click=lambda: export_to_excel(self.service, self.native),
                ).props("outline no-caps").mark("review-export")
                ui.button("Back to Home", icon="home", on_click=lambda: ui.navigate.to("/")).props(
                    "unelevated no-caps color=primary" if not left else "outline no-caps"
                ).mark("review-back-home")
            if s.approved:
                with ui.column().classes("w-full gap-2").mark("review-approved-list"):
                    ui.label("Write emails for the people you approved").classes("font-bold")
                    for done_item in s.approved.values():
                        self._approved_row(done_item.item)

    def _approved_row(self, item: ReviewItem) -> None:
        who = item.view.name or item.view.match.talent_id
        with (
            ui.row()
            .classes("dg-attn items-center gap-3 w-full no-wrap")
            .mark(f"approved-row:{item.view.match.talent_id}")
        ):
            ui.icon("check_circle", size="22px").classes("text-positive")
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                ui.label(who).classes("font-bold")
                ui.label(title_case(item.job.title_norm or item.job.title_raw)).classes(
                    "text-xs text-grey-7"
                )
            ui.button(
                "Write the email",
                icon="mail_outline",
                on_click=lambda i=item: self.write_email(i),
            ).props("outline dense no-caps").classes("px-3").mark(
                f"email:{item.view.match.talent_id}"
            )

    def review_skipped(self) -> None:
        self.session.skipped.clear()
        self.session.finished = False
        self.stage.refresh()
