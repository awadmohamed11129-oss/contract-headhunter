"""The desktop app's screens (NiceGUI). All logic lives in app/service.py; this file only
lays out the screens and wires buttons to it.

Screens:
- "/"         Find matches: pick the contractor folder and a jobs file, run, watch progress.
- "/results"  One card per job: up to 3 fits, or the best partial to check, or no match;
              approve / reject / needs info on each; export to Excel; start a new search.
- "/jobs"     Every job A–Z, coloured by state (matched / no match / waiting / closed), with
              an Unavailable toggle, Reopen and Delete for closed jobs (a job is completed
              when an application is set to Hired).
- "/talent"   Every contractor, with the "Available for matching" toggle (the reviewer's
              call, saved when flipped), the jobs they were approved for, their
              profile (editable, with the reviewer's note) and their résumé (add or
              replace a PDF).
- "/settings" Gemini key (never shown back), reviewer name, data folder.

The run is blocking, so it goes to a worker thread (run.io_bound). Its progress lines reach
the screen through a queue read by a timer; its budget question comes back to the screen as
a dialog (run_coroutine_threadsafe), and the worker waits for the answer.
"""

import asyncio
import logging
import re
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse
from nicegui import app as nicegui_app
from nicegui import background_tasks, run, ui
from nicegui.events import (
    UploadEventArguments,
    ValueChangeEventArguments,
)

from jobmatch.app import ui_email
from jobmatch.app.service import (
    AppError,
    AppService,
    JobAction,
    JobOverview,
    JobResult,
    JobState,
    MatchView,
    TalentOverview,
)
from jobmatch.app.ui_help import (
    HELP_CSS,
    KEY_HELP,
    failure_card,
    help_icon,
    left_out_dialog,
    plain_dates_in,
    plain_day,
    plain_when,
    plural,
    toast,
    undo_toast,
)
from jobmatch.app.ui_progress import PROGRESS_CSS, RunTracker, busy_jobs, busy_text, notify_os
from jobmatch.app.ui_sync import link_card
from jobmatch.app_paths import APP_TITLE
from jobmatch.backup import BackupInfo, backup_name
from jobmatch.llm.matches import MEETS_SEP
from jobmatch.llm.usage import RunCheck
from jobmatch.pipeline import PipelineError, RunOnceReport
from jobmatch.schemas import (
    ApplicationStatus,
    Commitment,
    ContractorProfile,
    Decision,
    Job,
    JobAvailability,
    ReasonCode,
    RemoteType,
    Review,
    web_url_or_none,
)
from jobmatch.sources.contractor_upsert import ContractorFileError
from jobmatch.storage.csv_store import CsvStoreError
from jobmatch.storage.loader import StorageBackendUnavailable

# The org's theme (redesign): a deep purple page, header and primary buttons; every screen is
# a white rounded sheet holding soft-shadow cards. The decision colours (SHADE below:
# green / yellow / red, each with a darker outer edge) carry meaning and are not the theme.
THEME_PRIMARY = "#593B9D"
THEME_ACCENT = "#7E4891"
THEME_BACKGROUND = "linear-gradient(170deg, #593B9D 0%, #4F3590 55%, #5A3D9F 100%)"

FONT_LINK = (
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800'
    '&family=Space+Mono&display=swap" rel="stylesheet">'
)
# The infinity sign, drawn as one stroked path (it replaces the "oo" of "good").
INF_PATH = (
    "M18 8c-5.5 0-10 3.6-10 8s4.5 8 10 8c8 0 14-16 22-16 5.5 0 10 3.6 10 8s-4.5 8-10 8"
    "c-8 0-14-16-22-16z"
)
WORDMARK_HTML = (
    '<div class="brand"><div class="brand-row"><span>do g</span>'
    '<svg class="inf" viewBox="2 4 54 24" aria-hidden="true">'
    '<path class="bs" d="PATH" pathLength="100"/><path class="tr" d="PATH" pathLength="100"/>'
    '</svg><span>d</span></div><div class="brand-tag">a talent company</div></div>'
).replace("PATH", INF_PATH)
APP_CSS = (
    """
body { font-family: Inter, "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
  counter-reset: dgstep; }
.q-layout { position: relative; z-index: 1; }
.q-header { background: rgba(89,59,157,.94) !important; backdrop-filter: blur(8px);
  box-shadow: none; }
.orbs { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.orbs i { position: absolute; border-radius: 50%; border: 2px solid rgba(255,255,255,.2);
  background: rgba(150,80,170,.16); animation: drift 18s ease-in-out infinite alternate; }
.orbs i:nth-child(1) { width: 300px; height: 300px; right: 8%; top: 6%; }
.orbs i:nth-child(2) { width: 200px; height: 200px; left: 3%; bottom: 12%; animation-delay: -6s; }
.orbs i:nth-child(3) { width: 380px; height: 380px; right: -90px; bottom: -120px;
  animation-delay: -11s; }
@keyframes drift { to { transform: translate(18px, -24px); } }
.brand { line-height: 1; cursor: pointer; }
.brand-row { display: inline-flex; align-items: baseline; color: #fff; font-size: 34px;
  font-weight: 800; letter-spacing: -.03em; }
.inf { height: .6em; width: auto; margin: 0 .03em; overflow: visible; }
.inf path { fill: none; stroke: #fff; stroke-width: 5.5; stroke-linecap: round;
  stroke-linejoin: round; }
.inf .bs { opacity: .8; }
.inf .tr { stroke-dasharray: 16 84; animation: trace 3.6s linear infinite;
  filter: drop-shadow(0 0 3px #fff); }
@keyframes trace { from { stroke-dashoffset: 100; } to { stroke-dashoffset: 0; } }
.brand:hover .inf { animation: wobble .7s ease; }
@keyframes wobble { 30% { transform: rotate(-8deg) scale(1.12); }
  60% { transform: rotate(6deg) scale(1.06); } }
.brand-tag { color: rgba(255,255,255,.88); font: 12px "Space Mono", ui-monospace, monospace;
  letter-spacing: .06em; margin-top: 5px; }
.q-header .nav-btn { color: rgba(255,255,255,.82) !important; border-radius: 9999px !important;
  padding: 6px 16px; font-weight: 600; }
.q-header .nav-btn:hover { background: rgba(255,255,255,.12); color: #fff !important; }
.q-header .nav-btn.nav-active { background: rgba(255,255,255,.2); color: #fff !important;
  box-shadow: inset 0 -3px 0 #fff; }
/* "backwards", not "both": a finished animation would keep the sheet the reference for fixed
   elements inside it, and the bottom message of Review mode would sit on its buttons. */
.dg-sheet { border: 3px solid #DDD9F0; animation: rise .45s ease backwards; }
@keyframes rise { from { opacity: 0; transform: translateY(12px); } }
.q-card { border-radius: 1.5rem; border: 2px solid #E4DFF3;
  box-shadow: 0 6px 22px rgba(89,59,157,.10), 0 1px 3px rgba(89,59,157,.08); }
.text-h5 { color: #4B3499; font-weight: 800; font-size: 2rem; letter-spacing: -.03em;
  line-height: 1.1; }
.text-h6 { color: #1E1A33; font-weight: 700; }
.step-h { display: flex; align-items: center; gap: 14px; }
.step-h::before { counter-increment: dgstep; content: counter(dgstep); width: 36px; height: 36px;
  border-radius: 50%; background: #7E4891; color: #fff; display: inline-flex;
  align-items: center; justify-content: center; font-size: 17px; font-weight: 700;
  transition: transform .25s; }
.q-card:hover .step-h::before { transform: scale(1.12) rotate(-6deg); }
.q-btn:not(.q-btn--round) { border-radius: 1.1rem; font-weight: 600;
  transition: transform .15s, box-shadow .15s; }
.q-btn:not(.q-btn--round):hover { transform: translateY(-1px); }
.q-btn--outline:before { border-width: 1.5px; }
.q-btn.bg-primary { box-shadow: 0 4px 14px rgba(89,59,157,.35); }
.q-field--outlined .q-field__control { border-radius: 1rem; }
.q-expansion-item .q-item { border-radius: .75rem; }
.q-expansion-item .q-item:hover { background: #F6F2FC; }
.nicegui-log { border-radius: 1.25rem; border: 2px solid #E4DFF3; background: #FBFAFE; }
.dg-main-sm { padding: 6px 18px; border-radius: 1.1rem !important; }
.dg-clamp2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; }
.dg-compact .q-item { padding: 2px 4px; min-height: 0; }
.dg-compact .q-expansion-item__content { padding: 4px 4px 8px; }
.dg-row .q-item { padding: 4px 8px; min-height: 0; }
.dg-row .q-expansion-item__content { padding: 4px 8px 10px; }
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after { animation: none !important; transition: none !important; } }
"""
    + HELP_CSS
    + PROGRESS_CSS
)

# Highlights the current screen's nav button.
NAV_JS = """<script>
if (!window.__dgNav) {
  window.__dgNav = setInterval(() => {
    document.querySelectorAll('.nav-btn').forEach((b) =>
      b.classList.toggle('nav-active', b.getAttribute('data-path') ===
        (location.pathname === '/review' ? '/results' : location.pathname)));
  }, 150);
}
</script>"""

# Screen width follows the window: full width, capped at 1600 px so lines stay readable on
# very wide monitors. Settings is a short form: narrower. Every screen is a white sheet.
SHEET = "dg-sheet bg-white rounded-[36px] shadow-2xl p-4 sm:p-6 lg:p-10"
PAGE = f"w-full mx-auto max-w-[1600px] {SHEET}"
PAGE_NARROW = f"w-full mx-auto max-w-[900px] {SHEET}"

logger = logging.getLogger("jobmatch.app")

RUN_ERRORS = (
    AppError,
    PipelineError,
    ContractorFileError,
    CsvStoreError,
    StorageBackendUnavailable,
    OSError,
)

OUTCOME_TEXT = {
    "fits": ("Clear fits", "positive"),
    "check_partial": ("No clear fit: closest person, please check by hand", "warning"),
    "no_match": ("No match: nobody on your contractor list fits", "grey"),
    "not_judged": ("Not checked yet: click Find matches", "grey"),
}
REASON_TEXT = {
    ReasonCode.WRONG_SKILLS: "Wrong skills",
    ReasonCode.SENIORITY: "Seniority",
    ReasonCode.LOCATION: "Location",
    ReasonCode.LANGUAGE: "Language",
    ReasonCode.NOT_CONTRACT: "Not a contract",
    ReasonCode.DUPLICATE: "Duplicate",
    ReasonCode.EXPIRED: "Posting expired",
    ReasonCode.OTHER: "Other",
}
DECISION_TEXT = {
    Decision.APPROVED: ("Approved", "positive"),
    Decision.REJECTED: ("Rejected", "negative"),
    Decision.NEEDS_INFO: ("Needs info", "warning"),
}


def open_in_file_manager(path: Path) -> None:
    """Show a file or folder in Finder / Explorer (fixed arguments, no shell)."""
    target = path if path.exists() else path.parent
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(target)], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", f"/select,{target}"], check=False)
    else:
        subprocess.run(
            ["xdg-open", str(target.parent if target.is_file() else target)], check=False
        )


# ---- file picking: the OS dialog in the app, an upload box in the browser preview ----


NOTHING_PICKED = "Nothing picked yet"

# Browser preview: a folder picked with the browser's chooser. Keeps the contractor file at
# the top and the PDFs in resume/ (or resumes/), tells the server what was picked, then hands
# the kept files to the hidden upload box. File contents never pass through this script.
_FOLDER_JS = """(e) => {
  const all = [...e.target.files];
  const folder = all.length ? all[0].webkitRelativePath.split('/')[0] : '';
  let contractorFiles = 0;
  const keep = all.filter((f) => {
    const parts = f.webkitRelativePath.split('/');
    const name = parts[parts.length - 1].toLowerCase();
    if (name.startsWith('.') || name.startsWith('~$')) return false;
    if (parts.length === 2 && (name.endsWith('.xlsx') || name.endsWith('.csv'))) {
      contractorFiles += 1;
      return true;
    }
    return parts.length === 3 && ['resume', 'resumes'].includes(parts[1].toLowerCase())
      && name.endsWith('.pdf');
  });
  emit({folder: folder, files: keep.length, contractor_files: contractorFiles});
  if (contractorFiles === 1) getElement(UPLOAD_ID).$refs.qRef.addFiles(keep);
  e.target.value = '';
}"""


def pick_row(label: str, icon: str, marker: str) -> tuple[ui.button, ui.label]:
    """The standard picker (user request): an icon button, then the picked path beside it."""
    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        button = (
            ui.button(label, icon=icon)
            .props("outline no-caps")
            .classes("bg-white shrink-0")
            .mark(marker)
        )
        note = (
            ui.label(NOTHING_PICKED)
            .classes("text-sm text-grey-7 truncate min-w-0")
            .mark(f"{marker}-path")
        )
    return button, note


def file_picker(
    native: bool,
    suffixes: tuple[str, ...],
    label: str,
    on_file: Callable[[str, bytes, Path | None], Awaitable[None] | None],
    *,
    multiple: bool = False,
    button: str = "Choose files…",
    icon: str = "upload_file",
    marker: str = "file-picker",
) -> Callable[[], None]:
    """The standard picker row for files: the OS dialog in the app; in the browser preview
    the same button opens the browser's file chooser (a hidden upload box), and the note
    shows file names (a browser never reveals paths). on_file is called once per file, in
    order. Returns a function that clears the note (after a run)."""
    chooser, note = pick_row(button, icon, marker)
    names: list[str] = []

    def reset() -> None:
        names.clear()
        note.text = NOTHING_PICKED

    async def handle(name: str, data: bytes, path: Path | None) -> None:
        result = on_file(name, data, path)
        if asyncio.iscoroutine(result):
            await result
        names.append(str(path) if path else name)
        note.text = ", ".join(names)
        note.tooltip(note.text)

    if native:

        async def browse() -> None:
            window = nicegui_app.native.main_window
            if window is None:
                ui.notify("The file dialog is not available.", type="negative")
                return
            patterns = ";".join(f"*{s}" for s in suffixes)
            picked = await window.create_file_dialog(
                allow_multiple=multiple, file_types=(f"{label} ({patterns})",)
            )
            for chosen in picked or ():
                path = Path(chosen)
                await handle(path.name, path.read_bytes(), path)

        chooser.on_click(browse)
    else:

        async def uploaded(e: UploadEventArguments) -> None:
            await handle(e.file.name, await e.file.read(), None)

        upload = (
            ui.upload(on_upload=uploaded, auto_upload=True, multiple=multiple)
            .props(f'accept="{",".join(suffixes)}"')
            .classes("hidden")
            .mark(f"{marker}-upload")
        )
        chooser.on_click(lambda: upload.run_method("pickFiles"))
    return reset


