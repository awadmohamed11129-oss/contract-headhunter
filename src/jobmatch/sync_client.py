"""Get latest: the client of the do good download link. No screen code in this file.

The Google side (the intake form's Apps Script web app, "version 13") hands out the newest
contractor folder and the job collector's files behind one secret link:

    https://script.google.com/macros/s/<deployment>/exec?sync=<64 hex characters>

This module asks it (HTTP GET only, HTTPS only), checks every file against the hash in the
manifest, and writes the result under the app's `synced/` folder in the exact shape the app
already imports: `synced/contractors/contractors.csv` + `resumes/<talent_id>.pdf`, and
`synced/jobs/*.txt`. Nothing is imported here; the service points the existing import at
those folders.

Safety:
- The token is the only credential. It is never logged, never part of an error text, and
  `mask_secrets` hides it from any text that is shown. Nothing is ever uploaded.
- A contractor download is built in a temporary folder next to the real one, verified, and
  only then swapped in: a broken or half download never replaces the last good copy.
- Only the app's own `synced/` folder is touched. Files the person added elsewhere are never
  read for deletion.
- Plain-text errors (`SyncError.message`) say what happened; they carry no URL.

The contract (answers, error codes, limits) is SYNC-CONTRACT.md of the Google side.
"""

import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from jobmatch.storage.files import atomic_write_text

logger = logging.getLogger("jobmatch.sync")

# httpx logs the address of every request at INFO level; the address holds the token.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

HASH_KEY = b"resume-fingerprint-v1"  # public: it only name-spaces the hash (contract, 1a)
TOKEN = re.compile(r"[0-9a-f]{64}")
SECRET_RUN = re.compile(r"[0-9a-fA-F]{64}")
SYNC_PARAM = re.compile(r"(sync=)[^&\s\"']+")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}  # http is allowed here, in a dev run only
CONTRACTOR_PATH = re.compile(r"contractors\.csv|resumes/[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.pdf")
JOB_PATH = re.compile(r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}/)?[A-Za-z0-9][A-Za-z0-9 ._()-]{0,200}\.txt")
JOB_PAGE = 20  # files per question: ~10 s a page (Google reads ~0.5 s per file; limit 120 s), so
# the screen can show honest step-by-step progress
MAX_LIMIT = 800  # the most files one question may ask for
MAX_PAGES = 25  # job pages (the collector lists at most 800 files)
MAX_BYTES = 60 * 1024 * 1024  # one answer, once decoded: far above anything real
MAX_WAIT = 20.0  # seconds a "busy" / "changed" answer is waited for (the contract says 20)
TRIES = 3  # the first ask plus at most two more (contract: wait, ask again, at most twice)

PLAIN = {
    "offline": "Could not reach your list. Check your internet connection.",
    "bad_link": "The link was not recognised.",
    "busy": "Your list is busy right now.",
    "no_data": "Nobody is on the list yet.",
    "no_jobs": "Jobs are not switched on for this link yet.",
    "damaged": "A downloaded file did not match, so nothing was changed.",
    "failed": "Could not get the latest right now.",
}


class SyncError(Exception):
    """A problem in plain words. `kind` is one of PLAIN's keys (or "changed" / "too_big",
    which are handled inside this module)."""

    def __init__(self, kind: str, message: str | None = None, retry_after: float = 0.0) -> None:
        self.kind = kind
        self.message = message or PLAIN.get(kind, PLAIN["failed"])
        self.retry_after = retry_after
        super().__init__(self.message)


def mask_secrets(text: str) -> str:
    """Hide a token (or `sync=...`) inside any text that might be shown or logged."""
    text = SYNC_PARAM.sub(r"\1…", text)
    return SECRET_RUN.sub(lambda m: "…" + m.group(0)[-4:], text)


def file_hash(data: bytes) -> str:
    """The manifest's hash: HMAC-SHA256 with the public key, as 64 lower-case hex characters."""
    return hmac.new(HASH_KEY, data, hashlib.sha256).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---- the link ----


