"""Everything the desktop app does, without any UI code (so it is tested directly).

The screens (app/ui.py) only call this class. It works on one Settings object whose data
paths point at the app's data root, and on the app's .env file for the Gemini key and the
reviewer name. Nothing here prints or logs contractor names or the key.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout
from pydantic import BaseModel, ValidationError

from jobmatch import secrets_file, sync_client
from jobmatch.backup import (
    BackupError,
    BackupInfo,
    backup_name,
    check_backup,
    current_counts,
    export_data,
    replace_data,
)
from jobmatch.config import Settings
from jobmatch.llm.anonymize import build_roster
from jobmatch.llm.export import ExportResult, export_current
from jobmatch.llm.judge import judgments_dir, move_judgments, plan_jobs
from jobmatch.llm.matches import judged_job
from jobmatch.llm.payload import ACTIVE_STATUSES, is_active
from jobmatch.llm.provider import LLMProvider
from jobmatch.llm.rounds import latest_applications, latest_reviews, rank
from jobmatch.llm.trial import TrialResult
from jobmatch.llm.usage import RunCheck, UsageLedger
from jobmatch.pipeline import PIPELINE_LOCK_FILE, PipelineError, RunOnceReport, run_once
from jobmatch.schemas import (
    Application,
    ApplicationStatus,
    ContractorProfile,
    Decision,
    Job,
    JobAvailability,
    JobStatus,
    LlmMatch,
    LlmVerdict,
    ReasonCode,
    RemovedJob,
    Review,
    TalentAvailability,
    TalentNote,
    web_url_or_none,
)
from jobmatch.shortlists import (
    contractors_to_scan,
    is_available,
    latest_changes,
    latest_toggles,
    mark_changes,
    pair_states,
    sync_rounds,
    toggles,
)
from jobmatch.sources.contractor_sheet import ContractorImportRules, load_contractor_import
from jobmatch.sources.contractor_upsert import (
    ContractorFileError,
    _name_key,
    read_contractor_file,
    upsert_contractors,
)
from jobmatch.sources.job_csv import (
    FORM_MARK,
    JOB_CSV_SUFFIX,
    TEMPLATE_ROWS,
    JobCsvError,
    JobEntry,
    read_job_csv,
    write_job_csv,
)
from jobmatch.sources.resumes import (
    RESUME_SUFFIX,
    ZIP_SUFFIX,
    match_ids,
    read_contractor_folder,
    resumes_dir,
    store_resume,
    stored_resume,
    unpack_zips,
)
from jobmatch.sources.saved_files import SAVED_SUFFIXES
from jobmatch.storage.csv_store import CsvStoreError, to_cell
from jobmatch.storage.files import atomic_write_text
from jobmatch.storage.loader import create_loader
from jobmatch.storage.repositories import DataLoader

REVIEWER_ENV = "JOBMATCH_REVIEWER"
HIRE_REVIEWER = "hire"  # availability rows hires wrote before 2026-11-18 (no longer written)
HIRE_UNDONE_REVIEWER = "hire undone"
DEFAULT_REVIEWER = "reviewer"
JOB_SUFFIXES = (".txt", *SAVED_SUFFIXES, JOB_CSV_SUFFIX)
CONTRACTOR_SUFFIXES = (".xlsx", ".csv")
UPLOAD_SUFFIXES = (*CONTRACTOR_SUFFIXES, RESUME_SUFFIX, ZIP_SUFFIX)  # browser mode
# Remembered settings, saved in the app's .env beside the key (so a data import keeps them).
CONTRACTORS_FOLDER_ENV = "JOBMATCH_CONTRACTORS_FOLDER"
JOBS_FOLDER_ENV = "JOBMATCH_JOBS_FOLDER"
LINK_NAMES = ("intake_form", "intake_sheet", "job_collector_sheet")
STATE_FILE = "app_state.json"  # beside the .env: jobs files already copied, last import times
# "Get latest": the do good link (a secret, kept in the .env like the Gemini key) and what the
# download client remembers. Dev flag: allow plain http to 127.0.0.1 (a local fake server).
SYNC_LINK_ENV = "JOBMATCH_SYNC_LINK"
SYNC_DEV_ENV = "JOBMATCH_DEV_ALLOW_LOCAL_SYNC"
SYNC_STATE_FILE = "sync_state.json"
SYNCED_DIR = "synced"  # beside the .env: synced/contractors and synced/jobs
UTF8_MESSAGE = (
    "The contractor file is not saved as UTF-8. Save the file as CSV UTF-8 and try again."
)
MOJIBAKE = re.compile(  # UTF-8 text that was read as Windows-1252: "\u00c3\u2030" for "\u00c9"
    "[\u00c2\u00c3]["
    + re.escape(bytes(range(0x80, 0xC0)).decode("cp1252", "ignore"))
    + "]|\u00e2\u20ac"
)

JobKind = Literal["links", "manual"]
JobOutcome = Literal["fits", "check_partial", "no_match", "not_judged"]


class AppError(Exception):
    """A problem to show to the person, in plain words."""


class PendingEntry(BaseModel):
    """A job entered with the form, saved and waiting for the next Ingest / Find matches."""

    name: str  # its file in data/inbox/manual/
    title: str
    company: str


class AddedJobsFile(BaseModel):
    kind: JobKind  # links: one URL per line; manual: a pasted or saved posting, jobs CSV
    dest: Path
    jobs: int | None = None  # a jobs CSV: rows that will go in
    problems: list[str] = []  # a jobs CSV: rows that will not, and why
    links: int | None = None  # number of URLs, for a links file


class ContractorFileInfo(BaseModel):
    """What the next run will load. Shown on screen only (`unmatched` file names may hold
    a person's name)."""

    path: Path | None  # the contractor file, if one is picked
    contractors: int
    resumes: int = 0  # PDFs named by a known talent ID
    unmatched: list[str] = []  # PDF names that are not a talent ID
    missing_resumes: list[str] = []  # names of people in the file with no PDF (picked or stored)
    same_name: list[str] = []  # names in the file that belong to more than one talent ID


class MatchView(BaseModel):
    match: LlmMatch
    name: str | None
    headline: str | None
    decision: Review | None  # latest decision, if any
    unavailable: bool = False  # not available for new projects (Talent screen)
    has_resume: bool = False  # a résumé is stored for them (Résumé button)


class JobResult(BaseModel):
    job: Job
    outcome: JobOutcome
    matches: list[MatchView]
    rejected: list[MatchView] = []  # the reviewer's rejections, behind "Show rejected"


# The Jobs screen's four states:
#   matched  (1, green)  scanned, someone recommended (reviewed or not, hire in progress or not)
#   no_match (2, red)    scanned, nobody recommended; stays available for later runs
#   waiting  (3, yellow) contractors still to scan (a new or reopened job, new contractors)
#   inactive (4, grey)   marked completed or unavailable: never sent to Gemini
JobState = Literal["matched", "no_match", "waiting", "inactive"]
JobAction = Literal["completed", "unavailable", "reopen"]


class Candidate(BaseModel):
    """An approved contractor in a job's table on the Jobs screen."""

    talent_id: str
    name: str | None
    headline: str | None
    match: LlmMatch | None  # their newest row for the job (verdict, score)
    status: ApplicationStatus  # latest; not_referred when never set
    removed: bool  # application rejected or ghosted: out of consideration (Undo restores)


FreeState = Literal["now", "later", "booked", "unknown"]
_ISO_DATE = r"(\d{4}-\d{2}-\d{2})"


def free_state_of(text: str | None, today: date | None = None) -> tuple[FreeState, date | None]:
    """The real-world availability in a profile's own words ("Available now", "Available from
    2026-12-02", "Booked until 2027-03-18"): free now, free later (date), booked (until date),
    or unknown when the text says nothing usable. A date that has passed means free now."""
    low = (text or "").casefold().strip()
    if not low:
        return "unknown", None
    today = today or datetime.now(UTC).date()
    found = re.search(_ISO_DATE, low)
    try:
        when = date.fromisoformat(found.group(1)) if found else None
    except ValueError:
        when = None
    if low.startswith("booked"):
        if when is not None and when <= today:
            return "now", None
        return "booked", when
    if when is not None and ("from" in low or "after" in low or "starting" in low):
        return ("now", None) if when <= today else ("later", when)
    if "now" in low or "immediate" in low:
        return "now", None
    return "unknown", None


class TalentJob(BaseModel):
    """One job a contractor was approved for, on the Talent screen (read-only)."""

    job_id: str
    title: str
    company: str | None
    location: str | None
    status: ApplicationStatus
    removed: bool  # application rejected or ghosted
    job_open: bool  # False: the job is completed or unavailable (or deleted)
    deleted: bool = False  # the job was deleted from the app (Jobs screen)


class TalentOverview(BaseModel):
    """One contractor on the Talent screen. Shown on screen only (personal data)."""

    talent_id: str
    name: str
    headline: str | None
    available: bool  # what matching uses: the reviewer's toggle, else the profile
    profile_open: bool  # the contractor's own answer (profile `contract`)
    toggled: TalentAvailability | None  # the reviewer's latest toggle, if any
    jobs: list[TalentJob] = []  # approved for, best known first
    has_resume: bool = False
    note: str | None = None  # the reviewer's latest note (Profile pop-up), read-only here
    availability: str | None = None  # the profile's own words, e.g. "From 2026-12-01"
    profile_updated: date | None = None  # when the profile was last updated
    same_name_ids: list[str] = []  # the OTHER contractors with the same name (maybe a duplicate)
    free_state: FreeState = "unknown"  # real-world availability read from `availability`
    free_date: date | None = None  # "later": when they are free; "booked": when the booking ends

    @property
    def available_now(self) -> bool:
        """In matching AND free now (or nothing says otherwise): who Josh can pitch today."""
        return self.available and self.free_state in ("now", "unknown")


class ProfileSaved(BaseModel):
    """What a Save in the Profile pop-up did."""

    profile_changed: bool  # the contractor's row in the contractor list was rewritten
    rescan: bool  # what Gemini sees changed: matched again on the next run
    note_changed: bool


class JobsFolderImport(BaseModel):
    new_files: int = 0  # job files copied to the inbox this time
    problems: list[str] = []  # files that could not be added, with the reason


class SyncSummary(BaseModel):
    """What opening the app found in the remembered folders (sync_on_start). Shown on screen
    only (`missing_resumes` holds names)."""

    contractors_folder: Path | None = None
    jobs_folder: Path | None = None
    people_added: int = 0
    people_updated: int = 0
    missing_resumes: list[str] = []
    new_jobs: int = 0  # jobs stored by this pass
    new_job_files: int = 0  # files copied from the jobs folder
    unreadable_files: list[str] = []  # job files that could not be read, each with its reason
    jobs_waiting: int = 0  # jobs with no match yet: the N of "Match N jobs now?"
    problems: list[str] = []
    ran: bool = False  # an ingest pass (no Gemini) was needed and done


class LinkTest(BaseModel):
    """The answer of "Test link": kind "ok", or a sync_client problem kind ("bad_link",
    "offline", "busy", ...)."""

    kind: str
    people: int = 0
    jobs: int | None = None  # None = the jobs part is not switched on for this link


class PartStatus(BaseModel):
    from_link: bool = False  # this part is read from the downloaded copy
    checked_at: datetime | None = None
    new: int = 0  # people / jobs the last check brought


class LatestStatus(BaseModel):
    """What the Contractors and Jobs rows say about the do good link."""

    has_link: bool = False
    hint: str = ""  # "…a1b2"
    contractors: PartStatus = PartStatus()
    jobs: PartStatus = PartStatus()
    last_ok_at: datetime | None = None
    problem: str = ""  # the last check in this run of the app could not finish


class LatestOutcome(BaseModel):
    summary: SyncSummary | None = None  # what the existing folder import found
    problem: str = ""  # "", or a sync_client problem kind (offline, bad_link, busy, ...)
    downloaded: bool = False


class LeftOutJob(BaseModel):
    """A job the import stored but the app does not list (not a contract job, not in Canada,
    a copy of another job, ...), with the reason in plain words."""

    title: str
    company: str | None = None
    reason: str


class HomeSummary(BaseModel):
    contractors: int
    jobs: int  # the jobs the Jobs screen lists (the one number every screen shows)
    jobs_left_out: int = 0  # stored by the import but not listed (see jobs_left_out())
    jobs_waiting: int  # no match yet
    matches_waiting: int  # recommended on Results, no decision yet
    last_run_at: datetime | None = None
    last_contractors_at: datetime | None = None  # a contractor file was last loaded
    last_jobs_at: datetime | None = None  # jobs were last imported
    contractors_folder: Path | None = None
    jobs_folder: Path | None = None


class NewItems(BaseModel):
    """What arrived since the person last looked: the "+3 new" badges on Home and the "New"
    tags on Jobs and Talent (job IDs and talent IDs)."""

    people: set[str] = set()
    jobs: set[str] = set()


class PlannedJob(BaseModel):
    """A job the running search is about to send to Gemini, in the order it is sent."""

    job_id: str
    title: str
    company: str | None = None


class FinishedJob(BaseModel):
    """A job whose Gemini answer is saved (shown under the progress bar while a search runs).
    Shown on screen only (`best_name` is a person)."""

    job_id: str
    title: str
    matches: int  # people kept for it (0: nobody fits)
    best_name: str | None = None
    best_score: int | None = None


class JobOverview(BaseModel):
    job: Job
    state: JobState
    summary: str  # "3 matches · best score 92", "best score 58", "no match", "" (not scanned)
    candidates: list[Candidate] = []  # approved for this job, best first
    new_people: int = 0  # contractors not yet checked for this job (0 when it is up to date)


class ReviewFacts(BaseModel):
    """The few facts Review mode shows about a contractor, as plain text (personal data: on
    screen only)."""

    location: str | None = None
    experience: str | None = None  # "8 years · Senior"
    availability: str | None = None  # the profile's own words
    rate: str | None = None
    languages: str | None = None


class ReviewItem(BaseModel):
    """One undecided match in Review mode, with its job and the job's other shown matches
    (for the email pop-up)."""

    job: Job
    view: MatchView
    others: list[MatchView]
    facts: ReviewFacts
    position: int  # 1-based place among this job's undecided matches
    of: int  # how many undecided matches this job has


LEFT_OUT_REASONS = {
    "not_canada": "It is not a job in Canada.",
    "not_contract": "It is not a contract job.",
    "stale": "It was posted too long ago.",
    "unsupported_language": "It is not written in English or French.",
}


def left_out_reason(job: Job) -> str:
    """Why the import left a job off the list, in one plain sentence."""
    if job.status is JobStatus.NEEDS_DETAILS:
        return "The posting has too few details to read."
    reason = (job.filter_reason or "").split(":", 1)[0]
    if reason == "duplicate":
        return "It is the same job as one already on the list."
    return LEFT_OUT_REASONS.get(reason, "It did not fit the rules for contract jobs.")


def job_summary(job: Job, matches: list[LlmMatch] | None) -> str:
    """The matching summary line on the Jobs screen. `matches` is the current shortlist,
    None when the job is not analyzed with the current contractor list."""
    if job.availability is JobAvailability.COMPLETED:
        return "completed"
    if job.availability is JobAvailability.UNAVAILABLE:
        return "unavailable"
    if matches is None:
        return ""  # the screen's state label already says "Not scanned yet"
    if not matches:
        return "no match"
    scores = [m.fit_score for m in matches if m.fit_score is not None]
    best = f"best score {max(scores)}" if scores else "no score"
    fits = sum(1 for m in matches if m.verdict is LlmVerdict.FIT)
    if not fits:
        return best  # the single best partial
    return f"{fits} match{'es' if fits != 1 else ''} · {best}"


class Quota(BaseModel):
    requests: int
    rpd: int
    tokens: int


def _review_facts(profile: ContractorProfile | None) -> ReviewFacts:
    if profile is None:
        return ReviewFacts()
    bits = []
    if profile.years_experience is not None:
        bits.append(f"{profile.years_experience:g} years")
    if profile.seniority:
        bits.append(profile.seniority.title() if profile.seniority.islower() else profile.seniority)
    rate = profile.rate_expectation.strip()
    if rate.replace(".", "", 1).isdigit():
        rate = f"${float(rate):,.0f}/hour"
    return ReviewFacts(
        location=profile.location,
        experience=" · ".join(bits) or None,
        availability=profile.availability,
        rate=rate or None,
        languages=" · ".join(
            {"en": "English", "fr": "French"}.get(x.lower(), x.title()) for x in profile.languages
        )
        or None,
    )


def _current_decision(review: Review | None) -> Review | None:
    """The latest decision, or None when there is none or it was reset."""
    return None if review is None or review.decision is Decision.CLEARED else review


def classify_jobs_file(name: str, data: bytes) -> JobKind:
    """links when every non-comment line of a .txt file starts with an http(s) URL;
    manual for anything else (a pasted posting, or a saved .html / .pdf page)."""
    suffix = Path(name).suffix.lower()
    if suffix not in JOB_SUFFIXES:
        raise AppError(f"{name}: choose a jobs .csv, or a .txt, .html or .pdf file")
    if suffix != ".txt":
        return "manual"
    lines = [
        ln.strip()
        for ln in data.decode("utf-8-sig", errors="replace").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if lines and all(ln.split()[0].lower().startswith(("http://", "https://")) for ln in lines):
        return "links"
    return "manual"


def _entry_problem(exc: ValueError) -> str:
    """A form or row problem in plain words: "job_title: is empty" -> "Job title is empty"."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    parts = []
    for e in errors(include_input=False, include_url=False):
        field = ".".join(str(p) for p in e["loc"]).replace("_", " ").capitalize()
        parts.append(f"{field}: {e['msg'].removeprefix('Value error, ')}")
    return "; ".join(parts)


def _encoding_damaged(path: Path) -> bool:
    """True when a CSV is not UTF-8, or its accents are already damaged (replacement
    characters, or UTF-8 read as Windows-1252)."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        return True
    return "\ufffd" in text or bool(MOJIBAKE.search(text))


def _stamped(folder: Path, name: str, now: datetime) -> Path:
    """A new file name in `folder` that never overwrites one already there."""
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{now:%Y%m%dT%H%M%SZ}-{Path(name).name}"
    dest, n = folder / base, 1
    while dest.exists():
        n += 1
        dest = folder / f"{Path(base).stem}-{n}{Path(base).suffix}"
    return dest


class AppService:
    def __init__(
        self,
        settings: Settings,
        env_path: Path,
        *,
        provider_factory: Callable[[], LLMProvider] | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        if settings.llm is None:
            raise AppError("settings.yaml has no llm section")
        self.settings = settings
        self.llm = settings.llm
        self.env_path = env_path
        self._provider_factory = provider_factory
        self._environ = os.environ if environ is None else environ
        self.contractor_file: Path | None = None  # picked, loaded on the next run
        self.resumes: dict[str, Path] = {}  # picked with it: {file stem: PDF}
        self._picked_ids: list[str] = []  # talent IDs in the picked file
        self._picked_people: dict[str, str] = {}  # talent ID -> name, same file
        self._unzipped: Path | None = None  # temp folder of a picked zip, deleted after use
        self._unpacked: Path | None = None  # a checked backup, waiting for confirmation
        self._open_noted = False  # this start of the app is remembered (note_app_opened)
        self._previous_open: datetime | None = None  # when the app was opened the time before
        self._latest_lock = threading.Lock()  # one "Get latest" at a time
        self._latest_problem = ""  # what went wrong in the last "Get latest" of this run
        self.sync_sleep: Callable[[float], None] = time.sleep  # a test can skip the waiting

    # ---- paths and stores ----

    @property
    def data_dir(self) -> Path:
        return self.settings.paths.data_dir

    def _loader(self) -> DataLoader:
        return create_loader(self.settings)

    # ---- settings: key and reviewer ----

    def has_key(self) -> bool:
        return bool(self._environ.get(self.llm.api_key_env, "").strip())

    def needs_key(self) -> bool:
        """Find matches cannot start: there is no key and no other way to reach Gemini."""
        return self._provider_factory is None and not self.has_key()

    def save_key(self, value: str) -> None:
        value = value.strip()
        if not value:
            raise AppError("The key is empty.")
        secrets_file.set_value(self.env_path, self.llm.api_key_env, value)
        self._environ[self.llm.api_key_env] = value

    def reviewer(self) -> str:
        return self._environ.get(REVIEWER_ENV, "").strip() or DEFAULT_REVIEWER

    def save_reviewer(self, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise AppError("The reviewer name is empty.")
        secrets_file.set_value(self.env_path, REVIEWER_ENV, name)
        self._environ[REVIEWER_ENV] = name

    # ---- inputs ----

    def add_jobs_file(self, name: str, data: bytes, now: datetime | None = None) -> AddedJobsFile:
        """Copy a picked jobs file into data/inbox/links or data/inbox/manual (never
        overwriting); the next run imports it."""
        if not data.strip():
            raise AppError(f"{name} is empty.")
        kind = classify_jobs_file(name, data)
        folder = self.data_dir / "inbox" / kind
        dest = _stamped(folder, name, now or datetime.now(UTC))
        dest.write_bytes(data)
        if Path(name).suffix.lower() == JOB_CSV_SUFFIX:
            try:
                rows = read_job_csv(
                    dest, now or datetime.now(UTC), full_time_hours=self._full_time_hours()
                )
            except JobCsvError as exc:
                dest.unlink()  # our own copy, just made: nothing to keep
                raise AppError(str(exc).replace(dest.name, name)) from exc
            problems = [f"Row {r.row}: {r.error}" for r in rows if r.error]
            return AddedJobsFile(
                kind=kind, dest=dest, jobs=sum(r.job is not None for r in rows), problems=problems
            )
        links = None
        if kind == "links":
            text = data.decode("utf-8-sig", errors="replace")
            links = sum(
                1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
            )
        return AddedJobsFile(kind=kind, dest=dest, links=links)

    # ---- export and import of all data (Settings; user decisions 2026-11-10) ----

    def _contractors_rel(self) -> Path:
        try:
            return self.settings.paths.contractors_csv.relative_to(self.data_dir)
        except ValueError:
            return Path("contractors") / "contractors.csv"

    def data_counts(self) -> tuple[int, int]:
        """(jobs, contractors) stored now."""
        return current_counts(self.data_dir, self._contractors_rel())

    def export_data(self, password: str, dest: Path | None = None) -> tuple[BackupInfo, Path]:
        """Write an encrypted backup of all data to `dest` (default: data/backups/exports/,
        which no export includes). The Gemini key and the reviewer name are never in it."""
        now = datetime.now(UTC)
        dest = dest or self.data_dir / "backups" / "exports" / backup_name(now)
        try:
            info = export_data(
                self.data_dir, dest, password, contractors_rel=self._contractors_rel(),
                lock_timeout=self.settings.storage.lock_timeout_seconds, now=now,
            )  # fmt: skip
        except BackupError as exc:
            raise AppError(str(exc)) from exc
        return info, dest

    def check_import(self, path: Path, password: str) -> BackupInfo:
        """Check a backup completely and unpack it beside the data (nothing replaced yet).
        import_checked() then puts it in place; discard_import() drops it."""
        self.discard_import()
        try:
            info, unpacked = check_backup(
                path, password, work_dir=self.data_dir / "backups",
                contractors_rel=self._contractors_rel(),
                lock_timeout=self.settings.storage.lock_timeout_seconds,
            )  # fmt: skip
        except BackupError as exc:
            raise AppError(str(exc)) from exc
        self._unpacked = unpacked
        return info

    def import_checked(self) -> Path:
        """Replace all data with the checked backup. The current data is moved (never
        deleted) into data/backups/before-import-<time>/; returns that folder."""
        if self._unpacked is None or not self._unpacked.is_dir():
            raise AppError("Check the backup again before importing it.")
        try:
            kept = replace_data(
                self.data_dir, self._unpacked,
                lock_timeout=self.settings.storage.lock_timeout_seconds, now=datetime.now(UTC),
            )  # fmt: skip
        except BackupError as exc:
            raise AppError(str(exc)) from exc
        self._unpacked = None
        self.clear_contractor_picks()
        # What the state file remembers belongs to the data that was just replaced.
        self._forget_state("jobs_seen", "contractors_sig", "inbox_failed")
        return kept

    def discard_import(self) -> None:
        if self._unpacked is not None:
            shutil.rmtree(self._unpacked, ignore_errors=True)  # our own unpacked copy
            self._unpacked = None

    # ---- jobs entered with the form (user decisions 2026-11-10) ----

    def _full_time_hours(self) -> float:
        return self.settings.normalize.full_time_hours_per_week

    def _manual_inbox(self) -> Path:
        return self.data_dir / "inbox" / "manual"

    def add_job_entry(self, fields: dict[str, str], now: datetime | None = None) -> JobEntry:
        """Save one job from the "Add a job by hand" form, as a one-row jobs CSV in the
        inbox; the next Ingest or Find matches stores it. Checked now (the link, the title
        and the date), so mistakes show in the form."""
        now = now or datetime.now(UTC)
        try:
            entry = JobEntry.from_cells(dict(fields))
            entry.to_job(now, full_time_hours=self._full_time_hours())
        except ValueError as exc:
            raise AppError(_entry_problem(exc)) from exc
        slug = re.sub(r"[^a-z0-9]+", "-", entry.job_title.lower()).strip("-")[:40] or "job"
        dest = _stamped(self._manual_inbox(), f"entered{FORM_MARK}{slug}.csv", now)
        write_job_csv(dest, [entry])
        return entry

    def pending_entries(self) -> list[PendingEntry]:
        """Jobs entered with the form that are not stored yet, oldest first."""
        folder = self._manual_inbox()
        if not folder.is_dir():
            return []
        out = []
        for path in sorted(folder.glob(f"*{FORM_MARK}*{JOB_CSV_SUFFIX}")):
            try:
                rows = read_job_csv(path, datetime.now(UTC))
            except JobCsvError:
                continue
            for r in rows:
                if r.job is not None:
                    out.append(
                        PendingEntry(name=path.name, title=r.job.title_raw,
                                     company=r.job.company_raw or "")
                    )  # fmt: skip
        return out

    def remove_entry(self, name: str) -> None:
        """Remove a form entry that is not stored yet (the screen asks first)."""
        if name not in {e.name for e in self.pending_entries()}:
            raise AppError("That entry is already stored or removed.")
        (self._manual_inbox() / name).unlink()

    def job_template(self, dest: Path | None = None) -> Path:
        """A fresh jobs CSV template (header and two example rows, English and French) at
        `dest`, chosen by the reviewer; default: data/templates/jobs-template.csv."""
        dest = dest or self.data_dir / "templates" / "jobs-template.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_job_csv(dest, TEMPLATE_ROWS)
        return dest

    def pick_contractor_folder(self, folder: Path) -> ContractorFileInfo:
        """The contractor folder (native picker): one .xlsx/.csv plus an optional resume/
        folder of <talent_id>.pdf (sources/resumes.py). A .zip of that folder works too.
        Checked now, loaded on the next run; the folder is remembered (contractors_folder)."""
        if folder.is_file() and folder.suffix.lower() == ZIP_SUFFIX:
            info = self.pick_contractor_zips([folder])  # forgets the old folder; saved below
        else:
            info = self._pick_dir(folder)
            self._drop_unzipped()
        self._save_env(CONTRACTORS_FOLDER_ENV, str(folder))
        return info

    def _pick_dir(self, folder: Path) -> ContractorFileInfo:
        try:
            picked = read_contractor_folder(folder)
        except ContractorFileError as exc:
            raise AppError(str(exc)) from exc
        self._check_contractor_file(picked.contractor_file)  # a failure keeps the earlier picks
        self.resumes = dict(picked.resumes)
        return self._picked()

    def pick_contractor_zips(self, zips: list[Path]) -> ContractorFileInfo:
        """One or several zips of the Contractors folder (Google Drive splits a big download
        into several), handled like the folder. Unpacked to a temp folder that is deleted when
        the picks are cleared or after the run. The zip is not remembered (a copy made from an
        upload is temporary): the caller remembers a real path, and any older remembered
        folder is forgotten so it can never load over this newer pick."""
        if not zips:
            raise AppError("No file was given.")
        previous, dest = self._unzipped, Path(tempfile.mkdtemp(prefix="contractors-"))
        try:
            info = self._pick_dir(unpack_zips(zips, dest))
        except ContractorFileError as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise AppError(str(exc)) from exc
        except AppError:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        self._unzipped = dest
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
        self.forget_contractors_folder()
        return info

    def _drop_unzipped(self) -> None:
        if self._unzipped is not None:
            shutil.rmtree(self._unzipped, ignore_errors=True)  # our own temp copy
            self._unzipped = None

    def save_upload(self, name: str, data: bytes) -> Path:
        """Browser mode: keep an uploaded file under data/contractors/uploads/."""
        path = _stamped(self.data_dir / "contractors" / "uploads", name, datetime.now(UTC))
        path.write_bytes(data)
        return path

    def pick_contractor_file(
        self, name: str, data: bytes | None = None, path: Path | None = None
    ) -> ContractorFileInfo:
        """One picked file: the contractor file, a résumé PDF named by talent ID (the
        browser upload takes the folder's files one by one), or a .zip of the folder. Checked
        now (so mistakes show at once) and kept for the next run. From the native picker,
        `path` is used where it is; an upload (`data`) is saved under
        data/contractors/uploads/ first."""
        suffix = Path(name).suffix.lower()
        if suffix not in UPLOAD_SUFFIXES:
            raise AppError(
                f"{name}: choose the contractor workbook (.xlsx) or a .csv file, and résumés "
                "as .pdf, or the Contractors folder as a .zip"
            )
        if path is None:
            if data is None:
                raise AppError("No file was given.")
            path = self.save_upload(name, data)
        if suffix == ZIP_SUFFIX:
            if data is None:  # a real path from the picker: remembered like a folder
                return self.pick_contractor_folder(path)
            return self.pick_contractor_zips([path])  # the saved upload copy is not remembered
        if suffix == RESUME_SUFFIX:
            self.resumes[Path(name).stem.strip()] = path
        else:
            self._check_contractor_file(path)
        # A file picked by hand is the newest import: an older remembered folder must not
        # load over it at the next search.
        self.forget_contractors_folder()
        return self._picked()

    def clear_contractor_picks(self) -> None:
        """Forget the picked contractor file and résumés (a new folder was picked)."""
        self.contractor_file = None
        self.resumes = {}
        self._picked_ids = []
        self._picked_people = {}
        self._drop_unzipped()

    def _check_contractor_file(self, path: Path) -> None:
        if path.suffix.lower() == ".csv" and _encoding_damaged(path):
            raise AppError(UTF8_MESSAGE)
        contractors = self._loader().contractors
        try:
            rows = read_contractor_file(
                path,
                config_dir=self.settings.config_dir,
                lock_timeout=self.settings.storage.lock_timeout_seconds,
                existing=contractors.list_all() if contractors.exists() else [],
            )
        except Exception as exc:  # shown to the person; holds no contractor data
            raise AppError(str(exc)) from exc
        self.contractor_file = path
        self._picked_ids = [r.talent_id for r in rows]
        self._picked_people = {r.talent_id: r.talent_name for r in rows}

    def _picked(self) -> ContractorFileInfo:
        contractors = self._loader().contractors
        stored = contractors.list_all() if contractors.exists() else []
        known = [c.talent_id for c in stored]
        matched, unmatched = match_ids(self.resumes, [*known, *self._picked_ids])
        have = {*matched.values(), *self._with_resume()}
        ids_of: dict[str, set[str]] = {}
        named = [*((c.talent_id, c.talent_name) for c in stored), *self._picked_people.items()]
        for talent_id, name in named:
            ids_of.setdefault(_name_key(name), set()).add(talent_id)
        shared: dict[str, str] = {}  # each shared name once, as first written in the file
        for n in self._picked_people.values():
            if len(ids_of[_name_key(n)]) > 1:
                shared.setdefault(_name_key(n), n)
        return ContractorFileInfo(
            path=self.contractor_file,
            contractors=len(self._picked_ids),
            resumes=len(matched),
            unmatched=unmatched,
            missing_resumes=[n for i, n in self._picked_people.items() if i not in have],
            same_name=list(shared.values()),
        )

    # ---- remembered folders and links (Settings store: the app's .env) ----

    def _save_env(self, key: str, value: str) -> None:
        secrets_file.set_value(self.env_path, key, value)
        self._environ[key] = value

    def _remembered(self, key: str) -> Path | None:
        value = self._environ.get(key, "").strip()
        return Path(value) if value else None

    def contractors_folder(self) -> Path | None:
        """The Contractors folder (or one zip) picked last time, if any."""
        return self._remembered(CONTRACTORS_FOLDER_ENV)

    def forget_contractors_folder(self) -> None:
        if self.contractors_folder() is not None:
            self._save_env(CONTRACTORS_FOLDER_ENV, "")

    def reimport_contractors(self) -> ContractorFileInfo:
        """Pick the remembered Contractors folder again (what is in it now); the next run
        loads it."""
        folder = self.contractors_folder()
        if folder is None:
            raise AppError("No Contractors folder is remembered yet.")
        if not folder.exists():
            raise AppError(f"The Contractors folder is not there any more: {folder}")
        return self.pick_contractor_folder(folder)

    def refresh_contractors(self) -> bool:
        """Before a search: pick the remembered Contractors folder again, but only when what is
        in it differs from what was loaded last (so an older folder never reverts newer data).
        Picks made by hand are left alone. True when a new pick is waiting for the run."""
        if self.contractor_file is not None or self.resumes:
            return False
        if self.contractors_folder() is None:
            return False
        self.reimport_contractors()
        if self._source_signature() == self._state().get("contractors_sig"):
            self.clear_contractor_picks()
            return False
        return True

    def jobs_folder(self) -> Path | None:
        return self._remembered(JOBS_FOLDER_ENV)

    def set_jobs_folder(self, folder: Path | None) -> None:
        """Remember the folder where job files are dropped; None forgets it."""
        if folder is not None and not folder.is_dir():
            raise AppError(f"Not a folder: {folder}")
        self._save_env(JOBS_FOLDER_ENV, str(folder) if folder else "")

    def import_jobs_folder(self) -> JobsFolderImport:
        """Copy every job file in the jobs folder that was not copied before to the inbox
        (add_jobs_file); the next Ingest / Find matches stores the jobs. A file is told apart
        by its content, so a changed file counts as new."""
        folder = self.jobs_folder()
        if folder is None:
            raise AppError("No jobs folder is set.")
        if not folder.is_dir():
            raise AppError(f"The jobs folder is not there any more: {folder}")
        seen = set(self._state().get("jobs_seen", []))
        result = JobsFolderImport()
        for path in sorted(folder.iterdir()):
            if (
                not path.is_file()
                or path.name.startswith((".", "~$"))
                or path.suffix.lower() not in JOB_SUFFIXES
            ):
                continue
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)  # a file with a problem is reported once, until it changes
            try:
                self.add_jobs_file(path.name, data)
            except AppError as exc:
                result.problems.append(str(exc))
            else:
                result.new_files += 1
        self._save_state(jobs_seen=sorted(seen))
        return result

    # ---- "Get latest": the do good link (sync_client downloads, the importer above reads) ----

    def sync_root(self) -> Path:
        """Where the downloaded copies live: synced/contractors and synced/jobs, beside the
        .env (the app's own folder; never inside data/, so an export does not copy them)."""
        return self.env_path.parent / SYNCED_DIR

    def _sync_link(self, text: str | None = None) -> sync_client.SyncLink | None:
        raw = (self._environ.get(SYNC_LINK_ENV, "") if text is None else text).strip()
        if not raw:
            return None
        return sync_client.parse_link(
            raw, allow_local_http=self._environ.get(SYNC_DEV_ENV, "") == "1"
        )

    def _sync_api(self, link: sync_client.SyncLink) -> sync_client.SyncApi:
        return sync_client.SyncApi(
            link,
            allow_local_http=self._environ.get(SYNC_DEV_ENV, "") == "1",
            sleep=self.sync_sleep,
        )

    def _sync_state(self) -> sync_client.SyncState:
        return sync_client.SyncState(self.env_path.parent / SYNC_STATE_FILE)

    def has_sync_link(self) -> bool:
        try:
            return self._sync_link() is not None
        except sync_client.SyncError:
            return False

    def sync_pending(self) -> bool:
        """A link was saved and its folders are not yet the sources of Contractors / Jobs."""
        return self.has_sync_link() and bool(self._sync_state().data.get("adopt_pending"))

    def sync_link_hint(self) -> str:
        """The only part of the saved link that is ever shown: "…a1b2". "" = none saved."""
        try:
            link = self._sync_link()
        except sync_client.SyncError:
            return ""
        return link.hint if link else ""

    def save_sync_link(self, text: str) -> str:
        """Save the pasted link (HTTPS only, with its secret code) in the app's .env, like the
        Gemini key. Returns the hint to show. The next Get latest adopts the downloaded
        folders as the sources of Contractors and Jobs."""
        try:
            link = self._sync_link(text)
        except sync_client.SyncError as exc:
            raise AppError(exc.message) from None
        if link is None:
            raise AppError("The link is empty.")
        self._save_env(SYNC_LINK_ENV, f"{link.base}?sync={link.token}")
        self._sync_state().set(adopt_pending=True)
        return link.hint

    def forget_sync_link(self) -> None:
        """Remove the link. Folders already downloaded stay where they are as plain folders."""
        self._save_env(SYNC_LINK_ENV, "")
        self._sync_state().set(adopt_pending=False)
        self._latest_problem = ""

    def test_sync_link(self, text: str | None = None) -> LinkTest:
        """Ask the link what it holds (the pasted one, or the saved one). Saves nothing."""
        try:
            link = self._sync_link(text)
            if link is None:
                return LinkTest(kind="bad_link")
            api = self._sync_api(link)
            try:
                found = sync_client.check_link(api)
            finally:
                api.close()
        except sync_client.SyncError as exc:
            return LinkTest(kind=exc.kind)
        return LinkTest(kind="ok", people=found.people, jobs=found.jobs)

    def _is_synced(self, folder: Path | None, name: str) -> bool:
        if folder is None:
            return False
        try:
            return folder.resolve() == (self.sync_root() / name).resolve()
        except OSError:
            return False

    def get_latest(
        self, *, adopt: bool = False, progress: sync_client.Progress | None = None
    ) -> LatestOutcome:
        """The cheap check, and a download only when something changed; then the folder import
        that already exists (sync_on_start: same checks, same report, no Gemini). `adopt` (the
        person asked, or the link was just saved) makes the downloaded folders the sources of
        Contractors and Jobs; otherwise a part the person pointed at another folder by hand is
        left alone. Never raises for network trouble: the problem is in the outcome and the
        local copy keeps working. `progress` is filled in while it runs (the screen reads it)."""
        try:
            link = self._sync_link()
        except sync_client.SyncError as exc:
            raise AppError(exc.message) from None
        if link is None:
            raise AppError("No do good link is saved yet.")
        if not self._latest_lock.acquire(blocking=False):
            return LatestOutcome(problem="busy")
        try:
            return self._get_latest(link, adopt, progress or sync_client.Progress())
        finally:
            self._latest_lock.release()

    def _get_latest(
        self, link: sync_client.SyncLink, adopt: bool, progress: sync_client.Progress
    ) -> LatestOutcome:
        root, state = self.sync_root(), self._sync_state()
        want = adopt or bool(state.data.get("adopt_pending"))
        use_contractors = want or self._is_synced(self.contractors_folder(), "contractors")
        use_jobs = want or self._is_synced(self.jobs_folder(), "jobs")
        problem, downloaded = "", False
        api = self._sync_api(link)
        try:
            syncer = sync_client.Syncer(api, root, state, progress)
            if use_contractors:
                try:
                    downloaded |= syncer.sync_contractors().status == "updated"
                except sync_client.SyncError as exc:
                    problem = exc.kind
            if use_jobs and problem not in ("offline", "bad_link"):
                try:
                    downloaded |= syncer.sync_jobs().status == "updated"
                except sync_client.SyncError as exc:
                    if exc.kind == "no_jobs":
                        state.update("jobs", enabled=False)
                    else:
                        problem = problem or exc.kind
        except OSError:  # the synced folder cannot be written
            problem = problem or "failed"
        finally:
            api.close()
        if want:
            if use_contractors and (root / "contractors").is_dir():
                self._save_env(CONTRACTORS_FOLDER_ENV, str(root / "contractors"))
            if use_jobs and (root / "jobs").is_dir():
                self._save_env(JOBS_FOLDER_ENV, str(root / "jobs"))
            if not problem:
                state.set(adopt_pending=False)
        self._latest_problem = problem
        progress.set("reading")
        before = self._state()
        summary = self.sync_on_start()  # the existing import: nothing is rewritten here
        if not problem or summary.people_added or summary.new_jobs:  # failed: keep the badges
            # The very first load of a list is the baseline (see _note_run): no "+N new" for it.
            first_people = "last_contractors_at" not in before
            first_jobs = "last_jobs_at" not in before
            state.set(
                new_contractors=0 if first_people else summary.people_added,
                new_jobs=0 if first_jobs else summary.new_jobs,
            )
        return LatestOutcome(summary=summary, problem=problem, downloaded=downloaded)

    def latest_status(self) -> LatestStatus:
        """For the Contractors and Jobs rows (cheap: reads two small files)."""
        try:
            link = self._sync_link()
        except sync_client.SyncError:
            link = None
        if link is None:
            return LatestStatus()
        state = self._sync_state()

        def part(name: str, folder: Path | None, new_key: str) -> PartStatus:
            saved = state.part(name)
            return PartStatus(
                from_link=self._is_synced(folder, name),
                checked_at=self._when(saved.get("ok_at")) if saved.get("ok_at") else None,
                new=int(state.data.get(new_key) or 0),
            )

        contractors = part("contractors", self.contractors_folder(), "new_contractors")
        jobs = part("jobs", self.jobs_folder(), "new_jobs")
        stamps = [p.checked_at for p in (contractors, jobs) if p.checked_at]
        return LatestStatus(
            has_link=True,
            hint=link.hint,
            contractors=contractors,
            jobs=jobs,
            last_ok_at=max(stamps, default=None),
            problem=self._latest_problem,
        )

    def talent_id_prefix(self) -> str:
        """How every talent ID starts (config/contractor_import.yaml), to tell a résumé named
        by a talent ID from any other PDF."""
        try:
            return load_contractor_import(self.settings.config_dir).talent_id_prefix
        except Exception:  # noqa: BLE001 (a missing config only means the default prefix)
            return ContractorImportRules.model_fields["talent_id_prefix"].default

    def links(self) -> dict[str, str]:
        """The three optional links (intake form, intake Sheet, job collector Sheet); "" =
        not set. A value that is not a web address (a hand-edited .env) is left out."""
        found = {n: self._environ.get(f"JOBMATCH_LINK_{n.upper()}", "").strip() for n in LINK_NAMES}
        return {n: (web_url_or_none(v) or "") for n, v in found.items()}

    def save_link(self, name: str, url: str) -> None:
        url = url.strip()
        if name not in LINK_NAMES:
            raise AppError(f"Unknown link: {name}")
        if url and not url.lower().startswith(("http://", "https://")):
            raise AppError("A link starts with http:// or https://")
        self._save_env(f"JOBMATCH_LINK_{name.upper()}", url)

    def _state(self) -> dict:
        try:
            state = json.loads((self.env_path.parent / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def _forget_state(self, *keys: str) -> None:
        state = self._state()
        if any(k in state for k in keys):
            atomic_write_text(
                self.env_path.parent / STATE_FILE,
                json.dumps({k: v for k, v in state.items() if k not in keys}),
            )

    def _save_state(self, **updates: object) -> None:
        atomic_write_text(
            self.env_path.parent / STATE_FILE, json.dumps({**self._state(), **updates})
        )

    def _note_run(self, report: RunOnceReport) -> None:
        now = datetime.now(UTC).isoformat()
        state = self._state()
        # The very first successful load of each list is the baseline: "+N new" counts only what
        # arrives after it (a list loaded by an older version has none and counts as before).
        if report.contractors is not None:
            first = "last_contractors_at" not in state
            self._save_state(
                last_contractors_at=now, **({"people_baseline_at": now} if first else {})
            )
        if report.ingest:
            first = "last_jobs_at" not in state
            self._save_state(last_jobs_at=now, **({"jobs_baseline_at": now} if first else {}))

    def _source_signature(self) -> str:
        """A fingerprint of the picked contractor file and résumés (their content)."""
        digest = hashlib.sha256()
        files = [self.contractor_file, *(self.resumes[k] for k in sorted(self.resumes))]
        for path in files:
            if path is not None:
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def _inbox_files(self) -> list[Path]:
        inbox = self.data_dir / "inbox"
        return [f for sub in ("links", "manual") for f in (inbox / sub).glob("*") if f.is_file()]

    @staticmethod
    def _file_digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _inbox_waiting(self) -> bool:
        """Inbox files the start-up sync should store: not one that already failed unchanged
        (it stays in the inbox until fixed; Save / Find matches still tries it again)."""
        failed = set(self._state().get("inbox_failed", []))
        return any(self._file_digest(f) not in failed for f in self._inbox_files())

    def sync_on_start(self) -> SyncSummary:
        """Opening the app: read the remembered Contractors and jobs folders and store what is
        new (the Ingest button's pass: contractors, résumés, jobs; no Gemini call). Nothing
        is run when nothing changed. A missing or bad folder is reported in `problems`.
        It works on a private copy of this service, so the picks made on screen meanwhile
        (and their temporary folders) are never touched."""
        worker = type(self)(
            self.settings,
            self.env_path,
            provider_factory=self._provider_factory,
            environ=self._environ,
        )
        return worker._sync_folders()

    def _sync_folders(self) -> SyncSummary:
        summary = SyncSummary(
            contractors_folder=self.contractors_folder(), jobs_folder=self.jobs_folder()
        )
        changed = False
        if summary.contractors_folder:
            try:
                summary.missing_resumes = self.reimport_contractors().missing_resumes
                changed = self._source_signature() != self._state().get("contractors_sig")
            except AppError as exc:
                summary.problems.append(str(exc))
        if summary.jobs_folder:
            try:
                got = self.import_jobs_folder()
            except AppError as exc:
                summary.problems.append(str(exc))
            else:
                summary.new_job_files = got.new_files
                summary.unreadable_files = list(got.problems)
                summary.problems += got.problems
        if changed or summary.new_job_files or self._inbox_waiting():
            try:
                report = run_once(
                    self.settings,
                    provider_factory=self._provider,
                    contractor_file=self.contractor_file if changed else None,
                    resumes=self.resumes if changed else {},
                    match=False,
                    echo=lambda line: None,
                )
            except (PipelineError, ContractorFileError, CsvStoreError, OSError) as exc:
                summary.problems.append(str(exc))
            else:
                summary.ran = True
                if report.contractors:
                    summary.people_added = len(report.contractors.added)
                    summary.people_updated = len(report.contractors.updated)
                summary.new_jobs = sum(r.count("new") for r in report.ingest)
                self._note_run(report)
                if changed:
                    self._save_state(contractors_sig=self._source_signature())
                # What is still in the inbox failed to load: not retried at every start.
                self._save_state(
                    inbox_failed=sorted(self._file_digest(f) for f in self._inbox_files())
                )
        self.clear_contractor_picks()
        summary.jobs_waiting = len(self.jobs_waiting())
        return summary

    def jobs_waiting(self) -> list[Job]:
        """Active jobs with no match yet (contractors still to scan), newest first: the jobs
        a "Match N jobs now?" question is about. Empty while there is no contractor list."""
        if not self.contractor_count():
            return []
        loader = self._loader()
        pictures = sync_rounds(self.settings, loader)
        waiting = [j for j in loader.jobs.list_all() if is_active(j) and pictures[j.job_id].to_scan]
        return sorted(waiting, key=lambda j: j.first_seen_at, reverse=True)

    def jobs_before(self, since: datetime, *, unmatched_only: bool) -> int:
        """Active jobs stored before `since` (only those with no match yet, if asked): the
        older backlog a search would also send to Gemini."""
        if unmatched_only:
            jobs = self.jobs_waiting()
        else:
            jobs = [j for j in self._loader().jobs.list_all() if is_active(j)]
        return sum(1 for j in jobs if j.first_seen_at < since)

    @staticmethod
    def _is_listed(job: Job) -> bool:
        """The Jobs screen lists a job unless the import left it out (see jobs_overview)."""
        return job.status in ACTIVE_STATUSES or job.availability is not JobAvailability.AVAILABLE

    def jobs_listed(self) -> int:
        """How many jobs the Jobs screen lists: the one job count on Home, the Jobs tile and
        the Jobs page."""
        return sum(1 for j in self._loader().jobs.list_all() if self._is_listed(j))

    def jobs_left_out(self) -> list[LeftOutJob]:
        """Jobs the import stored but left off the list, newest first, each with its reason."""
        left = [j for j in self._loader().jobs.list_all() if not self._is_listed(j)]
        left.sort(key=lambda j: j.first_seen_at, reverse=True)
        return [
            LeftOutJob(
                title=j.title_raw,
                company=j.company_raw,
                reason=left_out_reason(j),
            )
            for j in left
        ]

    def home_summary(self) -> HomeSummary:
        """The whole pipeline in numbers, for the home screen."""
        loader = self._loader()
        results = self.results()
        runs = loader.runs.list_all()
        state = self._state()

        def when(key: str) -> datetime | None:
            return datetime.fromisoformat(state[key]) if state.get(key) else None

        stored = self._loader().jobs.list_all()
        listed = sum(1 for j in stored if self._is_listed(j))
        return HomeSummary(
            contractors=self.contractor_count(),
            jobs=listed,
            jobs_left_out=len(stored) - listed,
            jobs_waiting=len(self.jobs_waiting()),
            matches_waiting=sum(m.decision is None for r in results for m in r.matches),
            last_run_at=max((r.finished_at or r.started_at for r in runs), default=None),
            last_contractors_at=when("last_contractors_at"),
            last_jobs_at=when("last_jobs_at"),
            contractors_folder=self.contractors_folder(),
            jobs_folder=self.jobs_folder(),
        )

    # ---- "new since last time" (the app's state file: when it was last opened / looked at) ----

    @staticmethod
    def _when(value: object) -> datetime | None:
        try:
            when = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return when if when.tzinfo else when.replace(tzinfo=UTC)

    def note_app_opened(self) -> None:
        """Once per start of the app: remember when it was opened, and keep the time of the
        opening before as the point "new" is counted from."""
        if self._open_noted:
            return
        self._open_noted = True
        self._previous_open = self._when(self._state().get("last_opened_at"))
        self._save_state(last_opened_at=datetime.now(UTC).isoformat())

    def _looked_at(self, kind: Literal["jobs", "talent"]) -> datetime | None:
        state = self._state()
        baseline = self._when(
            state.get("jobs_baseline_at" if kind == "jobs" else "people_baseline_at")
        )
        looked = self._when(state.get(f"{kind}_seen_at")) or self._previous_open
        return max((t for t in (looked, baseline) if t is not None), default=None)

    def new_items(self) -> NewItems:
        """Contractors and jobs added since they were last looked at (their screen opened), or
        since the app was last opened, but never counting what the first load brought in (that
        is the baseline). Nothing is new on a first start."""
        loader = self._loader()
        found = NewItems()
        since = self._looked_at("talent")
        if since is not None and loader.contractors.exists():
            known = {p.talent_id for p in loader.contractors.list_all()}
            found.people = {
                c.talent_id
                for c in loader.contractor_changes.list_all()
                if c.change == "added" and c.changed_at > since and c.talent_id in known
            }
        since = self._looked_at("jobs")
        if since is not None:
            found.jobs = {
                j.job_id for j in loader.jobs.list_all() if is_active(j) and j.first_seen_at > since
            }
        return found

    def mark_seen(self, kind: Literal["jobs", "talent"]) -> None:
        """The Jobs or Talent screen was opened: what it showed is no longer new."""
        self._save_state(**{f"{kind}_seen_at": datetime.now(UTC).isoformat()})

    # ---- what a running search is doing (read-only: nothing is written) ----

    def matching_plan(self) -> list[PlannedJob]:
        """The jobs the next search sends to Gemini, in the order it sends them: what the run
        itself works out (pipeline.run_once), asked again without sending anything."""
        loader = self._loader()
        jobs = [j for j in loader.jobs.list_all() if is_active(j)]
        if not jobs or not loader.contractors.exists():
            return []
        roster = build_roster(loader.contractors.list_all(), self.llm.payload, toggles(loader))
        if not roster.cards:
            return []
        rosters = contractors_to_scan(
            jobs, roster, loader.job_scans.list_all(), pair_states(loader), latest_changes(loader)
        )
        plan = plan_jobs(jobs, roster, self.llm, judgments_dir(self.data_dir), rosters)
        by_id = {j.job_id: j for j in jobs}
        return [
            PlannedJob(
                job_id=p.job_id,
                title=by_id[p.job_id].title_norm or by_id[p.job_id].title_raw,
                company=by_id[p.job_id].company_raw,
            )
            for p in plan
            if not p.cached
        ]

    def judged_since(self, since: datetime) -> list[FinishedJob]:
        """The jobs Gemini's answer was saved for after `since` (a search going on), with their
        best person, oldest first. Reads the saved answers only; the shortlists themselves
        are stored when the search ends."""
        folder = judgments_dir(self.data_dir)
        if not folder.is_dir():
            return []
        loader = self._loader()
        jobs = {j.job_id: j for j in loader.jobs.list_all()}
        profiles = self._profiles(loader)
        found: dict[str, FinishedJob] = {}
        for path in sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime):
            try:
                if path.stat().st_mtime < since.timestamp():
                    continue
                result = TrialResult.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            job = jobs.get(result.job_id)
            judged = judged_job(result, self.llm.shortlist)
            if job is None or judged is None:
                continue
            best = judged.matches[0] if judged.matches else None
            profile = profiles.get(best.talent_id) if best else None
            found[job.job_id] = FinishedJob(
                job_id=job.job_id,
                title=job.title_norm or job.title_raw,
                matches=len(judged.matches),
                best_name=profile.talent_name if profile else None,
                best_score=best.fit_score if best else None,
            )
        return list(found.values())

    def matches_waiting(self) -> int:
        """Recommended matches with no decision yet (what Review mode goes through)."""
        return sum(m.decision is None for r in self.results() for m in r.matches)

    def resume_path(self, talent_id: str) -> Path | None:
        """The stored résumé of a contractor in the list, or None."""
        contractors = self._loader().contractors
        known = [c.talent_id for c in contractors.list_all()] if contractors.exists() else []
        return stored_resume(self.data_dir, talent_id, known)

    def contractor_count(self) -> int:
        contractors = self._loader().contractors
        return len(contractors.list_all()) if contractors.exists() else 0

    # ---- the run ----

    def _provider(self) -> LLMProvider:
        if self._provider_factory is not None:
            return self._provider_factory()
        from jobmatch.llm.gemini import GeminiProvider
        from jobmatch.llm.provider import LlmConfigError

        try:
            return GeminiProvider.from_settings(self.llm)
        except LlmConfigError as exc:
            raise AppError("Add your Gemini key in Settings first.") from exc

    def run(
        self,
        *,
        echo: Callable[[str], None],
        confirm: Callable[[RunCheck], bool],
        progress: Callable[[float, str], None] | None = None,
        match: bool = True,
        say: Callable[[str], None] | None = None,
    ) -> RunOnceReport:
        """The "Find matches" button: load the picked contractor file (if any), import new
        jobs from the inbox, judge new jobs with Gemini, store shortlists. Blocking: the UI
        runs it in a worker thread. The picked contractor file is cleared once loaded.
        match=False is the "Ingest" button: store contractors, résumés and jobs only (no
        Gemini call), so the reviewer can check them before matching. `say` gets the plain
        sentences for the progress box; `echo` the technical lines."""
        if match:  # the remembered Contractors folder is read again, if it changed
            self.refresh_contractors()
        loaded = self._source_signature() if self.contractor_file is not None else None
        report = run_once(
            self.settings,
            provider_factory=self._provider,
            contractor_file=self.contractor_file,
            resumes=self.resumes,
            match=match,
            confirm=confirm,
            echo=echo,
            progress=progress,
            say=say,
        )
        self.clear_contractor_picks()
        self._note_run(report)
        if loaded is not None and report.contractors is not None:
            self._save_state(contractors_sig=loaded)  # what the store now holds
        return report

    def quota(self) -> Quota:
        # The screening model: one call per job, so its quota decides how many jobs fit today.
        today = UsageLedger(self._loader().llm_usage).today(model=self.llm.model)
        return Quota(requests=today.requests, rpd=self.llm.limits.rpd, tokens=today.tokens)

    # ---- results and decisions ----

    def _profiles(self, loader: DataLoader) -> dict[str, ContractorProfile]:
        contractors = loader.contractors
        return {p.talent_id: p for p in contractors.list_all()} if contractors.exists() else {}

    def _with_resume(self) -> set[str]:
        """Talent IDs with a stored résumé."""
        folder = resumes_dir(self.data_dir)
        return {f.stem for f in folder.glob(f"*{RESUME_SUFFIX}")} if folder.is_dir() else set()

    def results(self) -> list[JobResult]:
        """Every active job with its recommendations (llm/rounds.py) and the latest decision
        on each. Jobs with fits first, then those with a partial to check, then no match,
        then not judged yet; newest first within each group. Brings the rounds up to date
        first (no API call)."""
        loader = self._loader()
        pictures = sync_rounds(self.settings, loader)
        profiles = self._profiles(loader)
        decisions = latest_reviews(loader.llm_matches.list_all(), loader.reviews.latest_by_match())
        with_resume = self._with_resume()

        def view(m: LlmMatch) -> MatchView:
            profile = profiles.get(m.talent_id)
            return MatchView(
                match=m,
                name=profile.talent_name if profile else None,
                headline=profile.standardized_headline if profile else None,
                decision=_current_decision(decisions.get((m.job_id, m.talent_id))),
                unavailable=m.talent_id in pictures[m.job_id].unavailable,
                has_resume=m.talent_id in with_resume,
            )

        out: list[JobResult] = []
        for job in loader.jobs.list_all():
            if not is_active(job):
                continue
            picture = pictures[job.job_id]
            shown = picture.shortlist.shown
            if not shown and picture.to_scan:
                outcome: JobOutcome = "not_judged"
            elif not shown:
                outcome = "no_match"
            elif any(m.verdict is LlmVerdict.FIT for m in shown):
                outcome = "fits"
            else:
                outcome = "check_partial"
            out.append(
                JobResult(
                    job=job,
                    outcome=outcome,
                    matches=[view(m) for m in shown],
                    rejected=[view(m) for m in picture.shortlist.rejected],
                )
            )
        order = {"fits": 0, "check_partial": 1, "no_match": 2, "not_judged": 3}
        out.sort(key=lambda r: r.job.first_seen_at, reverse=True)
        out.sort(key=lambda r: order[r.outcome])
        return out

    def job_result(self, job_id: str) -> JobResult | None:
        """One job's card on Results, fresh (after a reject or a reset); None when the job
        is no longer active."""
        return next((r for r in self.results() if r.job.job_id == job_id), None)

    def review_queue(self) -> list[ReviewItem]:
        """Every undecided match for Review mode, grouped by job (the order of Results), best
        score first inside a job. Read fresh each time: a rejection can bring in the next
        best person."""
        profiles = self._profiles(self._loader())
        queue: list[ReviewItem] = []
        for result in self.results():
            todo = [v for v in result.matches if v.decision is None]
            todo.sort(key=lambda v: -(v.match.fit_score if v.match.fit_score is not None else -1))
            for i, view in enumerate(todo, 1):
                queue.append(
                    ReviewItem(
                        job=result.job,
                        view=view,
                        others=result.matches,
                        facts=_review_facts(profiles.get(view.match.talent_id)),
                        position=i,
                        of=len(todo),
                    )
                )
        return queue

    # ---- the Jobs screen ----

    def jobs_overview(self) -> list[JobOverview]:
        """Every imported job with its state, matching summary and approved candidates: open
        jobs A–Z by title, then closed jobs A–Z. Jobs the import left out (not contract, not
        Canada, duplicates, stubs without details) are not listed: they were never
        candidates."""
        loader = self._loader()
        jobs = [j for j in loader.jobs.list_all() if self._is_listed(j)]
        pictures = sync_rounds(self.settings, loader)
        profiles = self._profiles(loader)
        applications = latest_applications(loader.applications.list_all())
        new_people = self._new_people(loader, [j for j in jobs if is_active(j)])
        out: list[JobOverview] = []
        for job in jobs:
            picture = pictures[job.job_id]
            shown = picture.shortlist.shown
            if not is_active(job):
                state: JobState = "inactive"
            elif picture.to_scan:
                state = "waiting"
            elif shown:
                state = "matched"
            else:
                state = "no_match"
            matches = shown if shown or not picture.to_scan else None
            candidates = []
            for talent_id, s in picture.states.items():
                if s not in ("approved", "removed"):
                    continue
                profile = profiles.get(talent_id)
                application = applications.get((job.job_id, talent_id))
                status = application.status if application else ApplicationStatus.NOT_REFERRED
                candidates.append(
                    Candidate(
                        talent_id=talent_id,
                        name=profile.talent_name if profile else None,
                        headline=profile.standardized_headline if profile else None,
                        match=picture.rows.get(talent_id),
                        status=status,
                        removed=s == "removed",
                    )
                )
            candidates.sort(key=lambda c: (c.removed, rank(c.match) if c.match else (True,)))
            out.append(
                JobOverview(
                    job=job,
                    state=state,
                    summary=job_summary(job, matches),
                    candidates=candidates,
                    new_people=new_people.get(job.job_id, 0) if state == "waiting" else 0,
                )
            )
        # Open jobs A–Z, then closed ones (completed or unavailable) A–Z at the bottom.
        out.sort(
            key=lambda o: (
                o.state == "inactive",
                (o.job.title_norm or o.job.title_raw).casefold(),
                o.job.job_id,
            )
        )
        return out

    def _new_people(self, loader: DataLoader, active: list[Job]) -> dict[str, int]:
        """job_id -> how many contractors are still to be checked for it (the same rule the
        next Find matches uses). Jobs with nobody to check are left out."""
        llm = self.settings.llm
        if llm is None or not active or not self._profiles(loader):
            return {}
        roster = build_roster(self._profiles(loader).values(), llm.payload, toggles(loader))
        if not roster.cards:
            return {}
        todo = contractors_to_scan(
            active,
            roster,
            loader.job_scans.list_all(),
            pair_states(loader),
            latest_changes(loader),
        )
        return {job_id: len(r.aliases) for job_id, r in todo.items()}

    def set_job_availability(
        self, job_id: str, action: JobAction, now: datetime | None = None
    ) -> Job:
        """The Jobs screen toggles. completed / unavailable: the job leaves Results and is
        never sent to Gemini. reopen (only from those two): available again; the next run sends
        only contractors not judged for it yet (shortlists.py). One atomic rewrite of jobs.csv,
        after a timestamped backup."""
        jobs = self._loader().jobs
        job = jobs.get(job_id)
        if job is None:
            raise AppError("That job is not in the job list any more.")
        now = now or datetime.now(UTC)
        inactive = job.availability is not JobAvailability.AVAILABLE
        if action == "reopen":
            if not inactive:
                raise AppError("Only a completed or unavailable job can be reopened.")
            update = {
                "availability": JobAvailability.AVAILABLE,
                "availability_changed_at": now,
                "reopened_at": now,
            }
        else:
            if inactive:
                raise AppError("This job is already marked completed or unavailable.")
            update = {"availability": JobAvailability(action), "availability_changed_at": now}
        changed = job.model_copy(update=update)
        jobs.replace([changed])
        return changed

    # ---- the Talent screen ----

    def talent_overview(self) -> list[TalentOverview]:
        """Every contractor in the contractor list, with their availability and the jobs
        they were approved for: available A–Z by name, then not available A–Z. The note is
        the latest one saved in the Profile pop-up; before any, the note of the latest
        availability change (where notes were written until 2026-11-18)."""
        loader = self._loader()
        profiles = list(self._profiles(loader).values())
        latest = latest_toggles(loader)
        states = pair_states(loader)
        applications = latest_applications(loader.applications.list_all())
        jobs = {j.job_id: j for j in loader.jobs.list_all()}
        gone: dict[str, list[RemovedJob]] = {}
        for r in loader.removed_jobs.list_all():
            gone.setdefault(r.talent_id, []).append(r)
        with_resume = self._with_resume()
        notes = self._latest_notes(loader)
        ids_of: dict[str, list[str]] = {}
        for p in profiles:
            ids_of.setdefault(_name_key(p.talent_name), []).append(p.talent_id)
        out: list[TalentOverview] = []
        for p in profiles:
            toggle = latest.get(p.talent_id)
            approved: list[TalentJob] = []
            for (job_id, talent_id), state in states.items():
                job = jobs.get(job_id)
                if talent_id != p.talent_id or state not in ("approved", "removed") or not job:
                    continue
                application = applications.get((job_id, talent_id))
                approved.append(
                    TalentJob(
                        job_id=job_id,
                        title=job.title_norm or job.title_raw,
                        company=job.company_raw,
                        location=job.location_raw,
                        status=application.status
                        if application
                        else ApplicationStatus.NOT_REFERRED,
                        removed=state == "removed",
                        job_open=job.availability is JobAvailability.AVAILABLE,
                    )
                )
            listed = {t.job_id for t in approved}
            for r in gone.get(p.talent_id, []):
                if r.job_id in listed:
                    continue
                approved.append(
                    TalentJob(
                        job_id=r.job_id,
                        title=r.title,
                        company=r.company,
                        location=r.location,
                        status=r.status,
                        removed=r.status is ApplicationStatus.REJECTED,
                        job_open=False,
                        deleted=True,
                    )
                )
            approved.sort(key=lambda t: (t.removed, not t.job_open, t.title.casefold()))
            free_state, free_date = free_state_of(p.availability)
            out.append(
                TalentOverview(
                    talent_id=p.talent_id,
                    name=p.talent_name,
                    headline=p.standardized_headline,
                    available=is_available(p, toggle.available if toggle else None),
                    profile_open=p.contract,
                    toggled=toggle,
                    jobs=approved,
                    has_resume=p.talent_id in with_resume,
                    note=notes.get(p.talent_id, toggle.note if toggle else None),
                    availability=p.availability,
                    profile_updated=p.profile_updated,
                    same_name_ids=[i for i in ids_of[_name_key(p.talent_name)] if i != p.talent_id],
                    free_state=free_state,
                    free_date=free_date,
                )
            )
        out.sort(key=lambda t: (not t.available, t.name.casefold(), t.talent_id))
        return out

    def _latest_notes(self, loader: DataLoader) -> dict[str, str | None]:
        """talent ID -> the latest note saved in the Profile pop-up (None: cleared)."""
        out: dict[str, str | None] = {}
        rows = sorted(loader.talent_notes.list_all(), key=lambda n: n.noted_at)
        for row in rows:  # stable sort: file order breaks ties, later rows win
            out[row.talent_id] = row.note
        return out

    def save_profile(
        self,
        talent_id: str,
        values: dict[str, object],
        note: str | None,
        now: datetime | None = None,
    ) -> ProfileSaved:
        """The Save button of the Profile pop-up (Talent screen, user decisions 2026-11-18):
        the edited fields go to the contractor's row in the app's contractor list (backed up
        first), checked like an imported row; nothing is saved if a field is wrong. When
        what Gemini sees changed, the contractor is marked to be matched again, as after an
        import. A later contractor import with other values for them replaces the edit. The
        note goes to talent_notes.csv. talent_id cannot change (the résumé is named by it)."""
        loader = self._loader()
        profiles = self._profiles(loader)
        before = profiles.get(talent_id)
        if before is None:
            raise AppError(f"{talent_id} is not in the contractor list any more.")
        data = before.model_dump()
        data.update({k: v for k, v in values.items() if k in data and k != "talent_id"})
        try:
            after = ContractorProfile.model_validate(data)
        except ValidationError as exc:
            problems = [
                f"{'.'.join(str(part) for part in e['loc'][:1]) or 'profile'}: {e['msg']}"
                for e in exc.errors()
            ]
            raise AppError("Not saved. " + "; ".join(problems)) from None
        now = now or datetime.now(UTC)
        saved = ProfileSaved(profile_changed=after != before, rescan=False, note_changed=False)
        if saved.profile_changed:
            try:
                with FileLock(str(self.data_dir / PIPELINE_LOCK_FILE), timeout=1):
                    stored = list(profiles.values())
                    report = upsert_contractors([after], loader.contractors)
                    marked = mark_changes(loader, stored, report, self.llm.payload, now)
                    saved.rescan = bool(marked)
            except Timeout:
                raise AppError(
                    "A run is going: save again when it ends (nothing was saved)."
                ) from None
        text = (note or "").strip() or None
        current = self._latest_notes(loader)
        toggle = latest_toggles(loader).get(talent_id)
        shown = current.get(talent_id, toggle.note if toggle else None)
        if text != shown:
            loader.talent_notes.add_many(
                [TalentNote(talent_id=talent_id, note=text, reviewer=self.reviewer(), noted_at=now)]
            )
            saved.note_changed = True
        return saved

    def save_resume(self, talent_id: str, data: bytes, now: datetime | None = None) -> str:
        """A résumé picked on the Talent screen (user request 2026-11-18), stored as
        <talent_id>.pdf: "added", "replaced" (old copy kept in old/) or "unchanged"."""
        if talent_id not in self._profiles(self._loader()):
            raise AppError(f"{talent_id} is not in the contractor list any more.")
        try:
            return store_resume(self.data_dir, talent_id, data, now or datetime.now(UTC))
        except ValueError as exc:
            raise AppError(str(exc)) from None

    def set_talent_availability(
        self, talent_id: str, available: bool, note: str = "", now: datetime | None = None
    ) -> TalentAvailability:
        """The reviewer's "Available for matching" toggle, after checking with the
        contractor. Overrides the profile's own answer either way. Appended to
        talent_availability.csv (the latest counts). A hire never changes it (user decision
        2026-11-18)."""
        loader = self._loader()
        if talent_id not in self._profiles(loader):
            raise AppError(f"{talent_id} is not in the contractor list any more.")
        row = TalentAvailability(
            talent_id=talent_id,
            available=available,
            note=" ".join(note.split()) or None,
            reviewer=self.reviewer(),
            changed_at=now or datetime.now(UTC),
        )
        loader.talent_availability.add_many([row])
        return row

    def _history(self, loader: DataLoader, job_id: str, talent_id: str) -> list[Application]:
        rows = [
            a
            for a in loader.applications.list_all()
            if a.job_id == job_id and a.talent_id == talent_id
        ]
        return sorted(rows, key=lambda a: a.updated_at)  # stable: file order on ties

    def set_application(
        self,
        job_id: str,
        talent_id: str,
        status: ApplicationStatus,
        now: datetime | None = None,
    ) -> None:
        """Save an approved candidate's application status (Jobs screen). "rejected"
        (rejection or ghosted) takes them out of consideration for this job; "hired" marks
        the job completed. A hire leaves the contractor available: they can take on several
        projects if their time allows (user decision 2026-11-18). Moving away from "hired"
        still restores availability a hire set under the old rule (before 2026-11-18),
        unless a reviewer changed it since. Appended to applications.csv (the latest counts)."""
        loader = self._loader()
        job = loader.jobs.get(job_id)
        if job is None:
            raise AppError("That job is not in the job list any more.")
        state = pair_states(loader).get((job_id, talent_id))
        if state not in ("approved", "removed"):
            raise AppError("Only a candidate approved on Results has an application status.")
        if state == "removed":
            raise AppError("This candidate's application was rejected: use Undo first.")
        now = now or datetime.now(UTC)
        history = self._history(loader, job_id, talent_id)
        was_hired = bool(history) and history[-1].status is ApplicationStatus.HIRED
        loader.applications.add_many(
            [
                Application(
                    job_id=job_id,
                    talent_id=talent_id,
                    status=status,
                    reviewer=self.reviewer(),
                    updated_at=now,
                )  # fmt: skip
            ]
        )
        title = job.title_norm or job.title_raw
        if status is ApplicationStatus.HIRED:
            if job.availability is JobAvailability.AVAILABLE:
                self.set_job_availability(job_id, "completed", now)
        elif was_hired:
            self._undo_hire_availability(loader, job_id, talent_id, title, now)

    def _undo_hire_availability(
        self, loader: DataLoader, job_id: str, talent_id: str, title: str, now: datetime
    ) -> None:
        """The hire was undone: availability goes back to what it was before it, unless a
        reviewer changed it since (their choice stands)."""
        rows = sorted(
            (t for t in loader.talent_availability.list_all() if t.talent_id == talent_id),
            key=lambda t: t.changed_at,
        )
        hire_note = f"({job_id})"
        if (
            not rows
            or rows[-1].reviewer != HIRE_REVIEWER
            or not (rows[-1].note or "").endswith(hire_note)
        ):
            return
        profile = self._profiles(loader).get(talent_id)
        before = rows[-2].available if len(rows) > 1 else bool(profile and profile.contract)
        loader.talent_availability.add_many(
            [
                TalentAvailability(
                    talent_id=talent_id,
                    available=before,
                    note=f"Hire undone for {title} ({job_id})",
                    reviewer=HIRE_UNDONE_REVIEWER,
                    changed_at=now,
                )
            ]
        )

    # ---- deletions (the screens ask for confirmation first) ----

    def delete_job(self, job_id: str, now: datetime | None = None) -> int:
        """Delete a completed or unavailable job from the app entirely (user decisions
        2026-11-10, 2026-11-11): its row in jobs.csv, its scans, rounds and application
        statuses. Only a contractor hired for it keeps it on the Talent screen
        (removed_jobs.csv: title, company, location, status). Gemini's results for it go
        too: its shortlist rows, and its cached answers, moved to
        data/backups/removed-judgments/<time>-<job>/, so the job imported again is asked
        afresh. Decisions stay (evaluation data, IDs only) but no longer count for a row made
        again (rounds.latest_reviews). Every file is backed up before it is rewritten.
        Returns the contractors who keep it on their list."""
        loader = self._loader()
        job = loader.jobs.get(job_id)
        if job is None:
            raise AppError("That job is not in the job list any more.")
        if job.availability is JobAvailability.AVAILABLE:
            raise AppError("Only a completed or unavailable job can be deleted.")
        now = now or datetime.now(UTC)
        applications = latest_applications(loader.applications.list_all())
        keep = [
            RemovedJob(
                job_id=job_id,
                talent_id=talent_id,
                title=job.title_norm or job.title_raw,
                company=job.company_raw,
                location=job.location_raw,
                status=ApplicationStatus.HIRED,
                removed_at=now,
                removed_by=self.reviewer(),
            )
            for (j, talent_id), a in applications.items()
            if j == job_id and a.status is ApplicationStatus.HIRED
        ]  # fmt: skip
        if keep:
            loader.removed_jobs.add_many(keep)  # first: an interrupted delete loses nothing
        loader.job_scans.remove_where(lambda r: r.job_id == job_id)
        loader.job_rounds.remove_where(lambda r: r.job_id == job_id)
        loader.applications.remove_where(lambda r: r.job_id == job_id)
        loader.llm_matches.remove_where(lambda r: r.job_id == job_id)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
        move_judgments(
            judgments_dir(self.data_dir),
            job_id,
            self.data_dir / "backups" / "removed-judgments" / f"{now:%Y%m%dT%H%M%SZ}-{safe}",
        )
        loader.jobs.remove(job_id)
        return len(keep)

    def delete_talent(self, talent_id: str) -> None:
        """Delete a contractor and everything about them (user decisions 2026-11-10): their
        row in the app's contractor list, résumé (and old copies), availability, notes, change
        marks, scans, round slots, shortlist rows, the decisions on those rows, application
        statuses and removed-job rows. Only when they are not available for matching. Each
        CSV is backed up before it is rewritten (CLAUDE.md); the picked contractor folder is
        never touched, and a later import adds them back as new."""
        loader = self._loader()
        profile = self._profiles(loader).get(talent_id)
        if profile is None:
            raise AppError(f"{talent_id} is not in the contractor list any more.")
        toggle = latest_toggles(loader).get(talent_id)
        if is_available(profile, toggle.available if toggle else None):
            raise AppError("Mark them not available before deleting them.")
        matches = {m.match_id for m in loader.llm_matches.list_all() if m.talent_id == talent_id}
        mine = lambda r: r.talent_id == talent_id  # noqa: E731
        loader.reviews.remove_where(lambda r: r.match_id in matches)
        loader.llm_matches.remove_where(mine)
        loader.job_scans.remove_where(mine)
        loader.job_rounds.remove_where(mine)
        loader.applications.remove_where(mine)
        loader.removed_jobs.remove_where(mine)
        loader.contractor_changes.remove_where(mine)
        loader.talent_availability.remove_where(mine)
        loader.talent_notes.remove_where(mine)
        folder = resumes_dir(self.data_dir)
        (folder / f"{talent_id}{RESUME_SUFFIX}").unlink(missing_ok=True)
        old = re.compile(rf"{re.escape(talent_id)}-\d{{8}}T\d{{6}}Z{RESUME_SUFFIX}")
        if (folder / "old").is_dir():
            for pdf in (folder / "old").iterdir():
                if old.fullmatch(pdf.name):
                    pdf.unlink()
        loader.contractors.remove_where(mine)  # last: the delete can be run again

    def undo_application_rejection(
        self, job_id: str, talent_id: str, now: datetime | None = None
    ) -> ApplicationStatus:
        """Bring back a candidate whose application was rejected or ghosted (a misclick,
        usually): their status goes back to what it was before. Returns that status."""
        loader = self._loader()
        history = self._history(loader, job_id, talent_id)
        if not history or history[-1].status is not ApplicationStatus.REJECTED:
            raise AppError("This candidate's application is not rejected: nothing to undo.")
        before = next(
            (a.status for a in reversed(history) if a.status is not ApplicationStatus.REJECTED),
            ApplicationStatus.NOT_REFERRED,
        )
        loader.applications.add_many(
            [
                Application(
                    job_id=job_id,
                    talent_id=talent_id,
                    status=before,
                    reviewer=self.reviewer(),
                    updated_at=now or datetime.now(UTC),
                )  # fmt: skip
            ]
        )
        return before

    def decide(
        self,
        match_id: str,
        decision: Decision,
        reason: ReasonCode | None = None,
        notes: str | None = None,
    ) -> Review:
        """Store one decision in reviews.csv (append-only; the latest one counts)."""
        if decision is Decision.REJECTED and reason is None:
            raise AppError("Pick a reason for the rejection.")
        review = Review(
            match_id=match_id,
            decision=decision,
            reason_code=reason,
            notes=(notes or "").strip() or None,
            reviewer=self.reviewer(),
            reviewed_at=datetime.now(UTC),
        )
        self._loader().reviews.append(review)
        return review

    def clear_decision(self, match_id: str) -> None:
        """Reset a match to undecided. reviews.csv is append-only (it is the evaluation
        record), so this adds a "cleared" row instead of deleting anything."""
        review = Review(
            match_id=match_id,
            decision=Decision.CLEARED,
            reviewer=self.reviewer(),
            reviewed_at=datetime.now(UTC),
        )
        self._loader().reviews.append(review)

    def contractor_fields(self, talent_id: str) -> list[tuple[str, list[str]]]:
        """One contractor's stored record as (column name, values), in the contractor list's
        column order (the CSV columns): list fields as their items, other fields as text,
        empty fields as []. For the read-only Profile pop-up. Holds personal data: shown on
        screen only."""
        contractors = self._loader().contractors
        if not contractors.exists():
            raise AppError("There is no contractor list yet.")
        profile = next((p for p in contractors.list_all() if p.talent_id == talent_id), None)
        if profile is None:
            raise AppError(f"{talent_id} is not in the contractor list any more.")
        fields: list[tuple[str, list[str]]] = []
        for column in ContractorProfile.model_fields:
            value = getattr(profile, column)
            if isinstance(value, list):
                fields.append((column, [str(v) for v in value]))
            else:
                text = to_cell(value).strip()
                fields.append((column, [text] if text else []))
        return fields

    def export(self) -> ExportResult:
        return export_current(self.settings)