# ---- "Add a job by hand" (user decisions 2026-11-10) ----

# (field, label, hint, kind): kind "line", "date" or "list" (one item per line).
JOB_FORM_FIELDS = [
    ("url", "Job posting link",
     "The address of the posting. Used to recognise the same job if it comes in again.", "line"),
    ("job_title", "Job title", "As written in the posting, e.g. Data Analyst (6-month contract).",
     "line"),
    ("company", "Company", "The hiring company, or the agency if that's all the posting names.",
     "line"),
    ("contact_person", "Contact person", "The HR or hiring contact's name, if the posting gives "
     "one.", "line"),
    ("contact_email", "Contact email", "Where to reach them, e.g. jordan.lee@example.ca.", "line"),
    ("location", "Location", "City and province, e.g. Toronto, ON.", "line"),
    ("work_mode", "Work mode", "Where the work happens, as the posting says.", "work_mode"),
    ("hours_per_week", "Hours per week",
     "A number, e.g. 40 or 37.5. {ft} or more shows as FT, fewer as PT.", "hours"),
    ("pay", "Pay", "Canadian dollars: a number, or a range (the lower end is kept), e.g. 90 or "
     "85–95.", "line"),
    ("pay_type", "Pay type", "Hourly rate, or yearly salary.", "pay_type"),
    ("posted_date", "Posted date", "When the job was posted. Leave empty if unknown.", "date"),
    ("responsibility", "Responsibilities", "One per line. What the person will do.", "list"),
    ("qualification", "Qualifications",
     "One per line. Required skills, experience, languages.", "list"),
]  # fmt: skip


WORK_MODE_CHOICES = {"": "Not stated", "on-site": "On-site", "hybrid": "Hybrid", "remote": "Remote"}
PAY_TYPE_CHOICES = {"hourly": "Hourly", "salary": "Salary (per year)"}
FORM_DEFAULTS = {"work_mode": "", "pay_type": "hourly"}


def job_form(service: AppService, on_saved: Callable[[bool], None]) -> None:
    """One job typed or pasted by the reviewer. Saved as given (only cleaned of formatting);
    the next run stores it. `on_saved(again)`: again is True for "Save and add another"."""
    inputs: dict[str, ui.input | ui.textarea | ui.select] = {}
    with (
        ui.dialog() as dialog,
        ui.card().classes("job-form").style("width: 760px; max-width: 95vw"),
    ):
        with ui.row().classes("items-center gap-1"):
            ui.label("Add a job by hand").classes("text-h6")
            help_icon(
                "Paste or type the details. Formatting from the posting (bullets, bold, extra "
                "spaces and empty lines) is removed. Fields marked * are required."
            )
        ui.label("Fields marked * are required.").classes("text-sm text-grey-8")
        with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1"):
            full_time = service.settings.normalize.full_time_hours_per_week
            for name, label, hint, kind in JOB_FORM_FIELDS:
                hint = hint.replace("{ft}", f"{full_time:g}")  # noqa: PLW2901
                if kind == "list":
                    field = ui.textarea(label).props(f'outlined autogrow hint="{hint}"')
                    field.classes("col-span-2")
                elif kind in ("work_mode", "pay_type"):
                    choices = WORK_MODE_CHOICES if kind == "work_mode" else PAY_TYPE_CHOICES
                    field = ui.select(choices, label=label, value=FORM_DEFAULTS[name]).props(
                        f'outlined dense hint="{hint}"'
                    )
                elif kind == "hours":
                    field = ui.input(label).props(
                        f'outlined dense type=number min=1 max=80 step=0.5 hint="{hint}"'
                    )
                else:
                    field = ui.input(label).props(f'outlined dense hint="{hint}"')
                    if kind == "date":
                        field.props("type=date stack-label")
                    if name in REQUIRED_JOB_FIELDS:
                        field.classes("col-span-2 required")
                inputs[name] = field.mark(f"job-field:{name}")

        def save(again: bool) -> None:
            try:
                entry = service.add_job_entry({k: str(f.value or "") for k, f in inputs.items()})
            except AppError as exc:
                ui.notify(str(exc), type="warning", multi_line=True)
                return
            ui.notify(f"Saved {entry.job_title}.", type="positive")
            on_saved(again)
            if again:
                for key, f in inputs.items():
                    f.value = FORM_DEFAULTS.get(key, "")
            else:
                dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Save and add another", on_click=lambda: save(True)).props(
                "outline no-caps"
            ).mark("job-save-another")
            ui.button("Save", icon="save", on_click=lambda: save(False)).props("no-caps").mark(
                "job-save"
            )
    dialog.open()


# ---- screen: find matches ----


# The form's hints (user request 2026-11-10): flush with the box's left edge, right under it.
# A required field's hint starts with a red "*" (outside the box, not in its label).
JOB_FORM_CSS = (
    ".job-form .q-field__bottom { padding: 2px 0 0 1px; }"
    ".job-form .q-field--with-bottom { padding-bottom: 18px; }"
    ".job-form .required .q-field__messages > div::before"
    " { content: '* '; color: var(--q-negative); font-weight: 700; }"
    ".job-form .required-mark { color: var(--q-negative); font-weight: 700; }"
)
REQUIRED_JOB_FIELDS = ("url", "job_title")


def review_page(service: AppService, native: bool) -> None:
    """Review mode lives in ui_review.py (it reuses the Results pieces from this file)."""
    from jobmatch.app.ui_review import review_page as build  # noqa: PLC0415

    build(service, native)


def home_page(service: AppService, native: bool) -> None:
    """The Home screen lives in ui_home.py (it needs the pickers and RunJob from this file)."""
    from jobmatch.app.ui_home import home_page as build  # noqa: PLC0415

    build(service, native)


def result_line(report: RunOnceReport) -> str:
    """The progress box's last line after Find matches, shown in bold (user request
    2026-11-18), e.g. "Successful: 3 matched, 1 no matches."."""
    parts = [f"{report.jobs_matched} matched", f"{report.jobs_no_match} no matches"]
    if report.jobs_not_judged:
        parts.append(f"{report.jobs_not_judged} not checked yet")
    head = "Stopped early" if report.stopped else "Successful"
    return f"{head}: {', '.join(parts)}."


def run_summary(report: RunOnceReport) -> str:
    if report.ingest_only:
        return _ingested_text(report)
    return (
        f"Done: {plural(report.jobs_matched, 'job')} with suggestions, {report.jobs_no_match} "
        f"with no match, {report.jobs_not_judged} not checked yet."
        + (f" {report.stopped}." if report.stopped else "")
    )


class RunJob:
    """One Ingest or Find matches run, kept outside the screens so that changing tab never
    stops it (user request 2026-11-11). The worker thread writes progress, lines and the
    budget question here; whichever screen is open reads them on a timer. One per app."""

    def __init__(self, service: AppService) -> None:
        self.service = service
        self.running = False
        self.syncing = False  # the start-up check of the remembered folders is going on
        self.match = True
        # The progress box: plain sentences, one per line, and whether each is bold. The
        # technical lines go to the app's log (user request 2026-11-18).
        self.lines: list[tuple[str, bool]] = []
        self.share = 0.0
        self.stage = ""
        self.report: RunOnceReport | None = None
        self.error: str | None = None
        self.finished = 0  # counts finished runs, so a screen sees each ending once
        self.question: RunCheck | None = None  # the budget question waiting for an answer
        self._answered = threading.Event()
        self._answer = False
        self.track = RunTracker(service)  # "Job 2 of 5", time left, finished jobs (ui_progress)

    def working_text(self) -> str:
        if self.question is not None:
            return "Waiting for your answer about today's Gemini limit."
        return (
            "Matching… this can take a few minutes. You can use the other tabs meanwhile."
            if self.match
            else "Saving your contractors and jobs…"
        )

    def start(self, match: bool) -> bool:
        if self.running or self.syncing:
            return False
        self.running, self.match = True, match
        self.lines, self.share, self.stage = [], 0.0, "Starting"
        self.report, self.error, self.question = None, None, None
        try:
            waiting = self.service.matches_waiting() if match else 0
        except Exception:  # noqa: BLE001 (only used to say how many matches are new)
            logger.exception("matches_waiting_failed")
            waiting = 0
        self.track.reset(waiting)
        background_tasks.create(self._work(match), name="find-matches")
        return True

    async def _work(self, match: bool) -> None:
        try:
            self.report = await run.io_bound(
                self.service.run,
                echo=_log_run_line,
                confirm=self._confirm,
                progress=self._progress,
                match=match,
                say=self._say,
            )
            if match:
                self.lines.append((result_line(self.report), True))
        except RUN_ERRORS as exc:
            self.error = str(exc)
        except Exception:  # noqa: BLE001 (shown in plain words; details go to the log)
            logger.exception("run_failed")
            self.error = "Something unexpected went wrong. Details are in the app's log."
        finally:
            if self.error is not None:
                self._say(f"Stopped: {self.error.rstrip('.')}.")
            self.question = None
            self.running = False
            self.finished += 1

    def _say(self, line: str) -> None:  # worker thread
        self.lines.append((line, False))

    def _progress(self, share: float, stage: str) -> None:  # worker thread
        self.share, self.stage = share, stage
        self.track.on_progress(share, stage)

    def _confirm(self, check: RunCheck) -> bool:  # worker thread: waits for the reviewer
        self._answered.clear()
        self.question = check
        self._answered.wait()
        self.question = None
        return self._answer

    def answer(self, yes: bool) -> None:
        self._answer = yes
        self._answered.set()


def _log_run_line(line: str) -> None:
    """A technical run line (models, budget, tokens per call): the app's log, not the box."""
    logger.info("run_line %s", line.strip())


_RUN_JOBS: dict[int, RunJob] = {}


def run_job(service: AppService) -> RunJob:
    """The app's run (one per service)."""
    return _RUN_JOBS.setdefault(id(service), RunJob(service))


def run_indicator(service: AppService, native: bool = False) -> None:
    """In the header on every tab: a small "Matching 2 of 5" pill while a run goes on (it
    takes you back to it), and, when a run ends, a message with a Review button."""
    job = run_job(service)
    chip = (
        ui.button(on_click=lambda: ui.navigate.to("/"))
        .props("flat dense no-caps color=white icon=autorenew")
        .classes("dg-pill dg-spin")
        .mark("run-indicator")
    )

    seen = {"finished": job.finished}

    def ended() -> None:
        if job.error is not None or job.report is None or job.report.ingest_only:
            return
        try:
            new = max(0, service.matches_waiting() - job.track.waiting_before)
        except Exception:  # noqa: BLE001 (the message still says it ended)
            logger.exception("matches_waiting_failed")
            new = 0
        busy = busy_jobs(job.report)
        left = job.report.jobs_not_judged
        if new:
            text = f"Matching finished: {plural(new, 'new match', 'new matches')}"
            if busy:  # some jobs still wait: say why, plainly
                text = f"{text}. {busy_text(busy)}"
            toast(
                text, "Review", lambda: ui.navigate.to("/review"), seconds=20 if busy else 15,
                icon="auto_awesome", marker="run-toast",
            )  # fmt: skip
        else:
            if busy:  # Google was busy: never "nothing new"
                text = f"Matching finished. {busy_text(busy)}"
            elif left:  # another trouble: jobs not checked, so never "nothing new"
                text = f"Matching finished: {plural(left, 'job')} not checked yet"
            elif job.report.stopped:
                text = "Matching stopped early"
            else:
                text = "Matching finished: nothing new to review"
            toast(
                text if text.endswith(".") else f"{text}.", "See results",
                lambda: ui.navigate.to("/results"), seconds=20 if busy else 12,
                icon="auto_awesome", marker="run-toast",
            )  # fmt: skip
        if native:
            notify_os("do good", text)

    def update() -> None:
        chip.set_visibility(job.running)
        if job.finished != seen["finished"]:  # a run ended, on whichever tab is open
            seen["finished"] = job.finished
            ended()
        if job.running:
            what = "Matching" if job.match else "Saving"
            if job.question is not None:
                chip.text = "Answer needed on Find matches"
            elif job.match and job.track.active:
                chip.text = job.track.pill()
            else:
                chip.text = f"{what}… {round(job.share * 100)}%"

    update()
    ui.timer(0.5, update)


def _ingested_text(report: RunOnceReport) -> str:
    parts = []
    if report.contractors is not None:
        c = report.contractors
        parts.append(f"{plural(len(c.added), 'contractor')} added, {len(c.updated)} updated")
    if report.resumes is not None:
        r = report.resumes
        parts.append(f"{plural(r.added + r.replaced, 'résumé')} saved")
    new_jobs = sum(i.count("new") + i.count("needs_details") for i in report.ingest)
    parts.append(f"{plural(new_jobs, 'job')} added")
    dropped = sum(i.count("invalid") for i in report.ingest)
    if dropped:
        parts.append(f"{plural(dropped, 'row')} skipped (see the log)")
    return "Saved: " + " · ".join(parts) + ". Nothing was sent to Gemini."


# ---- screen: results ----

# Soft fills with a darker outer edge of the same colour (Quasar positive / warning /
# negative family), so colour codes stay readable behind dark text.
SHADE = {"green": "#B7EBC4", "yellow": "#FBE7A1", "red": "#F4B6BD"}
SHADE_EDGE = {"green": "#2E9D5B", "yellow": "#C99A12", "red": "#C0392B"}  # the darker outer edge