@dataclass(frozen=True)
class SyncLink:
    base: str  # the address without the query
    token: str  # 64 lower-case hex characters

    @property
    def hint(self) -> str:
        """All that may ever be shown of the link."""
        return "…" + self.token[-4:]

    def __repr__(self) -> str:  # a stray print or log line can never show the token
        return f"SyncLink({self.hint})"


def parse_link(text: str, *, allow_local_http: bool = False) -> SyncLink:
    """Read a pasted link. HTTPS only (plain http only to this computer, and only when the
    dev flag is on). A link without the 64-character `sync=` code is "not recognised"."""
    raw = (text or "").strip().strip("\"'<>")
    if not raw or any(c.isspace() for c in raw):
        raise SyncError("bad_link")
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        token = parse_qs(parts.query).get("sync", [""])[0].strip().lower()
    except ValueError as exc:
        raise SyncError("bad_link") from exc
    secure = parts.scheme == "https"
    local = parts.scheme == "http" and allow_local_http and host in LOCAL_HOSTS
    if not (secure or local) or not host or not TOKEN.fullmatch(token):
        raise SyncError("bad_link")
    if secure and not parts.path.rstrip("/").endswith("/exec"):
        raise SyncError("bad_link")  # a Sheet or a Drive link, not the download link
    return SyncLink(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), token)


# ---- the questions (GET only) ----


class SyncApi:
    """One GET at a time to the link, answers read as the contract says."""

    def __init__(
        self,
        link: SyncLink,
        *,
        allow_local_http: bool = False,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.link = link
        self._allow_local_http = allow_local_http
        self.sleep = sleep
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(20.0, read=120.0),
            follow_redirects=True,
            headers={"User-Agent": "dogoodtalent"},
            event_hooks={"request": [self._guard]},
        )

    def _guard(self, request: httpx.Request) -> None:
        """Every request, redirects included: https only (this computer only, in a dev run)."""
        url = request.url
        if url.scheme == "https":
            return
        if url.scheme == "http" and self._allow_local_http and url.host in LOCAL_HOSTS:
            return
        raise SyncError("failed", "A redirect to an unsafe address was refused.")

    def close(self) -> None:
        self._client.close()

    def get(self, **params: str | int | None) -> bytes:
        query = {"sync": self.link.token, **{k: v for k, v in params.items() if v is not None}}
        try:
            response = self._client.get(self.link.base, params=query)
        except httpx.TransportError as exc:  # no internet, no DNS, timeout, reset
            logger.warning("sync_unreachable", extra={"fields": {"error": type(exc).__name__}})
            raise SyncError("offline") from exc
        except httpx.HTTPError as exc:  # too many redirects and the like
            logger.warning("sync_http_error", extra={"fields": {"error": type(exc).__name__}})
            raise SyncError("failed") from exc
        if response.status_code == 404:
            raise SyncError("bad_link")
        if response.status_code != 200:
            logger.warning("sync_status", extra={"fields": {"status": response.status_code}})
            raise SyncError("failed")
        if len(response.content) > MAX_BYTES:
            raise SyncError("failed")
        return response.content

    @staticmethod
    def _problem(data: dict) -> SyncError:
        code = str(data.get("error") or "")
        if code in ("busy", "changed"):  # both say how long to wait (20 seconds)
            wait = data.get("retry_after_seconds")
            return SyncError(code, retry_after=float(wait) if isinstance(wait, int | float) else 0)
        if code in ("too_big", "no_data", "bad_since"):
            return SyncError(code)
        if code in ("no_jobs_folder", "jobs_folder_unreadable"):
            return SyncError("no_jobs")
        return SyncError("failed")

    def call(self, **params: str | int | None) -> dict:
        """A JSON answer with ok: true. Anything else becomes a SyncError."""
        body = self.get(**params)
        if body.strip() == b"not found":  # a wrong token: plain text, HTTP 200
            raise SyncError("bad_link")
        try:
            data = json.loads(body)
        except ValueError as exc:  # an HTML page, not our answer
            raise SyncError("bad_link") from exc
        if not isinstance(data, dict):
            raise SyncError("failed")
        if data.get("ok") is not True:
            raise self._problem(data)
        return data

    def csv(self) -> bytes:
        body = self.get(a="csv")
        if body.strip() == b"not found":
            raise SyncError("bad_link")
        if body.lstrip(b"\xef\xbb\xbf").startswith(b"{"):  # an error answer, not the file
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise SyncError("failed") from exc
            raise self._problem(data) if isinstance(data, dict) else SyncError("failed")
        return body

    def with_retries[T](self, work: Callable[[], T]) -> T:
        """Run `work`; "busy" and "changed" are tried again (a short wait), three times."""
        for attempt in range(1, TRIES + 1):
            try:
                return work()
            except SyncError as exc:
                if exc.kind not in ("busy", "changed") or attempt == TRIES:
                    raise
                self.sleep(min(exc.retry_after or 3.0, MAX_WAIT))
        raise SyncError("failed")  # unreachable


