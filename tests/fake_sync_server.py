"""A tiny fake of the Google side's download link (SYNC-CONTRACT.md), for tests and for looking
at the app without Google. Made-up data only. Not part of the app package.

In a test:

    server = FakeGoogle()
    server.set_people([("TAL-1", "Ann Example")])       # a contractors.csv + one PDF each
    server.add_job("2026-11-22-analyst.txt", "url: ...", created="2026-11-22T11:00:00.000Z")
    link = server.link                                   # http://127.0.0.1:<port>/macros/s/FAKE/exec?sync=<token>
    ...
    server.close()

From a shell (to run the app against it; the app needs JOBMATCH_DEV_ALLOW_LOCAL_SYNC=1):

    python tests/fake_sync_server.py --port 8099 --people-csv contractors.csv --resumes DIR \
        --jobs-dir DIR_WITH_TXT --extra-people 2

A control address (not part of the contract) lets a screenshot script change the world:
    /_ctl?down=1|0   drop every connection (the app sees "no internet")
    /_ctl?delay=3    wait this many seconds before every answer
    /_ctl?add_people=2   /_ctl?add_jobs=3   /_ctl?add_left_out=1
"""

import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import re
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TOKEN = "ab" * 31 + "cd"  # 64 hex characters, made up
ETAG = re.compile(r"[0-9a-fA-F]{64}")
KEY = b"resume-fingerprint-v1"
CSV_HEAD = [
    "talent_id", "talent_name", "location", "standardized_headline", "executive_summary",
    "core_strengths", "proof_points", "main_industry", "search_keywords", "seniority",
    "weekly_hours", "rate_expectation", "target_titles", "contract", "primary_profession",
    "secondary_professions", "years_experience", "languages", "availability", "profile_updated",
]  # fmt: skip


def person_row(talent_id: str, name: str) -> dict[str, str]:
    """A made-up person in the shape the intake export has."""
    return {
        "talent_id": talent_id, "talent_name": name, "location": "Ottawa, ON",
        "standardized_headline": "Data Analyst",
        "executive_summary": f"Made-up profile of {name}. Builds dashboards for public agencies.",
        "core_strengths": "Power BI|SQL|Reporting", "proof_points": "Cut reporting time by half.",
        "main_industry": "Public sector", "search_keywords": "Data Analyst|Power BI|SQL",
        "seniority": "mid", "weekly_hours": "24", "rate_expectation": "Industry Standard",
        "target_titles": "Data Analyst", "contract": "true",
        "primary_profession": "data analysis", "secondary_professions": "reporting",
        "years_experience": "5", "languages": "en|fr", "availability": "Available now",
        "profile_updated": "2026-11-20",
    }  # fmt: skip


def h(data: bytes) -> str:
    return hmac.new(KEY, data, hashlib.sha256).hexdigest()


def iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def pdf(text: str) -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n%%EOF\n"


def make_csv(rows: list[dict[str, str]], head: list[str] | None = None) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=head or CSV_HEAD, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