def shade_style(shade: str) -> str:
    """Soft fill with a darker outer edge of the same colour."""
    return f"background-color: {SHADE[shade]}; border: 1.5px solid {SHADE_EDGE[shade]};"


# Two steps lighter (about 75% toward white), for the Approve / Reject / Needs info buttons.
SHADE_LIGHT = {"green": "#C8EED0", "yellow": "#FCEFCD", "red": "#F0BFC4"}
TEXT_DARK = "#1D1D1D"
# Verdict chip by fit_score (bands in settings.yaml app.score_bands, user decision
# 2026-11-08): darker green, the green, the yellow, then the light yellow.
SCORE_SHADE = {
    "strong": "#5BBE77",
    "good": SHADE["green"],
    "some": SHADE["yellow"],
    "low": SHADE_LIGHT["yellow"],
}
EDGE_BY_FILL = {
    SCORE_SHADE["strong"]: SHADE_EDGE["green"],
    SCORE_SHADE["good"]: SHADE_EDGE["green"],
    SCORE_SHADE["some"]: SHADE_EDGE["yellow"],
    SCORE_SHADE["low"]: SHADE_EDGE["yellow"],
}
OUTCOME_SHADE = {"fits": "green", "check_partial": "yellow"}  # no match / not judged: none
DECISION_SHADE = {
    Decision.APPROVED: "green",
    Decision.REJECTED: "red",
    Decision.NEEDS_INFO: "yellow",
}
_MINOR_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with",
    "au", "aux", "de", "des", "du", "en", "et", "la", "le", "les", "ou", "pour", "sur",
}  # fmt: skip
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)


def title_case(text: str) -> str:
    """Title Case for display only: "senior data analyst (contract)" -> "Senior Data Analyst
    (Contract)". Words that already hold a capital (UX, SQL, iOS, McKinsey) are kept as they
    are; small words (and, of, de, la…) stay lowercase except first."""
    first = True

    def fix(m: re.Match[str]) -> str:
        nonlocal first
        word = m.group(0)
        is_first, first = first, False
        if word != word.lower():
            return word
        if not is_first and word in _MINOR_WORDS:
            return word
        return word[0].upper() + word[1:]

    return _WORD.sub(fix, text)


def _shade_button(text: str, shade: str, on_click: Callable, icon: str | None = None) -> ui.button:
    return (
        ui.button(text, icon=icon, on_click=on_click, color=None)
        .props("unelevated no-caps dense")
        .classes("px-3")
        .style(
            f"background-color: {SHADE_LIGHT[shade]}; color: {TEXT_DARK}; "
            f"border: 1.5px solid {SHADE_EDGE[shade]};"
        )
    )


# Profile fields edited as several lines (one item per line) or a long text.
_LONG_TEXT = {"executive_summary"}


FIELD_LABELS = {
    "talent_id": "ID",
    "talent_name": "Name",
    "location": "Location",
    "standardized_headline": "Headline",
    "executive_summary": "Summary",
    "core_strengths": "Core strengths",
    "proof_points": "Proof points",
    "main_industry": "Industries",
    "search_keywords": "Search keywords",
    "seniority": "Seniority",
    "weekly_hours": "Hours per week",
    "rate_expectation": "Rate expected (per hour)",
    "target_titles": "Job titles they want",
    "contract": "Open to contract work",
    "primary_profession": "Main profession",
    "secondary_professions": "Other professions",
    "years_experience": "Years of experience",
    "languages": "Languages",
    "availability": "Availability",
    "profile_updated": "Profile last updated",
}


def field_label(column: str) -> str:
    """The Profile pop-up's name for a stored column (display only; the column names stay)."""
    return FIELD_LABELS.get(column) or column.replace("_", " ").capitalize()


def _field_kind(column: str) -> str:
    """How the Profile pop-up edits a column: "list", "bool", "number" or "text"."""
    annotation = ContractorProfile.model_fields[column].annotation
    text = str(annotation)
    if "list" in text:
        return "list"
    if annotation is bool:
        return "bool"
    if "float" in text or "int" in text:
        return "number"
    return "text"


def _profile_dialog(
    service: AppService,
    talent_id: str,
    name: str | None,
    *,
    editable: bool = False,
    note: str | None = None,
    on_saved: Callable[[], None] | None = None,
) -> None:
    """The contractor's stored profile. On the Talent screen (editable, user decisions
    2026-11-18): Edit turns the fields into inputs, the Note can be written, and Save
    stores both (service.save_profile). Read-only elsewhere (Results)."""
    try:
        fields = service.contractor_fields(talent_id)
    except AppError as exc:
        ui.notify(str(exc), type="warning")
        return
    state = {"editing": False}
    inputs: dict[str, ui.element] = {}

    with (
        ui.dialog() as dialog,
        ui.card().style("width: 90vw; max-width: 90vw; max-height: 85vh"),
    ):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label(f"Profile: {name or talent_id}").classes("text-h6")
            with ui.row().classes("items-center gap-2 no-wrap"):
                if editable:
                    edit_button = (
                        ui.button("Edit", icon="edit", on_click=lambda: start_editing())
                        .props("outline dense no-caps")
                        .classes("bg-white pl-1 pr-3")
                        .mark("profile-edit")
                    )
                    save_button = (
                        ui.button("Save", icon="save", on_click=lambda: save())
                        .props("dense no-caps color=primary")
                        .classes("pl-1 pr-3")
                        .mark("profile-save")
                    )
                    save_button.set_visibility(False)  # a plain read view until Edit is pressed
                ui.button(icon="close", on_click=dialog.close).props(
                    'flat round dense aria-label="Close"'
                ).tooltip("Close")
        hint = ui.label("From the contractor list.").classes("text-xs text-grey-7")
        if editable:
            if note:  # the view shows a saved note as text; Edit turns it into the box below
                note_text = ui.label(f"Note: {note}").classes("text-sm whitespace-pre-wrap")
                note_text.mark("profile-note-view")
            note_box = (
                ui.textarea("Note", value=note or "")
                .props("outlined stack-label autogrow bg-color=white")
                .classes("w-full")
                .mark("profile-note")
            )
            note_box.set_visibility(False)

        @ui.refreshable
        def grid() -> None:
            with ui.grid(columns="minmax(10rem, auto) 1fr").classes("w-full gap-x-4 gap-y-1"):
                ui.label("Field").classes("font-bold border-b")
                ui.label("Value").classes("font-bold border-b")
                for column, values in fields:
                    ui.label(field_label(column)).classes(
                        "text-sm font-medium text-grey-9 border-b py-1"
                    ).mark(f"profile-label:{column}")
                    with ui.column().classes("gap-0 border-b py-1"):
                        if state["editing"] and column != "talent_id":
                            inputs[column] = _field_input(column, values)
                            continue
                        if not values:
                            ui.label("—").classes("text-grey-6")
                        for value in values:
                            ui.label(value).classes("text-sm whitespace-pre-wrap")

        with ui.scroll_area().classes("w-full h-[60vh]"):
            grid()

    def start_editing() -> None:
        state["editing"] = True
        edit_button.disable()
        save_button.set_visibility(True)
        note_box.set_visibility(True)
        if note:
            note_text.set_visibility(False)
        hint.text = (
            "Editing. Lists take one item per line. Save checks every field; a later "
            "contractor import with other values for this contractor replaces the edit."
        )
        grid.refresh()

    def save() -> None:
        values = {c: _field_value(c, e) for c, e in inputs.items()} if state["editing"] else {}
        try:
            saved = service.save_profile(talent_id, values, note_box.value)
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="warning", multi_line=True)
            return
        if not (saved.profile_changed or saved.note_changed):
            ui.notify("Nothing changed.")
        else:
            ui.notify(
                "Saved. They will be matched again on the next Find matches run."
                if saved.rescan
                else "Saved.",
                type="positive",
            )
        dialog.close()
        if on_saved:
            on_saved()

    dialog.open()


def _field_input(column: str, values: list[str]) -> ui.element:
    """One editable profile field (Profile pop-up)."""
    kind = _field_kind(column)
    mark = f"profile-field:{column}"
    if kind == "bool":
        return ui.switch(value=(values or [""])[0].lower() in ("true", "1", "yes")).mark(mark)
    if kind == "number":
        number = float(values[0]) if values else None
        return ui.number(value=number, min=0).props("dense outlined").classes("w-40").mark(mark)
    if kind == "list" or column in _LONG_TEXT:
        return (
            ui.textarea(value="\n".join(values))
            .props("dense outlined autogrow")
            .classes("w-full")
            .mark(mark)
        )
    return ui.input(value=(values or [""])[0]).props("dense outlined").classes("w-full").mark(mark)


def _field_value(column: str, element: ui.element) -> object:
    """What an edited profile field holds, for ContractorProfile."""
    kind = _field_kind(column)
    value = getattr(element, "value", None)
    if kind == "bool":
        return bool(value)
    if kind == "number":
        return None if value in (None, "") else value
    text = str(value or "")
    if kind == "list":
        return [line.strip() for line in text.splitlines() if line.strip()]
    return text.strip() or None


RESUME_ROUTE = "/resume/{talent_id}"
_resume_service: dict[str, AppService] = {}  # the service the résumé route reads from


def _serve_resumes(service: AppService) -> None:
    """GET /resume/<talent_id>: the stored PDF, shown inline. Only files of contractors in
    the list (looked up by ID, never a path from the URL); registered once per process."""
    _resume_service["service"] = service
    if any(getattr(r, "path", None) == RESUME_ROUTE for r in nicegui_app.routes):
        return

    @nicegui_app.get(RESUME_ROUTE)
    def resume(talent_id: str) -> FileResponse:
        path = _resume_service["service"].resume_path(talent_id)
        if path is None:
            raise HTTPException(status_code=404)
        return FileResponse(
            path,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


def pdf_chooser(
    native: bool, on_pdf: Callable[[bytes], Awaitable[None] | None], marker: str
) -> Callable[[], Awaitable[None]]:
    """Opens a chooser for one PDF: the OS dialog in the app, the browser's file chooser
    (a hidden upload box, made here) in the browser preview. on_pdf gets the file's bytes;
    its name is never kept (it may hold the person's name)."""

    async def deliver(data: bytes) -> None:
        result = on_pdf(data)
        if asyncio.iscoroutine(result):
            await result

    if native:

        async def browse() -> None:
            window = nicegui_app.native.main_window
            if window is None:
                ui.notify("The file dialog is not available.", type="negative")
                return
            picked = await window.create_file_dialog(file_types=("PDF résumé (*.pdf)",))
            if picked:
                await deliver(Path(picked[0]).read_bytes())

        return browse

    async def uploaded(e: UploadEventArguments) -> None:
        data = await e.file.read()
        upload.reset()  # the same file can be picked again
        await deliver(data)

    upload = (
        ui.upload(on_upload=uploaded, auto_upload=True)
        .props('accept=".pdf"')
        .classes("hidden")
        .mark(f"{marker}-upload")
    )

    async def pick() -> None:
        upload.run_method("pickFiles")

    return pick


def resume_button(
    talent_id: str,
    name: str | None,
    has_resume: bool,
    marker: str,
    *,
    service: AppService | None = None,
    native: bool = False,
    on_change: Callable[[], None] | None = None,
) -> None:
    """The contractor's stored résumé (Talent and Results). Always shown, grey when there is
    no résumé on file (user request). With `service` (Talent screen, user request
    2026-11-18): the grey button picks a PDF and stores it, and the viewer can replace the
    résumé. Without it (Results) a grey button is disabled. The tooltip sits on a wrapper:
    a disabled button gets no hover events."""
    editable = service is not None

    async def add(data: bytes) -> None:
        assert service is not None
        try:
            service.save_resume(talent_id, data)
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="warning")
            return
        ui.notify("Résumé added.", type="positive")
        if on_change:
            on_change()

    def click() -> Awaitable[None] | None:
        # Sync: the viewer dialog must be made in the click's own context.
        if has_resume:
            _resume_dialog(talent_id, name, service=service, native=native)
            return None
        return choose() if choose is not None else None

    with ui.element("span") as wrapper:
        button = (
            ui.button("Résumé", icon="picture_as_pdf", on_click=click)
            .props("outline dense no-caps")
            .classes("bg-white pl-1 pr-3")
            .mark(marker)
        )
        choose = pdf_chooser(native, add, marker) if editable and not has_resume else None
    if not has_resume:
        button.props("color=grey-7")
        if editable:
            wrapper.tooltip("No résumé on file: click to add one (PDF)")
        else:
            button.disable()
            wrapper.tooltip("No résumé on file")


def _resume_dialog(
    talent_id: str, name: str | None, *, service: AppService | None = None, native: bool = False
) -> None:
    """The résumé in the browser's (or webview's) own PDF viewer. With `service` (Talent
    screen): Replace résumé picks a new PDF, and only the Save that then appears replaces
    the stored file (user request 2026-11-18); Cancel drops the pick."""
    src = f"/resume/{quote(talent_id, safe='')}"
    pending: dict[str, bytes] = {}
    with (
        ui.dialog() as dialog,
        ui.card().style("width: 90vw; max-width: 90vw; height: 90vh; max-height: 90vh"),
    ):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label(f"Résumé: {name or talent_id}").classes("text-h6")
            with ui.row().classes("items-center gap-2 no-wrap"):
                if service is not None:

                    async def picked(data: bytes) -> None:
                        pending["data"] = data
                        confirm_row.set_visibility(True)

                    choose = pdf_chooser(native, picked, "resume-replace")
                    ui.button("Replace résumé", icon="upload_file", on_click=choose).props(
                        "outline dense no-caps"
                    ).classes("bg-white pl-1 pr-3").mark("resume-replace")
                ui.button(icon="close", on_click=dialog.close).props(
                    'flat round dense aria-label="Close"'
                ).tooltip("Close")
        with ui.row().classes(
            "w-full items-center gap-2 px-3 py-2 rounded bg-yellow-1"
        ) as confirm_row:
            ui.label("New résumé picked. Save replaces the one on file (the old copy is kept).")
            ui.button("Save", icon="save", on_click=lambda: save()).props(
                "dense no-caps color=primary"
            ).classes("pl-1 pr-3").mark("resume-save")
            ui.button("Cancel", on_click=lambda: cancel()).props("flat dense no-caps").mark(
                "resume-cancel"
            )
        confirm_row.set_visibility(False)
        frame = (
            ui.element("iframe")
            .props(f'src="{src}" title="Résumé"')
            .classes("w-full grow border-0")
            .mark("resume-frame")
        )

    def cancel() -> None:
        pending.clear()
        confirm_row.set_visibility(False)

    def save() -> None:
        assert service is not None
        data = pending.pop("data", None)
        if data is None:
            return
        try:
            outcome = service.save_resume(talent_id, data)
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="warning")
            return
        confirm_row.set_visibility(False)
        if outcome == "unchanged":
            ui.notify("That is the same file: nothing changed.")
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        frame.props(f'src="{src}?v={stamp}"')  # show the new file
        ui.notify("Résumé replaced.", type="positive")

    dialog.open()