def decode_data(answer: dict) -> bytes:
    if answer.get("encoding") != "base64" or not isinstance(answer.get("data"), str):
        raise SyncError("failed")
    try:
        data = base64.b64decode(answer["data"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SyncError("failed") from exc
    if len(data) > MAX_BYTES:
        raise SyncError("failed")
    return data


# ---- what the client remembers (etag, newest job time, last check) ----


class SyncState:
    """A small JSON file (sync_state.json beside the app's .env): per part the etag or the
    newest job time, when it was last checked, what was new. No personal data, no link."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.data: dict = data if isinstance(data, dict) else {}

    def part(self, name: str) -> dict:
        found = self.data.get(name)
        return found if isinstance(found, dict) else {}

    def update(self, name: str, **values: object) -> None:
        self.data[name] = {**self.part(name), **values}
        self.save()

    def set(self, **values: object) -> None:
        self.data.update(values)
        self.save()

    def save(self) -> None:
        """Atomic. Windows refuses the swap while the screen is reading the file at that very
        moment: try again a few times; a state that could not be saved only means the next
        check asks a little more."""
        for attempt in range(8):
            try:
                atomic_write_text(self.path, json.dumps(self.data))
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
            except OSError:
                break
        logger.warning("sync_state_not_saved")


class Progress:
    """What a download is doing right now, for the screen to read on a timer. The download
    (worker thread) writes it; nothing here is ever a secret. `part` is "contractors", "jobs"
    or "reading" (the downloaded files are being read into the app); `total` is None while the
    number of files to come is not known (only the first download knows it)."""

    def __init__(self) -> None:
        self.part = ""
        self.found = 0
        self.total: int | None = None

    def set(self, part: str, found: int = 0, total: int | None = None) -> None:
        self.part, self.found, self.total = part, found, total

    @property
    def share(self) -> float:
        """How far along, 0 to 1: the contractors are a short first step, the jobs the long one."""
        if self.part == "contractors":
            return 0.05
        if self.part == "jobs":
            if not self.total:
                return 0.1
            return 0.1 + 0.85 * min(self.found / self.total, 1.0)
        return 0.97 if self.part == "reading" else 0.0


@dataclass
class PartResult:
    status: str  # "unchanged" or "updated"
    new_files: int = 0  # jobs: new files written; contractors: files that changed
    etag: str = ""


@dataclass
class LinkCheck:
    people: int  # contractors found
    jobs: int | None  # jobs found; None = the job part is not switched on


def check_link(api: SyncApi) -> LinkCheck:
    """What "Test link" asks: how many people and jobs the link offers (nothing is saved)."""
    try:
        listed = api.with_retries(lambda: api.call(a="manifest"))
        people = int(listed.get("people") or 0)
    except SyncError as exc:
        if exc.kind != "no_data":
            raise
        people = 0
    try:
        found = api.with_retries(lambda: api.call(part="jobs", a="manifest", limit=1))
        jobs: int | None = int(found.get("total_listed") or found.get("count") or 0)
    except SyncError as exc:
        if exc.kind != "no_jobs":
            raise
        jobs = None
    return LinkCheck(people, jobs)


# ---- the folders ----


def _temp_dir(root: Path, name: str) -> Path:
    path = root / f".{name}-new-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    return path


def clean_leftovers(root: Path) -> None:
    """Temporary folders of an earlier download that was cut short (our own, hidden)."""
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_dir() and re.match(r"\.(contractors|jobs)-(new|old)-", entry.name):
                shutil.rmtree(entry, ignore_errors=True)


def _swap(tmp: Path, final: Path) -> None:
    """tmp becomes final. The old folder is set aside first and put back if the swap fails
    (a PDF open in a viewer can block a rename on Windows)."""
    old: Path | None = None
    if final.exists():
        old = final.with_name(f".{final.name}-old-{uuid.uuid4().hex[:8]}")
        try:
            os.replace(final, old)
        except OSError as exc:
            raise SyncError("failed", "Your last copy is in use, so it was kept as it is.") from exc
    try:
        os.replace(tmp, final)
    except OSError as exc:
        if old is not None:
            os.replace(old, final)
        raise SyncError("failed", "Could not save the new copy, so the old one was kept.") from exc
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def _manifest_files(manifest: dict) -> dict[str, str]:
    """{path: hash} of a contractor manifest; any path outside the two known shapes stops it."""
    files: dict[str, str] = {}
    for item in manifest.get("files") or []:
        path, digest = str(item.get("path", "")), str(item.get("hash", ""))
        if not CONTRACTOR_PATH.fullmatch(path) or not TOKEN.fullmatch(digest):
            raise SyncError("damaged", "The list from Google looked wrong, so nothing was changed.")
        files[path] = digest
    if "contractors.csv" not in files:
        raise SyncError("damaged", "The list from Google had no contractor file.")
    return files


def _write(root: Path, path: str, data: bytes) -> None:
    target = root.joinpath(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _verify(root: Path, expected: dict[str, str]) -> None:
    """Exactly the expected files are there and each one matches its hash."""
    found = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if found != set(expected):
        raise SyncError("damaged")
    for path, digest in expected.items():
        if not hmac.compare_digest(file_hash((root / path).read_bytes()), digest):
            raise SyncError("damaged")


class Syncer:
    """Downloads what changed into `root` (the app's synced/ folder) and keeps the state."""

    def __init__(
        self, api: SyncApi, root: Path, state: SyncState, progress: Progress | None = None
    ) -> None:
        self.api, self.root, self.state = api, root, state
        self.progress = progress or Progress()
        self.root.mkdir(parents=True, exist_ok=True)
        clean_leftovers(root)

    @property
    def contractors_dir(self) -> Path:
        return self.root / "contractors"

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    # -- contractors --

    def sync_contractors(self, *, force: bool = False) -> PartResult:
        return self.api.with_retries(lambda: self._contractors_once(force))

    def _contractors_once(self, force: bool) -> PartResult:
        self.progress.set("contractors")
        final, state = self.contractors_dir, self.state.part("contractors")
        etag = str(state.get("etag") or "") if final.is_dir() and not force else ""
        try:
            try:
                manifest = self.api.call(a="manifest", since=etag or None)
            except SyncError as exc:
                if exc.kind != "bad_since" or not etag:
                    raise
                manifest = self.api.call(a="manifest")  # a stored etag it refuses: ask in full
        except SyncError as exc:
            if exc.kind != "no_data":
                raise
            self.state.update("contractors", checked_at=_now(), ok_at=_now(), empty=True)
            return PartResult("unchanged")
        if manifest.get("changed") is False:
            self.state.update("contractors", checked_at=_now(), ok_at=_now(), empty=False)
            return PartResult("unchanged", etag=etag)
        self.progress.set("contractors", found=int(manifest.get("people") or 0))
        wanted = _manifest_files(manifest)
        local = self._local_hashes(final, wanted)
        need = [p for p, h in wanted.items() if local.get(p) != h]
        if not need and final.is_dir():  # same content: only the etag moved
            self.state.update(
                "contractors", etag=str(manifest.get("etag") or ""), checked_at=_now(),
                ok_at=_now(), empty=False,
            )  # fmt: skip
            return PartResult("unchanged", etag=str(manifest.get("etag") or ""))
        tmp = _temp_dir(self.root, "contractors")
        try:
            expected, new_etag = wanted, str(manifest.get("etag") or "")
            for path in wanted:
                if path in local and local[path] == wanted[path]:
                    _write(
                        tmp, path, (final / path).read_bytes()
                    )  # unchanged: not downloaded again
            if manifest.get("zip_available") and (
                len(need) * 2 >= len(wanted) or not final.is_dir()
            ):
                # The zip describes the files it holds: trust ITS list and ITS etag, even when
                # the folder changed since the manifest call (contract, "Which etag to trust").
                expected, zip_etag = self._fill_from_zip(tmp)
                new_etag = zip_etag or new_etag
            else:
                self._fill_paged(tmp, manifest, wanted, need)
            _verify(tmp, expected)
            _swap(tmp, final)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.state.update(
            "contractors", etag=new_etag, checked_at=_now(), ok_at=_now(), changed_at=_now(),
            empty=False,
        )  # fmt: skip
        return PartResult("updated", new_files=len(need), etag=new_etag)

    @staticmethod
    def _local_hashes(final: Path, wanted: dict[str, str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for path in wanted:
            target = final.joinpath(*path.split("/"))
            if target.is_file():
                found[path] = file_hash(target.read_bytes())
        return found

    def _fill_from_zip(self, tmp: Path) -> tuple[dict[str, str], str]:
        """The whole folder from one zip; returns the hashes of the zip's own manifest.json
        and the etag to remember (the zip answer's, which is the inner manifest's)."""
        answer = self.api.call(a="zip")
        try:
            with zipfile.ZipFile(io.BytesIO(decode_data(answer))) as archive:
                names = {i.filename for i in archive.infolist() if not i.is_dir()}
                if "manifest.json" not in names:
                    raise SyncError("damaged")
                inner = json.loads(archive.read("manifest.json"))
                expected = _manifest_files(inner)
                for path in expected:
                    if path not in names:
                        raise SyncError("damaged")
                    _write(tmp, path, archive.read(path))
        except (zipfile.BadZipFile, ValueError, KeyError) as exc:
            raise SyncError("damaged") from exc
        return expected, str(answer.get("etag") or inner.get("etag") or "")

    def _fill_paged(
        self, tmp: Path, manifest: dict, wanted: dict[str, str], need: list[str]
    ) -> None:
        etag = str(manifest.get("etag") or "")
        if "contractors.csv" in need:
            _write(tmp, "contractors.csv", self.api.csv())
        for path in need:
            if path != "contractors.csv":
                _write(
                    tmp,
                    path,
                    self._download_file(a_id=path[len("resumes/") : -len(".pdf")], etag=etag),
                )

    def _download_file(self, *, a_id: str, etag: str) -> bytes:
        """One résumé, piece by piece; the pieces are joined and checked as a whole."""
        pieces: list[bytes] = []
        chunks, n = 1, 0
        while n < chunks:
            answer = self.api.call(a="file", id=a_id, n=n)
            if etag and answer.get("etag") not in (None, etag):
                raise SyncError("changed")
            chunks = int(answer.get("chunks") or 1)
            pieces.append(decode_data(answer))
            n += 1
            if chunks > 100:
                raise SyncError("failed")
        return b"".join(pieces)

    # -- jobs --

    def sync_jobs(self) -> PartResult:
        self.progress.set("jobs")
        state = self.state.part("jobs")
        since = str(state.get("newest_created") or "") or None
        if since and not self.jobs_dir.is_dir():
            since = None  # the folder was lost: ask for everything again
        first = self.api.with_retries(
            lambda: self.api.call(part="jobs", a="manifest", since=since, limit=1)
        )
        if first.get("changed") is False:
            self.state.update("jobs", checked_at=_now(), ok_at=_now(), enabled=True)
            return PartResult("unchanged")
        # Only a first download knows how many files are coming (everything Google lists).
        listed = int(first.get("total_listed") or 0)
        self.progress.set("jobs", total=listed if since is None and listed else None)
        tmp = _temp_dir(self.root, "jobs")
        try:
            got = self.api.with_retries(lambda: self._jobs_pages(tmp, since))
            written = self._place_jobs(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        newest = max([str(state.get("newest_created") or ""), *(c for _, c in got)])
        self.state.update(
            "jobs", newest_created=newest, checked_at=_now(), ok_at=_now(), enabled=True,
            changed_at=_now() if written else state.get("changed_at"),
        )  # fmt: skip
        return PartResult("updated" if written else "unchanged", new_files=written)

    def _jobs_pages(self, tmp: Path, since: str | None) -> list[tuple[str, str]]:
        """All files newer than `since`, page by page (a page stops at 200 files or ~8 MB;
        `more` says there are older ones: ask again with before=<oldest included>)."""
        got: list[tuple[str, str]] = []
        seen: set[str] = set()
        before: str | None = None
        limit = JOB_PAGE
        for _ in range(MAX_PAGES):
            try:
                answer = self.api.call(
                    part="jobs", a="zip", since=since, before=before, limit=limit
                )
                if answer.get("changed") is False:  # nothing new after all: the answer has no data
                    break
                items, more, before = self._jobs_from_zip(tmp, answer)
            except SyncError as exc:
                if exc.kind != "too_big":
                    raise
                answer = self.api.call(
                    part="jobs", a="manifest", since=since, before=before, limit=limit
                )
                if answer.get("changed") is False:
                    break
                items = self._jobs_from_files(tmp, answer)
                more = bool(answer.get("more"))
                before = min((c for _, c in items), default=None)
            fresh = [i for i in items if i[0] not in seen]  # "before" is "at or before": the
            seen.update(path for path, _ in fresh)  # boundary file comes again; keep it once
            got += fresh
            self.progress.found = len(got)
            if not more or not before:
                break
            if not fresh:  # a page of files that all share one time: ask for a bigger page
                if limit >= MAX_LIMIT:
                    break
                limit = min(limit * 2, MAX_LIMIT)
        return got

    def _jobs_from_zip(
        self, tmp: Path, answer: dict
    ) -> tuple[list[tuple[str, str]], bool, str | None]:
        try:
            with zipfile.ZipFile(io.BytesIO(decode_data(answer))) as archive:
                listed = json.loads(archive.read("manifest.json")).get("files") or []
                items = [
                    self._take_job(tmp, f, archive.read(str(f.get("path", "")))) for f in listed
                ]
        except (zipfile.BadZipFile, ValueError, KeyError) as exc:
            raise SyncError("damaged") from exc
        return items, bool(answer.get("more")), str(answer.get("oldest_included") or "") or None

    def _jobs_from_files(self, tmp: Path, answer: dict) -> list[tuple[str, str]]:
        items = []
        for f in answer.get("files") or []:
            path = str(f.get("path", ""))
            if not JOB_PATH.fullmatch(path):
                raise SyncError("damaged")
            pieces, chunks, n = [], 1, 0
            while n < chunks:
                part = self.api.call(part="jobs", a="file", path=path, n=n)
                chunks = int(part.get("chunks") or 1)
                pieces.append(decode_data(part))
                n += 1
            items.append(self._take_job(tmp, f, b"".join(pieces)))
        return items

    @staticmethod
    def _take_job(tmp: Path, listed: dict, data: bytes) -> tuple[str, str]:
        """One job file into the temporary folder, checked against its manifest hash."""
        path, digest = str(listed.get("path", "")), str(listed.get("hash", ""))
        if not JOB_PATH.fullmatch(path) or not hmac.compare_digest(file_hash(data), digest):
            raise SyncError("damaged")
        _write(tmp, path, data)
        return path, str(listed.get("created") or "")

    def _place_jobs(self, tmp: Path) -> int:
        """Verified job files go flat into synced/jobs (the importer reads one folder). A
        file already there with the same content is skipped; a different file with the same
        name keeps both (the day folder is put in front of the new name)."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for source in sorted(p for p in tmp.rglob("*.txt") if p.is_file()):
            data = source.read_bytes()
            name = source.name
            dest = self.jobs_dir / name
            if dest.exists() and dest.read_bytes() != data:
                dest = self.jobs_dir / f"{source.parent.name}-{name}"
            if dest.exists():
                if dest.read_bytes() == data:
                    continue
                dest = self.jobs_dir / f"{file_hash(data)[:8]}-{name}"
            staged = self.jobs_dir / f".{uuid.uuid4().hex[:8]}.part"
            staged.write_bytes(data)
            os.replace(staged, dest)
            written += 1
        return written