class FakeGoogle:
    def __init__(self, token: str = TOKEN, port: int = 0) -> None:
        self.token = token
        self.csv_bytes = b""
        self.head = CSV_HEAD
        self.rows: list[dict[str, str]] = []
        self.resumes: dict[str, bytes] = {}
        self.jobs: list[dict] = []  # path, created, data
        self.zip_available = True
        self.jobs_enabled = True
        self.chunk = 3_000_000
        self.busy = 0  # answer "busy" this many times
        self.changed_answers = 0  # answer "changed" this many times (the folder moved meanwhile)
        self.before_zip = None  # a function called just before a contractors zip is built
        self.corrupt: set[str] = set()  # paths whose bytes are served wrong (hash mismatch)
        self.down = False
        self.delay = 0.0
        self.log: list[dict[str, str]] = []  # every request's query (token left out)
        self.changed_at = datetime.now(UTC)
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer._handle(self)

            def log_message(self, *args: object) -> None:  # silence
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    # -- the world --

    @property
    def link(self) -> str:
        return f"http://127.0.0.1:{self.port}/macros/s/FAKE/exec?sync={self.token}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def set_people(self, people: list[tuple[str, str]], with_resume: bool = True) -> None:
        rows = [person_row(i, n) for i, n in people]
        self.set_rows(rows, CSV_HEAD)
        self.resumes = {i: pdf(f"resume of {n}") for i, n in people} if with_resume else {}

    def set_rows(self, rows: list[dict[str, str]], head: list[str]) -> None:
        self.rows, self.head = rows, head
        self.csv_bytes = make_csv(rows, head)
        self.changed_at = datetime.now(UTC)

    def add_person(self, talent_id: str, name: str) -> None:
        row = {k: person_row(talent_id, name).get(k, "") for k in self.head}
        self.set_rows([*self.rows, row], self.head)
        self.resumes[talent_id] = pdf(f"resume of {name}")

    def add_job(
        self, name: str, text: str, created: str | None = None, day: str | None = None
    ) -> None:
        created = created or iso(datetime.now(UTC))
        path = f"{day}/{name}" if day else name
        self.jobs.append({"path": path, "name": name, "created": created, "data": text.encode()})

    def files(self) -> dict[str, bytes]:
        return {"contractors.csv": self.csv_bytes} | {
            f"resumes/{i}.pdf": d for i, d in sorted(self.resumes.items())
        }

    def etag(self) -> str:
        digest = hashlib.sha256()
        for path, data in self.files().items():
            digest.update(f"{path}:{h(data)}".encode())
        return digest.hexdigest()

    # -- the contract --

    def _served(self, path: str, data: bytes) -> bytes:
        return data + b"X" if path in self.corrupt else data

    def _manifest(self) -> dict:
        files = self.files()
        total = sum(len(d) for d in files.values())
        return {
            "ok": True, "changed": True, "format": 1, "etag": self.etag(),
            "generated": iso(datetime.now(UTC)), "changed_at": iso(self.changed_at),
            "people": len(self.rows), "resumes": len(self.resumes), "no_resume": [],
            "total_bytes": total, "hash_method": "HMAC-SHA256",
            "zip_available": self.zip_available, "chunk_bytes": self.chunk,
            "jobs_available": self.jobs_enabled,
            "files": [{"path": p, "bytes": len(d), "hash": h(d)} for p, d in files.items()],
        }  # fmt: skip

    def _jobs_list(self, q: dict[str, str]) -> tuple[list[dict], bool]:
        listed = sorted(self.jobs, key=lambda j: j["created"], reverse=True)
        if q.get("since") and not ETAG.fullmatch(q["since"]):
            listed = [j for j in listed if j["created"] > q["since"]]  # strictly newer
        if q.get("before"):
            listed = [j for j in listed if j["created"] <= q["before"]]  # at or before
        limit = min(int(q.get("limit") or 200), 800)
        return listed[:limit], len(listed) > limit

    def _job_entry(self, j: dict) -> dict:
        return {
            "path": j["path"], "name": j["name"], "created": j["created"],
            "bytes": len(j["data"]), "hash": h(j["data"]),
        }  # fmt: skip

    def _answer(self, q: dict[str, str]) -> tuple[bytes, str]:
        """(body, content type)."""
        if q.get("sync") != self.token:
            return b"not found", "text/plain"
        if self.busy > 0:
            self.busy -= 1
            return _j({"ok": False, "error": "busy", "retry_after_seconds": 20}), "application/json"
        if self.changed_answers > 0 and q.get("a") in ("file", "zip"):
            self.changed_answers -= 1
            return _j(
                {"ok": False, "error": "changed", "retry_after_seconds": 20}
            ), "application/json"
        action, part = q.get("a", "manifest"), q.get("part", "contractors")
        if part == "jobs":
            return self._jobs(action, q), "application/json"
        if part != "contractors":
            return _j({"ok": False, "error": "unknown_part"}), "application/json"
        if not self.rows:
            return _j({"ok": False, "error": "no_data"}), "application/json"
        if action == "manifest":
            since = q.get("since")
            if since is not None:  # the etag and nothing else (contract, "Changes", 1)
                if not ETAG.fullmatch(since):
                    return _j({"ok": False, "error": "bad_since"}), "application/json"
                if since.lower() == self.etag():
                    return _j({"ok": True, "changed": False, "etag": self.etag(),
                               "generated": iso(datetime.now(UTC)),
                               "changed_at": iso(self.changed_at)}), "application/json"  # fmt: skip
            return _j(self._manifest()), "application/json"
        if action == "csv":
            return self._served("contractors.csv", self.csv_bytes), "text/plain; charset=utf-8"
        if action == "zip":
            if not self.zip_available:
                return _j({"ok": False, "error": "too_big"}), "application/json"
            if self.before_zip:
                self.before_zip()
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(self._manifest()))
                for path, data in self.files().items():
                    archive.writestr(path, self._served(path, data))
            raw = buffer.getvalue()
            answer = {"ok": True, "name": "contractors.zip", "etag": self.etag(), "bytes": len(raw)}
            answer |= {"encoding": "base64", "data": base64.b64encode(raw).decode()}
            return _j(answer), "application/json"
        if action == "file":
            path = f"resumes/{q.get('id', '')}.pdf"
            data = self.files().get(path)
            if data is None:
                return _j({"ok": False, "error": "no_such_file"}), "application/json"
            return self._piece(path, data, int(q.get("n") or 0)), "application/json"
        return _j({"ok": False, "error": "unknown_action"}), "application/json"

    def _piece(self, path: str, data: bytes, n: int, extra: dict | None = None) -> bytes:
        chunks = max(1, -(-len(data) // self.chunk))
        if n >= chunks:
            return _j({"ok": False, "error": "no_such_piece"})
        served = self._served(path, data)[n * self.chunk : (n + 1) * self.chunk]
        return _j({
            "ok": True, "path": path, "n": n, "chunks": chunks, "bytes": len(data), "hash": h(data),
            "etag": self.etag(), "encoding": "base64", "data": base64.b64encode(served).decode(),
            **(extra or {}),
        })  # fmt: skip

    def _jobs(self, action: str, q: dict[str, str]) -> bytes:
        if not self.jobs_enabled:
            return _j({"ok": False, "error": "no_jobs_folder"})
        etag = hashlib.sha256("".join(sorted(j["path"] for j in self.jobs)).encode()).hexdigest()
        files, more = self._jobs_list(q)
        base = {"ok": True, "part": "jobs", "etag": etag, "generated": iso(datetime.now(UTC)),
                "hash_method": "HMAC-SHA256", "total_seen": len(self.jobs),
                "total_listed": len(self.jobs), "truncated": False}  # fmt: skip
        nothing_new = bool(q.get("since")) and (q["since"].lower() == etag or not files)
        if action in ("manifest", "zip") and nothing_new:
            # One exact shape for "nothing new": ten keys, no files, no data (contract, Part 2)
            return _j({**base, "changed": False, "format": 1})
        if action == "manifest":
            return _j({**base, "changed": True, "format": 1, "count": len(files), "more": more,
                       "files": [self._job_entry(j) for j in files]})  # fmt: skip
        if action == "file":
            found = next((j for j in self.jobs if j["path"] == q.get("path")), None)
            if found is None:
                return _j({"ok": False, "error": "no_such_file"})
            return self._piece(found["path"], found["data"], int(q.get("n") or 0))
        if action == "zip":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(
                    {"files": [self._job_entry(j) for j in files]}))  # fmt: skip
                for j in files:
                    archive.writestr(j["path"], self._served(j["path"], j["data"]))
            raw = buffer.getvalue()
            return _j({**base, "changed": True, "name": "jobs.zip", "count": len(files),
                       "more": more, "oldest_included": files[-1]["created"] if files else None,
                       "bytes": len(raw), "encoding": "base64",
                       "data": base64.b64encode(raw).decode()})  # fmt: skip
        return _j({"ok": False, "error": "unknown_action"})

    def _handle(self, req: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(req.path)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if parts.path == "/_ctl":
            self._control(q)
            return self._send(req, b"ok", "text/plain")
        if self.down:
            req.close_connection = True
            return  # no answer at all
        with self._lock:
            self.log.append({k: v for k, v in q.items() if k != "sync"})
        if self.delay:
            time.sleep(self.delay)
        body, kind = self._answer(q)
        self._send(req, body, kind)

    @staticmethod
    def _send(req: BaseHTTPRequestHandler, body: bytes, kind: str) -> None:
        req.send_response(200)  # always 200, like Apps Script
        req.send_header("Content-Type", kind)
        req.send_header("Content-Length", str(len(body)))
        req.end_headers()
        req.wfile.write(body)

    def _control(self, q: dict[str, str]) -> None:
        if "down" in q:
            self.down = q["down"] == "1"
        if "delay" in q:
            self.delay = float(q["delay"])
        for _ in range(int(q.get("add_people", 0))):
            n = len(self.rows) + 1
            self.add_person(f"TAL-INT-ZZ-{n:03d}", f"Pat Placeholder {n}")
        # add_left_out=1: a job the app's importer leaves off its list (not in Canada)
        for k in range(int(q.get("add_jobs", 0)) + int(q.get("add_left_out", 0))):
            stamp = datetime.now(UTC)  # always newer than every job already listed
            if self.jobs:
                newest = max(j["created"] for j in self.jobs)
                last = datetime.strptime(newest, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
                stamp = max(stamp, last + timedelta(seconds=1))
            n = len(self.jobs) + 1
            text = job_text(n)
            if k >= int(q.get("add_jobs", 0)):
                text = text.replace("Remote - Canada", "Austin, Texas, USA").replace(
                    "remote in Canada", "on site in Texas"
                )
            self.add_job(f"{stamp:%Y-%m-%d}-made-up-role-{n}.txt", text, iso(stamp))


def _j(data: dict) -> bytes:
    return json.dumps(data).encode()


def job_text(n: int) -> str:
    """A job file in the collector's format (made-up company and role)."""
    return (
        f"url: https://jobs.example.com/{n}\n"
        f"title: Made-up Analyst {n} (6 month contract)\n"
        f"company: Example Company {n}\n"
        "location: Remote - Canada\nemployment_type: Contract\n"
        f"posted: {datetime.now(UTC):%Y-%m-%d}\n# source: made-up board\n---\n"
        f"The Role: made-up analyst work number {n}, six months, remote in Canada. "
        "Needs data analysis, dashboards and clear writing.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--token", default=TOKEN)
    parser.add_argument("--people-csv", type=Path, required=True)
    parser.add_argument("--resumes", type=Path)
    parser.add_argument("--jobs-dir", type=Path)
    parser.add_argument("--extra-people", type=int, default=0)
    parser.add_argument("--extra-jobs", type=int, default=0)
    args = parser.parse_args()
    server = FakeGoogle(args.token, args.port)
    with args.people_csv.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows, head = list(reader), list(reader.fieldnames or [])
    server.set_rows(rows, head)
    if args.resumes:
        server.resumes = {p.stem: p.read_bytes() for p in sorted(args.resumes.glob("*.pdf"))}
    if args.jobs_dir:
        for k, p in enumerate(sorted(args.jobs_dir.glob("*.txt"))):
            stamp = datetime.now(UTC) - timedelta(days=30 - k)
            server.add_job(p.name, p.read_text(encoding="utf-8"), iso(stamp))
    server._control({"add_people": str(args.extra_people), "add_jobs": str(args.extra_jobs)})
    print(f"fake do good link: {server.link}", flush=True)  # made-up token, local only
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.close()


if __name__ == "__main__":
    main()