def _meets_table(items: list[str]) -> None:
    """The "Meets" table (v10): TALENT ASSET (their skill or result) | JOB REQUIREMENT (the
    one it meets, summarized). Column names, in capitals: user decision 2026-11-08. Each
    stored item is "skill → requirement"; an older item without a requirement fills only the
    left column."""
    ui.label("Meets").classes("font-bold")
    with (
        ui.element("div")
        .classes("w-full grid grid-cols-2 gap-x-4 gap-y-1 text-sm")
        .mark("meets-table")
    ):
        for header in ("Talent Asset", "Job Requirement"):
            ui.label(header).classes("text-xs text-grey-7 uppercase border-b border-grey-4 pb-1")
        for item in items:
            skill, _, requirement = item.partition(MEETS_SEP)
            ui.label(skill)
            ui.label(requirement or "—").classes("text-grey-9")


def score_shade(service: AppService, score: int | None, fit: bool) -> str:
    """The verdict chip's colour: by fit_score band, or by verdict when there is no score
    (a contractor Gemini judged but did not describe)."""
    if score is None:
        return SHADE["green" if fit else "yellow"]
    bands = service.settings.app.score_bands
    if score >= bands.strong:
        return SCORE_SHADE["strong"]
    if score >= bands.good:
        return SCORE_SHADE["good"]
    if score >= bands.some:
        return SCORE_SHADE["some"]
    return SCORE_SHADE["low"]


def _rejected(review: Review | None) -> bool:
    return review is not None and review.decision is Decision.REJECTED


async def ask_reject_reason() -> tuple[ReasonCode, str] | None:
    """Wilson's "Why reject this match?" pop-up (Results and Review mode): the reason (required)
    and an optional note, or None when cancelled or no reason was picked."""
    with ui.dialog() as dialog, ui.card():
        ui.label("Why reject this match?").classes("text-h6")
        reason = (
            ui.select({code.value: text for code, text in REASON_TEXT.items()}, label="Reason")
            .classes("w-64")
            .mark("reject-reason")
        )
        notes = ui.input("Notes (optional)").classes("w-64")
        with ui.row():
            ui.button("Reject", on_click=lambda: dialog.submit(True)).props("color=negative").mark(
                "reject-confirm"
            )
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
    ok = await dialog
    chosen = reason.value
    note = notes.value or ""
    dialog.delete()
    if not ok:
        return None
    if not chosen:
        ui.notify("Pick a reason for the rejection.", type="warning")
        return None
    return ReasonCode(chosen), note


def _match_row(
    service: AppService,
    view: MatchView,
    moved: Callable[[], None] | None = None,
    job: Job | None = None,
    others: list[MatchView] | None = None,
    opened: set[str] | None = None,
) -> None:
    """One contractor on a Results card, as a compact row that opens on click. `moved`: called
    when a decision moves them in or out of "Show rejected" (a reject, or a reset or approve
    of a rejection), so the card redraws at once (user decision 2026-11-09; Results only).
    Every decision shows an Undo toast."""
    m = view.match
    state = {"review": view.decision}
    opened = opened if opened is not None else set()
    who = view.name or m.talent_id

    def after(before: Review | None) -> None:
        if moved is not None and _rejected(before) != _rejected(state["review"]):
            moved()
            return
        judgement.refresh()
        actions.refresh()
        paint()

    @ui.refreshable
    def judgement() -> None:
        """Top right: the decision tag and Reset, only once a decision is made."""
        review = state["review"]
        if review is None:
            return
        text, _ = DECISION_TEXT[review.decision]
        reason = f" ({REASON_TEXT[review.reason_code]})" if review.reason_code else ""
        with ui.row().classes("items-center gap-1"):
            ui.label(text + reason).classes("text-sm px-3 py-0.5 rounded-full font-medium").style(
                f"{shade_style(DECISION_SHADE[review.decision])} color: {TEXT_DARK};"
            )
            ui.button(icon="restart_alt", on_click=reset).props("flat round dense size=sm").mark(
                "reset-decision", f"reset:{m.talent_id}"
            ).tooltip("Undo: back to no decision")

    def open_email() -> None:
        if job is not None:
            ui_email.email_dialog(
                service,
                view,
                job,
                others=[o for o in (others or []) if o.match.match_id != m.match_id],
            )

    @ui.refreshable
    def actions() -> None:
        """The verdict buttons and "Write the email", on the collapsed row. The button of the
        decision already made is not offered again (no second Approve beside "Approved"); the
        others stay as the way to change it, and the tag's Undo clears it."""
        current = state["review"].decision if state["review"] else None
        with ui.row().classes("gap-2 flex-wrap justify-end items-center").mark("match-actions"):
            if current is not Decision.APPROVED:
                _shade_button(
                    "Approve", "green", lambda: save(Decision.APPROVED), icon="check"
                ).mark(f"approve:{m.talent_id}")
            if current is not Decision.REJECTED:
                _shade_button("Reject", "red", reject, icon="close").mark(f"reject:{m.talent_id}")
            if current is not Decision.NEEDS_INFO:
                _shade_button(
                    "Needs info", "yellow", lambda: save(Decision.NEEDS_INFO), icon="help_outline"
                ).mark(f"needs-info:{m.talent_id}")
            if job is not None:
                ui.button("Write the email", icon="mail_outline", on_click=open_email).props(
                    "dense no-caps "
                    + ("unelevated color=primary" if current is Decision.APPROVED else "outline")
                ).classes("px-3").mark(f"email:{m.talent_id}")

    def restore(before: Review | None) -> None:
        """Undo: put the decision back as it was (a new row in reviews.csv; nothing is erased)."""
        try:
            if before is None:
                service.clear_decision(m.match_id)
            else:
                service.decide(m.match_id, before.decision, before.reason_code, before.notes)
        except (AppError, CsvStoreError) as exc:
            ui.notify(str(exc), type="negative")
            return
        if moved is not None:
            moved()  # the card is redrawn from the saved decisions
            return
        current = state["review"]
        state["review"] = before
        after(current)

    def save(decision: Decision, reason: ReasonCode | None = None, notes: str = "") -> None:
        before = state["review"]
        try:
            state["review"] = service.decide(m.match_id, decision, reason, notes)
        except (AppError, CsvStoreError) as exc:
            ui.notify(str(exc), type="negative")
            return
        after(before)
        undo_toast(f"{DECISION_TEXT[decision][0]}: {who}.", lambda: restore(before))

    def reset() -> None:
        before = state["review"]
        try:
            service.clear_decision(m.match_id)
        except CsvStoreError as exc:
            ui.notify(str(exc), type="negative")
            return
        state["review"] = None
        after(before)
        undo_toast(f"Decision cleared for {who}.", lambda: restore(before))

    async def reject() -> None:
        picked = await ask_reject_reason()
        if picked is not None:
            save(Decision.REJECTED, *picked)

    def toggled(e: ValueChangeEventArguments) -> None:
        (opened.add if e.value else opened.discard)(m.match_id)
        if e.value:
            reason_label.classes(remove="dg-clamp2")
        else:
            reason_label.classes(add="dg-clamp2")

    fit = m.verdict.value == "fit"
    box = ui.row().classes("w-full items-start justify-between no-wrap gap-3 dg-compact")
    box.classes("rounded-xl border border-grey-4 px-3 py-1")
    box.mark("contractor-box")

    def paint() -> None:
        """Left border in the decision's colour (none when undecided). The width is kept
        constant with padding, so deciding never shifts the contractor's text sideways."""
        review = state["review"]
        if review is None:
            box.style(replace="border-left: 1px solid #BDBDBD; padding-left: calc(0.75rem + 3px);")
        else:
            colour = SHADE_EDGE[DECISION_SHADE[review.decision]]
            box.style(replace=f"border-left: 4px solid {colour}; padding-left: 0.75rem;")

    paint()
    collector = " · ".join(
        t for t in (getattr(job, "why_kept", None), getattr(job, "fits_roles", None)) if t
    )
    with box:
        with (
            ui.expansion(value=m.match_id in opened, on_value_change=toggled)
            .props("dense")
            .classes("flex-1 min-w-0 text-sm") as row
        ):
            with row.add_slot("header"), ui.column().classes("gap-0 w-full min-w-0 py-1"):
                with ui.row().classes("items-center gap-2").mark("match-head"):
                    ui.label(who).classes("font-bold")
                    if view.headline:
                        ui.label(view.headline).classes("text-grey-8")
                    # Only the verdict chip is coloured (by score band); the score is plain text.
                    chip_fill = score_shade(service, m.fit_score, fit)
                    ui.label("fit" if fit else "partial").classes(
                        "text-xs px-2 rounded-full font-semibold"
                    ).style(
                        f"background-color: {chip_fill}; color: {TEXT_DARK}; "
                        f"border: 1.5px solid {EDGE_BY_FILL.get(chip_fill, SHADE_EDGE['green'])};"
                    ).mark("verdict-chip")
                    if m.fit_score is not None:
                        ui.label(f"· score {m.fit_score}").classes("text-xs text-grey-8")
                    if not m.detailed:
                        ui.label("reason only").classes("text-xs text-grey-7 italic")
                    if view.unavailable:
                        ui.label("Not available for new projects").classes(
                            "text-xs px-2 rounded bg-grey-3 text-grey-9"
                        ).mark("unavailable-tag")
                reason_label = ui.label(m.reason or "").classes(
                    "text-sm" + ("" if m.match_id in opened else " dg-clamp2")
                )
                if collector:
                    ui.label(f"From the job collector: {collector}").classes(
                        "text-xs text-grey-7 dg-clamp2"
                    ).mark("collector-note")
            with ui.row().classes("gap-2 pb-2"):
                ui.button(
                    "Profile",
                    icon="badge",
                    on_click=lambda: _profile_dialog(service, m.talent_id, view.name),
                ).props("outline dense no-caps")
                resume_button(m.talent_id, view.name, view.has_resume, f"resume:{m.match_id}")
            if m.requirements_met:
                _meets_table(m.requirements_met)
            for title, items in (
                ("Missing", m.requirements_missing),
                ("Flags", m.red_flags),
            ):
                if items:
                    ui.label(title).classes("font-bold")
                    for item in items:
                        ui.label(f"• {item}")
            if m.unverified_evidence:
                ui.label(
                    "Something Gemini listed could not be found in their profile or the job, "
                    "so it was left out."
                ).classes("text-grey-7")
            if not m.detailed:
                ui.label(
                    "Gemini judged this contractor without describing them: only the reason "
                    "above is known."
                ).classes("text-grey-7")
        with ui.column().classes("items-end gap-1 shrink-0 pt-1"):
            judgement()
            actions()


def _open_url(url: str) -> Callable[[], None]:
    """Opens a web link in a new tab; anything that is not http(s) (javascript:, file:) is not."""

    def open_it() -> None:
        link = web_url_or_none(url)
        if link is None:
            ui.notify("That link is not a web address, so it was not opened.", type="warning")
            return
        ui.navigate.to(link, new_tab=True)

    return open_it


# ---- contact email and links between Jobs and Results (TODO 1 and 2, 2026-11-10) ----


WORK_MODE_TEXT = {
    RemoteType.ONSITE: "On-site", RemoteType.HYBRID: "Hybrid", RemoteType.REMOTE: "Remote",
}  # fmt: skip
PAY_UNIT_TEXT = {"hour": "hour", "day": "day", "week": "week", "month": "month", "year": "year"}


def pay_text(job: Job) -> str | None:
    """ "$90/hour", "$95,000/year", "$85–95/hour"; None when the pay is not known."""
    if job.pay_min is None and job.pay_max is None:
        return None
    low, high = job.pay_min or job.pay_max, job.pay_max or job.pay_min
    amount = f"${low:,.0f}" if low == high else f"${low:,.0f}–{high:,.0f}"
    unit = f"/{PAY_UNIT_TEXT[job.pay_unit.value]}" if job.pay_unit else ""
    return amount + unit


COMMITMENT_SHORT = {Commitment.FULL_TIME: "FT", Commitment.PART_TIME: "PT"}


def job_title(job: Job, classes: str = "") -> None:
    """The job title, with full-time / part-time after it in smaller text when known
    (user request 2026-11-10), e.g. "Bilingual (Fr/Eng) - PT"."""
    with ui.row().classes(f"items-baseline gap-x-2 gap-y-0 {classes}"):
        ui.label(title_case(job.title_norm or job.title_raw)).classes("text-h6")
        short = COMMITMENT_SHORT.get(job.commitment)
        if short:
            ui.label(f"- {short}").classes("text-sm font-medium text-grey-8").mark(
                f"commitment:{job.job_id}"
            ).tooltip("Full-time" if short == "FT" else "Part-time")


def contact_line(job: Job) -> None:
    """The posting's contact details (name, email, phone, apply link) with copy buttons, or a
    note that there is no email. Shown and copied only: the app never sends email."""
    with ui.row().classes("items-center gap-x-3 gap-y-0 text-sm").mark("contact-email"):
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.icon("mail_outline", size="16px").classes("text-grey-7")
            if job.contact_person:
                ui.label(job.contact_person).classes("font-medium").mark("contact-person")
            if not job.contact_email:
                ui.label("No contact email in the posting").classes("text-grey-7")
            else:
                ui.label(job.contact_email).classes("select-all")
                _copy_button(
                    job.contact_email, "Email copied.", "Copy email", f"copy-email:{job.job_id}"
                )
        phone = getattr(job, "contact_phone", None)
        if phone:
            with ui.row().classes("items-center gap-1 no-wrap").mark("contact-phone"):
                ui.icon("call", size="16px").classes("text-grey-7")
                ui.label(phone).classes("select-all")
                _copy_button(
                    phone, "Phone number copied.", "Copy phone", f"copy-phone:{job.job_id}"
                )
        apply_url = getattr(job, "apply_url", None)
        if apply_url:
            ui.button("Apply link", icon="open_in_new", on_click=_open_url(apply_url)).props(
                "flat dense no-caps size=sm"
            ).mark(f"apply-link:{job.job_id}")


def _copy_button(value: str, done: str, tip: str, marker: str) -> None:
    async def copy() -> None:
        if await ui_email.copy_to_clipboard(value):
            ui.notify(done, type="positive")
        else:
            ui.notify(ui_email.COPY_FAILED, type="warning")

    ui.button(icon="content_copy", on_click=copy).props(
        f'flat round dense size=sm aria-label="{tip}"'
    ).mark(marker).tooltip(tip)


def anchor(page: str, job_id: str) -> str:
    """The HTML id of a job's card on a page (job IDs hold ':' and other characters)."""
    return f"{page}-" + re.sub(r"[^A-Za-z0-9_-]", "-", job_id)


FOCUS_KEY = "focus_job"  # app.storage.client: the card the next screen scrolls to


def go_to_card(page: str, job_id: str) -> None:
    """Open Jobs or Results on one job's card (the screens read it on opening)."""
    nicegui_app.storage.client[FOCUS_KEY] = (page, job_id)
    ui.navigate.to(f"/{page}")


def take_focus(page: str) -> str | None:
    """The job this screen was opened for, if any (read once)."""
    focus = nicegui_app.storage.client.pop(FOCUS_KEY, None)
    if focus and focus[0] == page:
        return str(focus[1])
    return None


def scroll_to_card(page: str, job_id: str) -> None:
    """Scroll to the card and outline it in purple for about 2 seconds."""
    target = anchor(page, job_id)
    js = (
        f"const el = document.getElementById('{target}'); if (el) {{"
        " el.scrollIntoView({behavior: 'smooth', block: 'center'});"
        f" el.style.outline = '3px solid {THEME_PRIMARY}'; el.style.outlineOffset = '2px';"
        " setTimeout(() => { el.style.outline = ''; }, 2000); }"
    )
    ui.timer(0.3, lambda: ui.run_javascript(js), once=True)


def _chip(text: str, icon: str, shade: str | None = None) -> None:
    style = (
        shade_style(shade) if shade else "background-color: #F3EEFB; border: 1.5px solid #E0D5F3;"
    )
    ui.chip(text, icon=icon, color=None, text_color=None).props("dense").classes(
        "m-0 text-sm"
    ).style(f"{style} color: {TEXT_DARK};")


RESULTS_VIEW_KEY = "results_view"  # app.storage.client: "approved" = the next Results shows them


def go_to_approved() -> None:
    """Open Results showing only the people approved so far (the Home tile)."""
    nicegui_app.storage.client[RESULTS_VIEW_KEY] = "approved"
    ui.navigate.to("/results")


def approved_only(result: JobResult) -> JobResult | None:
    """The job with only its approved people; None when nobody is approved for it."""
    mine = [
        m
        for m in result.matches
        if m.decision is not None and m.decision.decision is Decision.APPROVED
    ]
    return result.model_copy(update={"matches": mine, "rejected": []}) if mine else None


def _job_card(
    service: AppService,
    result: JobResult,
    keep: Callable[[JobResult], JobResult | None] | None = None,
) -> None:
    """One job on Results. Redraws itself when a reject or a reset moves someone in or out
    of "Show rejected" (that section stays open if it was). `keep`: the view in force (only
    approved people), applied again after every redraw."""
    state = {"result": result, "open": False}
    rows: set[str] = set()  # matches shown open (kept when the card is redrawn)

    def moved() -> None:
        fresh = service.job_result(result.job.job_id)
        if fresh is not None:
            state["result"] = (keep(fresh) if keep else fresh) or fresh.model_copy(
                update={"matches": [], "rejected": []}
            )
        card.refresh()

    def remember(e: ValueChangeEventArguments) -> None:
        state["open"] = bool(e.value)

    @ui.refreshable
    def card() -> None:
        _job_card_body(service, state["result"], moved, bool(state["open"]), remember, rows)

    card()


def _job_card_body(
    service: AppService,
    result: JobResult,
    moved: Callable[[], None],
    rejected_open: bool,
    remember: Callable[[ValueChangeEventArguments], None],
    rows: set[str] | None = None,
) -> None:
    job = result.job
    text, _ = OUTCOME_TEXT[result.outcome]
    shade = OUTCOME_SHADE.get(result.outcome)
    band = (
        f"background-color: {SHADE[shade]}; border-bottom: 2px solid {SHADE_EDGE[shade]};"
        if shade
        else "background-color: #F3EEFB; border-bottom: 1px solid #E0D5F3;"
    )
    with (
        ui.card()
        .props(f'flat bordered id="{anchor("results", job.job_id)}"')
        .classes("w-full p-0 gap-0 rounded-2xl overflow-hidden")
        .style(f"border: 2px solid {SHADE_EDGE[shade]};" if shade else "")
    ):
        with ui.row().classes("w-full items-center justify-between no-wrap px-4 py-3").style(band):
            job_title(job, "flex-1 min-w-0")
            ui.button(
                "See on Jobs", icon="work", on_click=lambda: go_to_card("jobs", job.job_id)
            ).props("outline dense no-caps").classes("bg-white pl-1 pr-3").mark(
                f"see-jobs:{job.job_id}"
            )
            ui.button(icon="open_in_new", on_click=_open_url(job.url)).props(
                'outline round dense aria-label="Open posting"'
            ).classes("bg-white").mark("open-posting").tooltip("Open posting")
        with ui.row().classes(
            "w-full items-center gap-2 px-4 pt-3" + ("" if result.matches else " pb-3")
        ):
            if job.company_raw:
                _chip(job.company_raw, "business")
            if job.location_raw:
                _chip(job.location_raw, "place")
            if job.remote_type is not RemoteType.UNKNOWN:
                _chip(WORK_MODE_TEXT[job.remote_type], "apartment")
            if job.hours_per_week:
                _chip(f"{job.hours_per_week:g} h/week", "schedule")
            if pay := pay_text(job):
                _chip(pay, "payments")
            _chip(text, "fact_check", shade)
            contact_line(job)
        if result.matches:
            with ui.column().classes("w-full gap-3 p-4"):
                for view in result.matches:
                    _match_row(service, view, moved, job, result.matches, rows)
        if result.rejected:
            # The reviewer's rejections: hidden, still holding their slot in the round, and
            # brought back with Reset (user decision 2026-11-09: rejections are often
            # misclicks).
            with (
                ui.expansion(
                    f"Show rejected ({len(result.rejected)})",
                    icon="visibility_off",
                    value=rejected_open,
                    on_value_change=remember,
                )
                .classes("w-full px-4 pb-2 text-sm text-grey-8")
                .mark("show-rejected"),
                ui.column().classes("w-full gap-3 py-2"),
            ):
                for view in result.rejected:
                    _match_row(service, view, moved, job, result.matches, rows)


async def export_to_excel(service: AppService, native: bool) -> None:
    """The Export to Excel button (Results and the end of Review mode)."""
    try:
        done = await run.io_bound(service.export)
    except RUN_ERRORS as exc:
        ui.notify(str(exc), type="negative")
        return
    if done is None:
        return
    ui.notify(f"Saved {done.path.name} ({done.rows} rows). It holds names: keep it local.")
    if native:
        open_in_file_manager(done.path)
    else:
        ui.download.file(done.path)


def results_page(service: AppService, native: bool) -> None:
    results = service.results()
    only_approved = nicegui_app.storage.client.pop(RESULTS_VIEW_KEY, None) == "approved"
    counts = {k: sum(r.outcome == k for r in results) for k in OUTCOME_TEXT}
    undecided = sum(m.decision is None for r in results for m in r.matches)
    if only_approved:
        results = [kept for r in results if (kept := approved_only(r)) is not None]
    with ui.column().classes(f"{PAGE} gap-3"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Results").classes("text-h5")
            if undecided and not only_approved:
                ui.button(
                    f"Review {plural(undecided, 'match', 'matches')} one by one",
                    icon="playlist_add_check",
                    on_click=_go("/review"),
                ).props("unelevated no-caps color=primary").classes("dg-main-sm").mark(
                    "review-matches"
                )
        if only_approved:
            people = sum(len(r.matches) for r in results)
            with ui.row().classes("w-full items-center gap-3").mark("results-approved-view"):
                ui.label(
                    f"Showing only approved people: {plural(people, 'person', 'people')} on "
                    f"{plural(len(results), 'job')}"
                ).classes("text-sm text-grey-8")
                ui.button("Show everything", icon="visibility", on_click=_go("/results")).props(
                    "flat dense no-caps color=primary"
                ).mark("results-show-all")
        else:
            ui.label(
                f"{plural(counts['fits'], 'job')} with clear fits · {counts['check_partial']} to "
                f"check by hand · {counts['no_match']} with no match · {counts['not_judged']} not "
                "checked yet"
            ).classes("text-sm text-grey-8")
        if not results:
            ui.label(
                "Nobody is approved yet. Review your matches on Home."
                if only_approved
                else "No jobs yet. Add a jobs file on Home and click Find matches."
            )
        for result in results:
            _job_card(service, result, approved_only if only_approved else None)
        focus = take_focus("results")
        if focus:
            scroll_to_card("results", focus)

        async def export() -> None:
            await export_to_excel(service, native)

        with ui.row().classes("w-full justify-between py-4"):
            ui.button("Export to Excel", icon="download", on_click=export).props("outline")
            ui.button(
                "Add jobs / new search", icon="add", on_click=lambda: ui.navigate.to("/")
            ).props("color=primary")


# ---- screen: jobs ----

# (background, border) per state. Green: matched; red: analyzed, nobody fits (still open for
# later runs); yellow: waiting to be analyzed; grey: completed or unavailable (never sent).
JOB_STATE_STYLE: dict[JobState, tuple[str, str]] = {
    "matched": ("#E4F8E9", "#2E9D5B"),
    "no_match": ("#FCE3E6", "#C0392B"),
    "waiting": ("#FFF4C7", "#D9A21B"),
    "inactive": ("#F1EFF5", "#B9B2C9"),
}
JOB_STATE_TEXT: dict[JobState, str] = {
    "matched": "Checked",
    "no_match": "Checked",
    "waiting": "Not checked yet",
    "inactive": "Closed",
}


# The application statuses, in the dropdown's order (user wording 2026-11-09).
APPLICATION_TEXT: dict[ApplicationStatus, str] = {
    ApplicationStatus.NOT_REFERRED: "Not referred yet",
    ApplicationStatus.OUTREACHED: "Outreached to HR",
    ApplicationStatus.IN_PROGRESS: "HR replied, in progress",
    ApplicationStatus.REJECTED: "Rejection / Ghosted",
    ApplicationStatus.HIRED: "Hired",
}


def _candidates_table(service: AppService, item: JobOverview, refresh: Callable[[], None]) -> None:
    """The approved candidates of one job: name, headline, score, the application status
    dropdown with Save; a rejected or ghosted application is greyed with Undo."""
    job_id = item.job.job_id
    if not item.candidates:
        ui.label("Nobody approved yet. Approve people on Results.").classes("text-sm text-grey-7")
        return

    def run_action(
        action: Callable[[], object], done: str, undo: Callable[[], object] | None = None
    ) -> None:
        try:
            action()
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="warning")
            return
        refresh()
        if undo is None:
            ui.notify(done, type="positive")
        else:
            undo_toast(done, lambda: run_action(undo, "Undone."))

    with ui.element("div").classes(
        "w-full grid grid-cols-[minmax(8rem,1fr)_minmax(8rem,2fr)_auto_minmax(13rem,auto)_auto] "
        "items-center gap-x-4 gap-y-2 text-sm"
    ):
        # A no-break space for the Save column's header: an empty label has no height, so its
        # underline sat higher than the others (user request 2026-11-10).
        for header in ("Candidate", "Headline", "Score", "Application status", "\u00a0"):
            ui.label(header).classes(
                "text-xs text-grey-7 uppercase border-b border-grey-4 pb-1 self-end"
            )
        for c in item.candidates:
            key = f"{job_id}:{c.talent_id}"
            dim = " opacity-50 line-through" if c.removed else ""
            ui.label(c.name or c.talent_id).classes("font-bold" + dim)
            ui.label(c.headline or "").classes("text-grey-8" + dim)
            score = c.match.fit_score if c.match and c.match.fit_score is not None else None
            ui.label("—" if score is None else str(score)).classes(dim)
            if c.removed:
                ui.label(APPLICATION_TEXT[ApplicationStatus.REJECTED]).classes("text-grey-7")
                ui.button(
                    "Undo",
                    icon="undo",
                    on_click=lambda t=c.talent_id: run_action(
                        lambda: service.undo_application_rejection(job_id, t), "Brought back."
                    ),
                ).props("outline dense no-caps").classes("bg-white").mark(f"undo:{key}")
                continue
            choice = (
                ui.select({s.value: text for s, text in APPLICATION_TEXT.items()}, value=c.status)
                .props("dense outlined bg-color=white")
                .classes("w-full")
                .mark(f"status:{key}")
            )

            def save(
                t: str = c.talent_id, box: ui.select = choice, prev: ApplicationStatus = c.status
            ) -> None:
                status = ApplicationStatus(box.value)
                note = (
                    "Saved. The job is marked completed."
                    if status is ApplicationStatus.HIRED
                    else "Saved."
                )
                undo = None  # a hire changes other things (the job closes): no one-click undo
                if status is ApplicationStatus.REJECTED:
                    undo = lambda: service.undo_application_rejection(job_id, t)  # noqa: E731
                elif ApplicationStatus.HIRED not in (status, prev):
                    undo = lambda: service.set_application(job_id, t, prev)  # noqa: E731
                run_action(lambda: service.set_application(job_id, t, status), note, undo)

            ui.button("Save", icon="save", on_click=save).props("outline dense no-caps").classes(
                "bg-white"
            ).mark(f"save-status:{key}")


DANGER = "#C62828"  # red for destructive actions (Quasar's red-9)


def confirm_delete(title: str, lines: list[str], on_confirm: Callable[[], None]) -> None:
    """Every deletion asks first (user request 2026-11-10): a pop-up naming what goes,
    with Cancel as the safe default."""
    with ui.dialog() as dialog, ui.card().classes("max-w-lg"):
        ui.label(title).classes("text-h6")
        for line in lines:
            ui.label(line).classes("text-sm")
        ui.label("This cannot be undone from the app.").classes("text-sm font-medium")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps").mark("delete-cancel")

            def go() -> None:
                dialog.close()
                on_confirm()

            ui.button("Delete", icon="delete_forever", on_click=go).props(
                "unelevated no-caps text-color=white"
            ).props("color=red-9").mark("delete-confirm")
    dialog.open()


def danger_button(text: str, on_click: Callable[[], None], marker: str) -> ui.button:
    """A red button for a deletion; icon only when `text` is empty. The colour goes through
    Quasar's own `color` prop (a style alone can be overridden by the theme)."""
    button = ui.button(text or None, icon="delete_forever", on_click=on_click).props(
        "unelevated dense no-caps color=red-9 text-color=white"
    )
    if text:
        button.classes("pl-1 pr-3")
    else:
        button.props('aria-label="Delete"').classes("px-2")
    return button.mark(marker)


def job_status(item: JobOverview) -> tuple[str, str]:
    """The Jobs row's state line and, apart from it, what is still to check. A job that has
    matches AND new people not checked yet says both: "Checked · 2 matches · best score 98" and
    "3 new people not checked yet" (the matches stay valid). Otherwise the usual wording."""
    if item.state == "waiting" and item.summary:
        news = (
            f"{plural(item.new_people, 'new person', 'new people')} not checked yet"
            if item.new_people
            else "Not checked yet"
        )
        return f"Checked · {item.summary}", news
    line = JOB_STATE_TEXT[item.state]
    return (f"{line} · {item.summary}" if item.summary else line), ""


def _jobs_card(
    service: AppService,
    item: JobOverview,
    refresh: Callable[[], None],
    opened: set[str],
    new: bool = False,
) -> None:
    """One job as a compact row (title, place, state line); click it to see the contact,
    the terms and the approved candidates. The buttons stay on the right."""
    job = item.job
    background, border = JOB_STATE_STYLE[item.state]
    grey = item.state == "inactive"
    title = title_case(job.title_norm or job.title_raw)

    def change(action: JobAction, text: str, undo_action: JobAction | None) -> None:
        try:
            service.set_job_availability(job.job_id, action)
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="warning")
            return
        refresh()
        if undo_action is None:
            return

        def undo() -> None:
            try:
                service.set_job_availability(job.job_id, undo_action)
            except RUN_ERRORS as exc:
                ui.notify(str(exc), type="warning")
                return
            refresh()

        undo_toast(f"{text}: {title}.", undo)

    def act(action: JobAction) -> Callable[[], None]:
        def handler() -> None:
            if action == "unavailable":
                change(action, "Marked unavailable", "reopen")
            elif action == "reopen":
                was_unavailable = job.availability is JobAvailability.UNAVAILABLE
                change(action, "Reopened", "unavailable" if was_unavailable else None)
            else:
                change(action, "Saved", None)

        return handler

    def remember(e: ValueChangeEventArguments) -> None:
        (opened.add if e.value else opened.discard)(job.job_id)

    def delete() -> None:
        def go() -> None:
            try:
                kept = service.delete_job(job.job_id)
            except RUN_ERRORS as exc:
                ui.notify(str(exc), type="warning")
                return
            ui.notify(
                f"Deleted {title}."
                + (f" Still listed for {plural(kept, 'contractor')} on Talent." if kept else ""),
                type="positive",
            )
            refresh()

        confirm_delete(
            f"Delete {title}?",
            [
                "The job leaves the app: Jobs, Results and future matching. Its checks, rounds, "
                "application statuses and Gemini's results are deleted.",
                "Added again later, it is sent to Gemini afresh.",
                "A contractor hired for it still sees it on the Talent screen.",
            ],
            go,
        )

    card = (
        ui.card()
        .props(f'flat id="{anchor("jobs", job.job_id)}"')
        .classes("w-full px-3 py-1 gap-1 rounded-2xl dg-row")
    )
    card.style(f"background-color: {background}; border: 2px solid {border};")
    card.mark("job-card", f"job-state-{item.state}")
    active = [c for c in item.candidates if not c.removed]
    with card, ui.row().classes("w-full items-start no-wrap gap-3"):
        with (
            ui.expansion(value=job.job_id in opened, on_value_change=remember)
            .props("dense")
            .classes("flex-1 min-w-0 text-sm")
            .mark(f"candidates:{job.job_id}") as row
        ):
            with (
                row.add_slot("header"),
                ui.column().classes("gap-0 w-full min-w-0 py-1" + (" opacity-60" if grey else "")),
            ):
                with ui.row().classes("items-center gap-2"):
                    job_title(job)
                    if new:
                        ui.label("New").classes("dg-new-tag").mark("new-tag")
                where = " · ".join(p for p in (job.company_raw, job.location_raw) if p)
                terms = " · ".join(
                    p
                    for p in (
                        WORK_MODE_TEXT.get(job.remote_type),
                        f"{job.hours_per_week:g} h/week" if job.hours_per_week else None,
                        pay_text(job),
                    )
                    if p
                )
                if where or terms:
                    ui.label(" · ".join(p for p in (where, terms) if p)).classes(
                        "text-sm text-grey-8"
                    )
                line, news = job_status(item)
                with ui.row().classes("items-center gap-3"):
                    ui.label(line).classes("text-sm font-medium").mark("job-summary")
                    if news:
                        ui.label(news).classes("text-xs px-2 rounded-full font-medium").style(
                            shade_style("yellow") + f" color: {TEXT_DARK};"
                        ).mark("job-new-people")
                    if active:
                        ui.label(f"{len(active)} approved").classes(
                            "text-xs px-2 rounded-full bg-white"
                        ).style(f"border: 1.5px solid {border};")
            with ui.column().classes("w-full gap-2 pt-1" + (" opacity-60" if grey else "")):
                contact_line(job)
                why = " · ".join(
                    t
                    for t in (getattr(job, "why_kept", None), getattr(job, "fits_roles", None))
                    if t
                )
                if why:
                    ui.label(f"From the job collector: {why}").classes("text-xs text-grey-7").mark(
                        "collector-note"
                    )
                ui.label(f"Approved candidates ({len(active)})").classes("font-bold text-sm")
                _candidates_table(service, item, refresh)
        with ui.row().classes("items-center gap-2 no-wrap shrink-0 pt-1"):
            if not grey:  # closed jobs are not on Results
                ui.button(
                    "See on Results",
                    icon="fact_check",
                    on_click=lambda: go_to_card("results", job.job_id),
                ).props("outline dense no-caps").classes("bg-white pl-1 pr-3").mark(
                    f"see-results:{job.job_id}"
                )
            ui.button(icon="open_in_new", on_click=_open_url(job.url)).props(
                'outline round dense aria-label="Open posting"'
            ).classes("bg-white").tooltip("Open posting")
            if grey:
                text, icon, action, tip = (
                    "Reopen", "replay", "reopen", "Available again for matching"
                )  # fmt: skip
            else:
                # No Completed button (user request 2026-11-10): a job is completed when an
                # application is set to Hired.
                text, icon, action, tip = (
                    "Unavailable", "block", "unavailable", "The posting expired or is not valid"
                )  # fmt: skip
            ui.button(text, icon=icon, on_click=act(action)).props(
                "outline dense no-caps align=center"
            ).classes("bg-white items-center pl-1 pr-3").mark(f"{action}:{job.job_id}").tooltip(tip)
            if grey:
                danger_button("", delete, f"delete-job:{job.job_id}").tooltip(
                    "Delete this closed job from the app"
                )


def keep_order(jobs: list[JobOverview], order: list[str]) -> list[JobOverview]:
    """`jobs` in the order already on screen (job IDs in `order`); any job not shown yet
    goes after them, in the service's order. A toggle repaints the cards without moving them;
    the new order shows on the next visit or page refresh."""
    place = {job_id: i for i, job_id in enumerate(order)}
    return sorted(jobs, key=lambda o: place.get(o.job.job_id, len(place)))


def _fold(text: str) -> str:
    """Lower case without accents, so "quebec" finds "Québec" (French postings)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def job_matches_search(job: Job, words: list[str]) -> bool:
    """Every search word appears in the job's title or company (user request 2026-11-10)."""
    text = _fold(" ".join(t for t in (job.title_norm, job.title_raw, job.company_raw) if t))
    return all(_fold(w) in text for w in words)


JOB_FILTERS = {
    "all": "All (A–Z)",
    "approved": "With approved candidates",
    "unavailable": "Unavailable",
}


def job_in_filter(item: JobOverview, name: str) -> bool:
    """The Jobs screen filters (user request 2026-11-10). "all" keeps the default order:
    open jobs A–Z, then closed ones A–Z."""
    if name == "approved":
        return any(not c.removed for c in item.candidates)
    if name == "unavailable":
        return item.job.availability is JobAvailability.UNAVAILABLE
    return True


def jobs_page(service: AppService, native: bool) -> None:
    shown: list[str] = []  # job IDs in on-screen order, fixed when the page opens
    opened: set[str] = set()  # cards whose candidates table is open (kept across repaints)
    query = {"text": "", "filter": "all"}
    new_jobs = service.new_items().jobs  # what arrived since this screen was last opened
    service.mark_seen("jobs")
    focus = take_focus("jobs")  # opened from a Results card: its candidates table open
    if focus:
        opened.add(focus)

    @ui.refreshable
    def body() -> None:
        jobs = keep_order(service.jobs_overview(), shown)
        shown[:] = [o.job.job_id for o in jobs]
        counts = {s: sum(j.state == s for j in jobs) for s in JOB_STATE_STYLE}
        scanned = counts["matched"] + counts["no_match"]
        left_out = service.jobs_left_out()
        with ui.row().classes("items-center gap-2"):
            ui.label(
                f"{plural(len(jobs), 'job')} · {scanned} checked ({counts['matched']} with "
                f"matches, {counts['no_match']} with no match) · {counts['waiting']} not checked "
                f"yet · {counts['inactive']} closed"
            ).classes("text-sm text-grey-8")
            if left_out:
                ui.button(
                    f"{plural(len(left_out), 'job')} left out: see why",
                    on_click=lambda: left_out_dialog(left_out),
                ).props("flat dense no-caps color=primary").classes("px-1").mark("jobs-left-out")
        words = query["text"].split()
        matching = [
            o
            for o in jobs
            if job_matches_search(o.job, words) and job_in_filter(o, query["filter"])
        ]
        if not jobs:
            ui.label("No jobs yet. Add a jobs file on Home and click Find matches.")
        elif not matching:
            ui.label("No job matches the search.").classes("text-grey-7")
        for item in matching:
            _jobs_card(service, item, body.refresh, opened, item.job.job_id in new_jobs)

    def search(e: ValueChangeEventArguments) -> None:
        query["text"] = e.value or ""
        body.refresh()

    def pick_filter(name: str) -> None:
        query["filter"] = name
        filter_button.text = "" if name == "all" else JOB_FILTERS[name]
        filter_button.props(f"color={'primary' if name != 'all' else 'grey-8'}")
        body.refresh()

    with ui.column().classes(f"{PAGE} gap-3"):
        with ui.row().classes("items-center gap-1"):
            ui.label("Jobs").classes("text-h5")
            help_icon(
                "A job is completed when an approved candidate is set to Hired. Mark a job "
                "Unavailable to stop matching it. Reopen puts it back, and the next Find "
                "matches only checks people not yet checked for it. A closed job can be "
                "deleted."
            )
        with ui.row().classes("w-full items-center gap-3"):
            ui.input(placeholder="Search by job title or company", on_change=search).props(
                "dense outlined clearable bg-color=white"
            ).classes("w-full max-w-md").mark("jobs-search")
            # A filter icon with a dropdown (user request 2026-11-10); it names the filter
            # while one other than "All" is on.
            with (
                ui.button(icon="filter_list")
                .props("outline dense no-caps icon-right=arrow_drop_down color=grey-8")
                .classes("bg-white pl-2")
                .mark("jobs-filter")
                .tooltip("Filter jobs") as filter_button,
                ui.menu(),
            ):
                for name, text in JOB_FILTERS.items():
                    ui.menu_item(text, on_click=lambda n=name: pick_filter(n)).mark(
                        f"jobs-filter:{name}"
                    )
        body()
        if focus:
            scroll_to_card("jobs", focus)


# ---- screen: talent ----

# By available. Unavailable: a clearly grey card, distinct from the white sheet.
TALENT_STYLE = {True: ("#FFFFFF", "#D9CEF0"), False: ("#ECE9F2", "#A79FBC")}


def _talent_jobs_table(item: TalentOverview) -> None:
    """The jobs a contractor was approved for, with the status set on the Jobs screen
    (read-only here). Rejected / ghosted applications and closed jobs are greyed."""
    if not item.jobs:
        ui.label("Not approved for any job yet.").classes("text-sm text-grey-7")
        return
    with ui.element("div").classes(
        "w-full grid grid-cols-[minmax(10rem,2fr)_minmax(8rem,1fr)_minmax(8rem,1fr)_auto] "
        "items-center gap-x-4 gap-y-2 text-sm"
    ):
        for header in ("Job title", "Company", "Location", "Application status"):
            ui.label(header).classes("text-xs text-grey-7 uppercase border-b border-grey-4 pb-1")
        for job in item.jobs:
            dim = " text-grey-6" if job.removed or not job.job_open else ""
            closed = " (removed)" if job.deleted else "" if job.job_open else " (closed)"
            title = title_case(job.title) + closed
            ui.label(title).classes("font-medium" + dim)
            ui.label(job.company or "—").classes(dim)
            ui.label(job.location or "—").classes(dim)
            ui.label(APPLICATION_TEXT[job.status]).classes(dim).mark(
                f"talent-status:{item.talent_id}:{job.job_id}"
            )


def _day(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def free_chip(item: TalentOverview) -> tuple[str, str]:
    """The real-world availability chip (from the profile's own words), whether or not the
    contractor is included in matching: "Available now" (green), "Available from Dec 2, 2026"
    (blue), "Booked until Mar 18, 2027" (orange); any other wording is shown as written."""
    if item.free_state == "now":
        return "Available now", "bg-green-2 text-green-10"
    if item.free_state == "later" and item.free_date:
        return f"Available from {_day(item.free_date)}", "bg-blue-1 text-blue-10"
    if item.free_state == "booked":
        until = f" until {_day(item.free_date)}" if item.free_date else ""
        return f"Booked{until}", "bg-orange-2 text-orange-10"
    return plain_dates_in(str(item.availability)), "bg-blue-1 text-blue-10"


TALENT_FILTERS = {
    "all": "Everyone",
    "now": "Available now",
    "later": "Booked or free later",
    "left_out": "Left out of matching",
}
TALENT_SORTS = {"name": "Name (A–Z)", "updated": "Recently updated"}


def talent_group(item: TalentOverview) -> str:
    """Each contractor is in exactly one group, so the header counts add up: left out of
    matching, available now, or booked / free later."""
    if not item.available:
        return "left_out"
    return "now" if item.available_now else "later"


def talent_in_filter(item: TalentOverview, name: str) -> bool:
    return name == "all" or talent_group(item) == name


def sort_talent(items: list[TalentOverview], how: str) -> list[TalentOverview]:
    """ "name": people in matching first, then A-Z (the service's order); "updated": the
    newest profile first, profiles with no date last."""
    if how == "updated":
        return sorted(
            items,
            key=lambda t: (t.profile_updated is None, -(t.profile_updated or date.min).toordinal()),
        )
    return list(items)


def profile_age(updated: date | None, today: date | None = None) -> tuple[str, bool] | None:
    """ "Profile updated 2026-03-01 (8 months ago)" and whether it is getting old (6 months or
    more); None when the profile has no date."""
    if updated is None:
        return None
    days = ((today or datetime.now(UTC).date()) - updated).days
    months = days // 30
    ago = "this month" if months < 1 else f"{plural(months, 'month')} ago"
    return f"Profile updated {plain_day(updated)} ({ago})", months >= 6


def _talent_card(
    service: AppService,
    item: TalentOverview,
    refresh: Callable[[], None],
    opened: set[str],
    sheet_url: str = "",
    native: bool = False,
    new: bool = False,
) -> None:
    """One contractor as a compact row (name, tags, headline); click it for the note, the
    approved jobs and the ID tools. The switch, Profile and Résumé stay on the row."""
    background, border = TALENT_STYLE[item.available]
    card = ui.card().props("flat").classes("w-full px-3 py-1 gap-1 rounded-2xl dg-row")
    card.style(f"background-color: {background}; border: 2px solid {border};")
    card.mark("talent-card", f"talent-{'available' if item.available else 'unavailable'}")

    def flip(e: ValueChangeEventArguments) -> None:
        """The switch saves as soon as it is flipped (user decision 2026-11-18); the toast
        has Undo."""
        before, before_note = item.available, (item.toggled.note if item.toggled else "") or ""
        try:
            service.set_talent_availability(item.talent_id, bool(e.value))
        except RUN_ERRORS as exc:
            ui.notify(str(exc), type="warning")
            return
        refresh()

        def undo() -> None:
            try:
                service.set_talent_availability(item.talent_id, before, before_note)
            except RUN_ERRORS as exc:
                ui.notify(str(exc), type="warning")
                return
            refresh()

        state = "included in matching" if e.value else "left out of matching"
        undo_toast(f"Saved: {state}.", undo)

    def remember(e: ValueChangeEventArguments) -> None:
        (opened.add if e.value else opened.discard)(item.talent_id)

    def delete() -> None:
        def go() -> None:
            try:
                service.delete_talent(item.talent_id)
            except RUN_ERRORS as exc:
                ui.notify(str(exc), type="warning")
                return
            ui.notify(f"Deleted {item.name}.", type="positive")
            refresh()

        confirm_delete(
            f"Delete {item.name}?",
            [
                "Everything about them leaves the app: profile, résumé, availability, "
                "recommendations, your decisions on them and their application statuses.",
                "Your contractor folder is not touched: adding it again brings them back.",
            ],
            go,
        )

    def copy_id() -> None:
        ui.clipboard.write(item.talent_id)
        ui.notify(f"ID {item.talent_id} copied.", type="positive")

    def open_sheet() -> None:
        ui.clipboard.write(item.talent_id)
        ui.navigate.to(sheet_url, new_tab=True)
        toast(
            f"ID {item.talent_id} copied. Search for it in the Sheet (Ctrl+F).",
            icon="content_paste",
        )

    age = profile_age(getattr(item, "profile_updated", None))
    availability = getattr(item, "availability", None)
    same = list(getattr(item, "same_name_ids", []) or [])
    with card, ui.row().classes("w-full items-start no-wrap gap-3"):
        # The availability switch, in its own section on the left (user request).
        with ui.column().classes(
            "items-center justify-center gap-0 pr-2 border-r border-grey-4 w-24 shrink-0 "
            "self-stretch"
        ):
            ui.switch(value=item.available, on_change=flip).mark(f"available:{item.talent_id}")
            ui.label("Include in matching").classes(
                "text-xs text-grey-8 text-center leading-tight"
            ).mark(f"include-label:{item.talent_id}")
        with (
            ui.expansion(value=item.talent_id in opened, on_value_change=remember)
            .props("dense")
            .classes("flex-1 min-w-0 text-sm")
            .mark(f"talent-jobs:{item.talent_id}") as row
        ):
            with row.add_slot("header"), ui.column().classes("gap-0 w-full min-w-0 py-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(item.name).classes("text-h6")
                    if new:
                        ui.label("New").classes("dg-new-tag").mark("new-tag")
                    if not item.available:
                        ui.label("Left out of matching").classes(
                            "text-xs px-2 rounded bg-grey-4 text-grey-9"
                        ).mark("left-out-tag")
                    # The contractor's own answer, when the reviewer's toggle disagrees.
                    if item.toggled is not None and item.toggled.available != item.profile_open:
                        said = "open" if item.profile_open else "not open"
                        ui.label(f"Profile says: {said} to contract work").classes(
                            "text-xs px-2 rounded bg-yellow-2 text-grey-9"
                        ).mark("profile-disagrees")
                    elif item.toggled is None and not item.profile_open:
                        ui.label("Profile says: not open to contract work").classes(
                            "text-xs px-2 rounded bg-grey-3 text-grey-9"
                        )
                    if availability:
                        text, colours = free_chip(item)
                        ui.label(text).classes(f"text-xs px-2 rounded {colours}").mark(
                            "availability-note"
                        )
                    if same:
                        ui.label("Same name as another contractor").classes(
                            "text-xs px-2 rounded bg-orange-2 text-grey-9"
                        ).mark("same-name-flag").tooltip("Maybe a duplicate: " + ", ".join(same))
                if item.headline:
                    ui.label(item.headline).classes("text-grey-8 dg-clamp2")
            with ui.column().classes("w-full gap-2 pt-1"):
                if item.toggled is not None:
                    t = item.toggled
                    state = "available" if t.available else "not available"
                    line = f"Set {state} by {t.reviewer} on {plain_day(t.changed_at.astimezone())}."
                    ui.label(line).classes("text-xs text-grey-7").mark("talent-set")
                if age is not None:
                    ui.label(age[0]).classes(
                        "text-xs " + ("text-orange-9 font-medium" if age[1] else "text-grey-7")
                    ).mark("profile-age")
                ui.label(item.note or "No note").classes(
                    "w-full max-w-xs text-sm px-2 py-1 rounded border border-grey-4 bg-white "
                    "whitespace-pre-wrap " + ("" if item.note else "text-grey-6 italic")
                ).mark(f"note:{item.talent_id}")
                with ui.row().classes("items-center gap-2"):
                    ui.button("Copy ID", icon="content_copy", on_click=copy_id).props(
                        "outline dense no-caps"
                    ).classes("bg-white pl-1 pr-3").mark(f"copy-id:{item.talent_id}").tooltip(
                        item.talent_id
                    )
                    if sheet_url:
                        ui.button("Open in Sheet", icon="table_chart", on_click=open_sheet).props(
                            "outline dense no-caps"
                        ).classes("bg-white pl-1 pr-3").mark(f"open-sheet:{item.talent_id}")
                live = [j for j in item.jobs if not j.removed]
                ui.label(f"Approved for jobs ({len(live)})").classes("font-bold text-sm")
                _talent_jobs_table(item)
                if not item.available:
                    danger_button(
                        "Delete this contractor", delete, f"delete-talent:{item.talent_id}"
                    )
        with ui.row().classes("items-center justify-end gap-2 no-wrap shrink-0 self-center"):
            ui.button(
                "Profile",
                icon="badge",
                on_click=lambda: _profile_dialog(
                    service,
                    item.talent_id,
                    item.name,
                    editable=True,
                    note=item.note,
                    on_saved=refresh,
                ),
            ).props("outline dense no-caps").classes("bg-white pl-1 pr-3").mark(
                f"profile:{item.talent_id}"
            )
            resume_button(
                item.talent_id,
                item.name,
                item.has_resume,
                f"resume:{item.talent_id}",
                service=service,
                native=native,
                on_change=refresh,
            )


def talent_page(service: AppService, native: bool) -> None:
    try:
        sheet_url = service.links().get("intake_sheet", "") if hasattr(service, "links") else ""
    except Exception:  # noqa: BLE001 (the button is only a convenience)
        sheet_url = ""
    shown: list[str] = []  # talent IDs in on-screen order, fixed when the page opens
    opened: set[str] = set()
    query = {"text": "", "filter": "all", "sort": "name"}
    new_people = service.new_items().people  # what arrived since this screen was last opened
    service.mark_seen("talent")

    @ui.refreshable
    def body() -> None:
        everyone = service.talent_overview()
        if not shown:  # a new sort order (or the first draw) sets the order; then no jumping
            everyone = sort_talent(everyone, query["sort"])
        place = {talent_id: i for i, talent_id in enumerate(shown)}
        everyone.sort(key=lambda t: place.get(t.talent_id, len(place)))
        shown[:] = [t.talent_id for t in everyone]
        groups = [talent_group(t) for t in everyone]
        now, later, out = (groups.count(g) for g in ("now", "later", "left_out"))
        parts = [plural(len(everyone), "contractor"), f"{now} available now"]
        if later:
            parts.append(f"{later} booked or free later")
        if out:
            parts.append(f"{out} left out of matching")
        ui.label(" · ".join(parts)).classes("text-sm text-grey-8").mark("talent-header")
        words = query["text"].casefold().split()
        matching = [
            t
            for t in everyone
            if all(w in f"{t.name} {t.headline or ''}".casefold() for w in words)
            and talent_in_filter(t, query["filter"])
        ]
        if not everyone:
            ui.label("No contractors yet. Add your contractor list on Home.")
        elif not matching:
            ui.label("Nobody matches the search.").classes("text-grey-7")
        for item in matching:
            _talent_card(
                service, item, body.refresh, opened, sheet_url, native, item.talent_id in new_people
            )

    def search(e: ValueChangeEventArguments) -> None:
        query["text"] = e.value or ""
        body.refresh()

    def pick_filter(name: str) -> None:
        query["filter"] = name
        filter_button.text = "" if name == "all" else TALENT_FILTERS[name]
        filter_button.props(f"color={'primary' if name != 'all' else 'grey-8'}")
        body.refresh()

    def pick_sort(name: str) -> None:
        query["sort"] = name
        sort_button.text = TALENT_SORTS[name]
        shown.clear()
        body.refresh()

    # A smaller "work" icon on the "Approved for jobs" caret (user request 2026-11-09).
    ui.add_css(
        ".talent-jobs .q-item__section--avatar { min-width: 26px; }"
        ".talent-jobs .q-item__section--avatar .q-icon { font-size: 16px; }"
    )
    with ui.column().classes(f"{PAGE} gap-3"):
        with ui.row().classes("items-center gap-1"):
            ui.label("Talent").classes("text-h5")
            help_icon(
                "Turn off Include in matching when a contractor is not looking for a "
                "project (check with them first): they are no longer sent to Gemini, and their "
                "open recommendations make room for others. The switch saves as soon as you "
                "flip it; a hire never changes it. The coloured tag (Available now, Booked "
                "until...) is what the contractor's own profile says about their time. "
                "Profile opens the contractor's details: "
                "Edit changes them and Save stores them with your note. A later contractor "
                "list import with other values replaces your edits, and a new or changed "
                "profile in an import sets the switch from the contractor's own answer."
            )
        with ui.row().classes("w-full items-center gap-3"):
            ui.input(placeholder="Search by name or headline", on_change=search).props(
                "dense outlined clearable bg-color=white"
            ).classes("w-full max-w-md").mark("talent-search")
            with (
                ui.button(icon="filter_list")
                .props("outline dense no-caps icon-right=arrow_drop_down color=grey-8")
                .classes("bg-white pl-2")
                .mark("talent-filter")
                .tooltip("Filter contractors") as filter_button,
                ui.menu(),
            ):
                for name, text in TALENT_FILTERS.items():
                    ui.menu_item(text, on_click=lambda n=name: pick_filter(n)).mark(
                        f"talent-filter:{name}"
                    )
            with (
                ui.button(TALENT_SORTS["name"], icon="sort")
                .props("outline dense no-caps icon-right=arrow_drop_down color=grey-8")
                .classes("bg-white pl-2")
                .mark("talent-sort")
                .tooltip("Sort contractors") as sort_button,
                ui.menu(),
            ):
                for name, text in TALENT_SORTS.items():
                    ui.menu_item(text, on_click=lambda n=name: pick_sort(n)).mark(
                        f"talent-sort:{name}"
                    )
        body()


# ---- screen: settings ----


def settings_page(service: AppService, native: bool) -> None:
    ui.add_css(
        ".dg-adv .q-item { border-radius: 1.25rem; background: #FBFAFE; min-height: 52px;"
        " border: 2px solid #E4DFF3; }"
        ".dg-adv .q-item__label { font-weight: 600; color: #4B3499; }"
        ".dg-adv .q-item__section--avatar { color: #593B9D; }"
    )
    with ui.column().classes(f"{PAGE_NARROW} gap-4"):
        ui.label("Settings").classes("text-h5")
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-1"):
                ui.label("Gemini key").classes("text-h6")
                help_icon(KEY_HELP)
            state = ui.label(
                "A key is saved." if service.has_key() else "No key saved yet."
            ).classes("text-sm")
            key = (
                ui.input("Paste a new key", password=True, password_toggle_button=True)
                .classes("w-full")
                .mark("key-input")
            )

            def save_key() -> None:
                try:
                    service.save_key(key.value or "")
                except AppError as exc:
                    ui.notify(str(exc), type="warning")
                    return
                key.value = ""
                state.text = "A key is saved."
                ui.notify("Key saved.", type="positive")

            ui.button("Save key", on_click=save_key)

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-1"):
                ui.label("Your name").classes("text-h6")
                help_icon(
                    "Saved with each approve or reject decision, and used to sign the emails."
                )
            name = ui.input("Reviewer", value=service.reviewer()).classes("w-full")

            def save_name() -> None:
                try:
                    service.save_reviewer(name.value or "")
                except AppError as exc:
                    ui.notify(str(exc), type="warning")
                    return
                ui.notify("Saved.", type="positive")

            ui.button("Save name", on_click=save_name)

        if hasattr(service, "sync_link_hint"):
            link_card(service)

        folders_and_links_card(service, native)

        # Anything technical stays folded away until someone wants it.
        with (
            ui.expansion("Advanced", icon="tune")
            .props("dense")
            .classes("dg-adv w-full")
            .mark("settings-advanced"),
            ui.column().classes("w-full gap-4 pt-2"),
        ):
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-1"):
                    ui.label("Data folder").classes("text-h6")
                    help_icon(
                        "Jobs, contractors, results and exports live here. Contractor data "
                        "is personal: keep this computer password-protected."
                    )
                ui.label(str(service.data_dir)).classes("text-sm font-mono")
                if native:
                    ui.button(
                        "Show in folder", on_click=lambda: open_in_file_manager(service.data_dir)
                    ).props("outline")
            backup_card(service, native)


def folders_and_links_card(service: AppService, native: bool) -> None:
    """The remembered Contractors folder and jobs folder (read again every time you match and
    when the app opens), and the three links shown as buttons on Home."""
    if not hasattr(service, "links"):
        return
    with ui.card().classes("w-full gap-2").mark("folders-card"):
        with ui.row().classes("items-center gap-1"):
            ui.label("Folders and links").classes("text-h6")
            help_icon(
                "The app remembers your Contractors folder and your jobs folder. It reads "
                "them again when it opens and every time you click Find matches, so new "
                "people and new jobs show up by themselves. The three links become buttons "
                "on Home."
            )

        def folder_row(label: str, current: Path | None, marker: str, save, forget) -> None:  # noqa: ANN001
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                field = (
                    ui.input(label, value=str(current) if current else "")
                    .props('outlined dense placeholder="Not set"')
                    .classes("flex-1")
                    .mark(marker)
                )

                async def choose() -> None:
                    window = nicegui_app.native.main_window
                    if window is None:
                        ui.notify("The folder dialog is not available.", type="negative")
                        return
                    import webview  # noqa: PLC0415 (only in the desktop app)

                    chosen = await window.create_file_dialog(webview.FileDialog.FOLDER)
                    if chosen:
                        field.value = str(chosen[0])
                        apply()

                def apply() -> None:
                    text = (field.value or "").strip()
                    if not text:
                        forget()
                        ui.notify(f"{label}: forgotten.", type="positive")
                        return
                    try:
                        save(Path(text))
                    except AppError as exc:
                        failure_slot.clear()
                        with failure_slot:
                            failure_card(str(exc), apply, what=f"{label} did not work.")
                        return
                    failure_slot.clear()
                    ui.notify(f"{label}: remembered.", type="positive")

                if native:
                    ui.button("Browse…", icon="folder_open", on_click=choose).props(
                        "outline dense no-caps"
                    ).classes("bg-white").mark(f"{marker}-browse")
                ui.button("Save", on_click=apply).props("outline dense no-caps").classes(
                    "bg-white"
                ).mark(f"{marker}-save")

        failure_slot = ui.column().classes("w-full")
        folder_row(
            "Contractors folder",
            service.contractors_folder(),
            "setting-contractors-folder",
            service.pick_contractor_folder,
            service.forget_contractors_folder,
        )
        folder_row(
            "Jobs folder",
            service.jobs_folder(),
            "setting-jobs-folder",
            service.set_jobs_folder,
            lambda: service.set_jobs_folder(None),
        )
        links = service.links()
        fields: dict[str, ui.input] = {}
        for key, label in (
            ("intake_form", "Contractor form link"),
            ("intake_sheet", "Contractor Sheet link"),
            ("job_collector_sheet", "Jobs Sheet link"),
        ):
            fields[key] = (
                ui.input(label, value=links.get(key, ""))
                .props('outlined dense placeholder="https://…"')
                .classes("w-full")
                .mark(f"setting-link:{key}")
            )

        def save_links() -> None:
            try:
                for key, field in fields.items():
                    service.save_link(key, field.value or "")
            except AppError as exc:
                ui.notify(str(exc), type="warning", multi_line=True)
                return
            ui.notify("Links saved.", type="positive")

        ui.button("Save links", icon="save", on_click=save_links).props("outline no-caps").mark(
            "setting-links-save"
        )


# ---- export and import of all data (user decisions 2026-11-10) ----


def _size(n: int) -> str:
    return f"{n / 1024**2:.1f} MB" if n >= 1024**2 else f"{max(n, 1) / 1024:.0f} KB"


def backup_card(service: AppService, native: bool) -> None:
    with ui.card().classes("w-full gap-2"):
        with ui.row().classes("items-center gap-1"):
            ui.label("Back up or move the app").classes("text-h6")
            help_icon(
                "Export saves all jobs, contractors, résumés, decisions and Gemini's saved "
                "answers in one password-protected file. Import replaces this app's data with "
                "such a file, for a new computer, a new person or after a reset. The Gemini "
                "key and your name are never in the file: enter them again after an import."
            )
        ui.label("Save everything to one protected file, or load one.").classes(
            "text-sm text-grey-8"
        )
        with ui.row().classes("gap-2"):
            ui.button(
                "Export all data", icon="archive", on_click=lambda: export_dialog(service, native)
            ).props("outline no-caps").mark("export-data")
            ui.button(
                "Import a backup", icon="unarchive", on_click=lambda: import_dialog(service, native)
            ).props("outline no-caps").mark("import-data")


def export_dialog(service: AppService, native: bool) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[480px] max-w-full gap-2"):
        ui.label("Export all data").classes("text-h6")
        ui.label(
            "Choose a password for the file. Without it the backup cannot be opened, and it "
            "cannot be recovered: keep it somewhere safe, apart from the file."
        ).classes("text-sm text-grey-8")
        first = (
            ui.input("Password", password=True, password_toggle_button=True)
            .props('outlined dense hint="At least 10 characters."')
            .classes("w-full")
            .mark("export-password")
        )
        second = (
            ui.input("Password again", password=True)
            .props("outlined dense")
            .classes("w-full")
            .mark("export-password-again")
        )

        async def go() -> None:
            if first.value != second.value:
                ui.notify("The two passwords differ.", type="warning")
                return
            dest: Path | None = None
            if native:
                import webview  # only in the desktop app

                window = nicegui_app.native.main_window
                if window is None:
                    ui.notify("The save dialog is not available.", type="negative")
                    return
                chosen = await window.create_file_dialog(
                    webview.FileDialog.SAVE, save_filename=backup_name(datetime.now(UTC))
                )
                if not chosen:
                    return
                dest = Path(chosen if isinstance(chosen, str) else chosen[0])
            try:
                info, path = await run.io_bound(service.export_data, str(first.value or ""), dest)
            except AppError as exc:
                ui.notify(str(exc), type="warning", multi_line=True)
                return
            dialog.close()
            ui.notify(
                f"Exported {plural(info.jobs, 'job')} and {plural(info.contractors, 'contractor')} "
                f"({_size(info.size)}).",
                type="positive",
            )
            if not native:
                ui.download(path, path.name)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Export", icon="archive", on_click=go).props("no-caps").mark("export-confirm")
    dialog.open()


def import_dialog(service: AppService, native: bool) -> None:
    picked: dict[str, Path] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[520px] max-w-full gap-2"):
        ui.label("Import a backup").classes("text-h6")
        ui.label(
            "Pick a backup file made with Export, and type its password. It is checked "
            "completely before anything changes."
        ).classes("text-sm text-grey-8")
        chooser, note = pick_row("Choose backup…", "unarchive", "import-file")
        password = (
            ui.input("Password", password=True, password_toggle_button=True)
            .props("outlined dense")
            .classes("w-full")
            .mark("import-password")
        )

        if native:

            async def browse() -> None:
                window = nicegui_app.native.main_window
                if window is None:
                    ui.notify("The file dialog is not available.", type="negative")
                    return
                chosen = await window.create_file_dialog(file_types=("Backup (*.zip)",))
                if chosen:
                    picked["path"] = Path(chosen[0])
                    note.text = str(picked["path"])

            chooser.on_click(browse)
        else:

            async def uploaded(e: UploadEventArguments) -> None:
                dest = service.data_dir / "backups" / "uploads" / e.file.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(await e.file.read())
                picked["path"] = dest
                note.text = e.file.name

            upload = (
                ui.upload(on_upload=uploaded, auto_upload=True)
                .props('accept=".zip"')
                .classes("hidden")
                .mark("import-upload")
            )
            chooser.on_click(lambda: upload.run_method("pickFiles"))

        async def check() -> None:
            path = picked.get("path")
            if path is None:
                ui.notify("Choose a backup file first.", type="warning")
                return
            try:
                info = await run.io_bound(service.check_import, path, str(password.value or ""))
            except AppError as exc:
                ui.notify(str(exc), type="warning", multi_line=True)
                return
            dialog.close()
            confirm_import(service, info)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Check backup", icon="fact_check", on_click=check).props("no-caps").mark(
                "import-check"
            )
    dialog.open()


def confirm_import(service: AppService, info: BackupInfo) -> None:
    jobs, contractors = service.data_counts()
    with ui.dialog().props("persistent") as dialog, ui.card().classes("max-w-lg gap-2"):
        ui.label("Replace this app's data?").classes("text-h6")
        ui.label(
            f"Now: {jobs} job(s) and {contractors} contractor(s). The backup from "
            f"{plain_when(info.created_at)} (app {info.app_version}): {info.jobs} job(s), "
            f"{info.contractors} contractor(s), {info.files} file(s), {_size(info.size)}."
        ).classes("text-sm")
        ui.label(
            "The backup passed every check. Your current data is not deleted: it is moved to "
            "the backups folder (data/backups/before-import-…), so the import can be undone."
        ).classes("text-sm text-grey-8")

        def cancel() -> None:
            service.discard_import()
            dialog.close()

        async def go() -> None:
            try:
                kept = await run.io_bound(service.import_checked)
            except AppError as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
                return
            dialog.close()
            ui.notify(
                f"Imported. The previous data is kept in {kept.name}.",
                type="positive",
                multi_line=True,
            )
            ui.navigate.to("/settings")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=cancel).props("flat no-caps").mark("import-cancel")
            ui.button("Replace data", icon="unarchive", on_click=go).props(
                "unelevated no-caps color=red-9 text-color=white"
            ).mark("import-confirm")
    dialog.open()


# ---- the app ----


def _go(path: str) -> Callable[[], None]:
    return lambda: ui.navigate.to(path)


def build_root(service: AppService, *, native: bool) -> Callable[[], None]:
    def root() -> None:
        _serve_resumes(service)  # here, not once at start: the test harness resets routes
        service.note_app_opened()  # once per start: what is "new since last time" counts from here
        ui.page_title(APP_TITLE)
        ui.colors(primary=THEME_PRIMARY, secondary=THEME_ACCENT, accent=THEME_ACCENT)
        ui.add_css(APP_CSS)
        ui.add_head_html(FONT_LINK)
        ui.add_body_html(NAV_JS)
        ui.add_body_html('<div class="orbs"><i></i><i></i><i></i></div>')
        ui.query("body").style(f"background: {THEME_BACKGROUND}; background-attachment: fixed;")
        with ui.header().classes("items-center px-6 py-3 gap-1"):
            ui.html(WORDMARK_HTML, sanitize=False).on("click", _go("/")).mark("app-title")
            ui.space()
            run_indicator(service, native)
            for text, path in (
                ("Home", "/"),
                ("Results", "/results"),
                ("Jobs", "/jobs"),
                ("Talent", "/talent"),
                ("Settings", "/settings"),
            ):
                # color=None: a flat button's text otherwise takes the primary colour, the
                # header's own purple, and the unselected items disappear.
                ui.button(text, on_click=_go(path), color=None).props(
                    f'flat no-caps data-path="{path}"'
                ).classes("nav-btn")
        # NiceGUI's page wrapper is a left-aligned column sized to its content: make it full
        # width and centre each screen in it (the header is separate and keeps full width).
        ui.sub_pages(
            {
                "/": lambda: home_page(service, native),
                "/results": lambda: results_page(service, native),
                "/review": lambda: review_page(service, native),
                "/jobs": lambda: jobs_page(service, native),
                "/talent": lambda: talent_page(service, native),
                "/settings": lambda: settings_page(service, native),
            }
        ).classes("w-full items-center px-3 sm:px-6 py-5")

    return root
