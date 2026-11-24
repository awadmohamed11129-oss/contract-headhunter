"""Manual intake: one text file per posting, a short header, then the pasted posting text.

    url: https://www.linkedin.com/jobs/view/4012345678/
    title: Senior Business Analyst (12-month contract)
    company: Example Insurance Inc.
    location: Toronto, ON (Hybrid)
    employment_type:
    posted: 2026-10-18
    ---
    <pasted posting text>

Only `url` and `title` are required. With nothing after `---` the job is a stub
(status needs_details) to be completed later by pasting the text into the same file.
Optional header fields: contact_person, contact_email, contact_phone, apply_url (otherwise
found in the posting text). Lines starting with "#" in the header are comments, except the
job collector's two plain-words lines, which are kept: "# why kept: ..." and "# fits: ...".
No network access happens here.
"""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from jobmatch.schemas import RawJob, RawRecord

SEPARATOR = "---"
FIELDS = ("url", "title", "company", "location", "employment_type", "posted")
EXTRA_FIELDS = ("contact_person", "contact_email", "contact_phone", "apply_url")
# Comment lines the job collector writes: "# why kept: ..." -> why_kept, "# fits: ..." ->
# fits_roles.
_COLLECTOR_LINES = {"why_kept": "why kept", "fits_roles": "fits"}
_LABEL_PREFIX = re.compile(r"^(?:fits|why[ \t]+kept)[ \t]*:[ \t]*", re.IGNORECASE)
SOURCE_LINKEDIN = "manual_linkedin"
SOURCE_OTHER = "manual"

_LINKEDIN_VIEW = re.compile(r"/jobs/view/(?:[^/?#]*?-)?(\d{6,})")
_TRACKING_PARAMS = re.compile(r"^(utm_|trk|ref|refid|tracking)", re.IGNORECASE)


def collector_text(value: str) -> str:
    """A collector line without a repeated label: "Fits: sql (2)" -> "sql (2)"."""
    return _LABEL_PREFIX.sub("", value.strip(), count=1).strip()


class PasteFormatError(ValueError):
    """A paste file that cannot be read; the message says which line and why."""


def canonical_url(url: str) -> tuple[str, str, str]:
    """Return (source, source_id, canonical url) for a posting URL."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise PasteFormatError(f"url must start with http:// or https:// (got {url!r})")
    host = parts.netloc.lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        query = dict(parse_qsl(parts.query))
        view = _LINKEDIN_VIEW.search(parts.path)
        job_number = view.group(1) if view else query.get("currentJobId")
        if job_number and job_number.isdigit():
            return SOURCE_LINKEDIN, job_number, f"https://www.linkedin.com/jobs/view/{job_number}/"
    kept = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)]
    canonical = urlunsplit(
        (parts.scheme.lower(), host, parts.path.rstrip("/") or "/", urlencode(kept), "")
    )
    source = SOURCE_LINKEDIN if "linkedin.com" in host else SOURCE_OTHER
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return source, f"url-{digest}", canonical


def _parse_posted(value: str) -> datetime:
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            return datetime(day.year, day.month, day.day, tzinfo=UTC)
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PasteFormatError(f"posted must be a date like 2026-10-18 (got {value!r})") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_paste(text: str, *, file_name: str, fetched_at: datetime) -> tuple[RawJob, RawRecord]:
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    try:
        separator = next(i for i, line in enumerate(lines) if line.strip() == SEPARATOR)
    except StopIteration:
        raise PasteFormatError(
            f"missing the '{SEPARATOR}' line between the header and the posting text"
        ) from None

    fields: dict[str, str | None] = {}
    for number, line in enumerate(lines[:separator], start=1):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            label, _, value = line.lstrip().lstrip("#").partition(":")
            label = " ".join(label.lower().split())
            for field, name in _COLLECTOR_LINES.items():
                if label == name and value.strip():
                    fields[field] = collector_text(value) or None
            continue
        if ":" not in line:
            raise PasteFormatError(f"line {number}: expected 'field: value'")
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        if key not in FIELDS + EXTRA_FIELDS:
            raise PasteFormatError(
                f"line {number}: unknown field {key!r} (expected one of {', '.join(FIELDS)})"
            )
        fields[key] = value.strip() or None

    for required in ("url", "title"):
        if not fields.get(required):
            raise PasteFormatError(f"the '{required}' field is required")
    body = "\n".join(lines[separator + 1 :]).strip() or None
    source, source_id, url = canonical_url(fields["url"] or "")
    posted = fields.get("posted")

    try:
        raw_job = RawJob(
            source=source,
            source_id=source_id,
            url=url,
            title=fields["title"],
            company=fields.get("company"),
            location=fields.get("location"),
            description=body,
            employment_type=fields.get("employment_type"),
            posted_at=_parse_posted(posted) if posted else None,
            fetched_at=fetched_at,
            **{k: fields.get(k) for k in (*EXTRA_FIELDS, *_COLLECTOR_LINES)},
        )
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'posting'}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise PasteFormatError(problems) from None

    payload = {"file": file_name, "fields": fields, "text": body}
    record = RawRecord(
        source=source,
        source_id=source_id,
        fetched_at=fetched_at,
        content_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        payload=payload,
    )
    return raw_job, record


def read_paste_file(path: Path, *, fetched_at: datetime) -> tuple[RawJob, RawRecord]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PasteFormatError("file is not UTF-8 text; save it as UTF-8") from exc
    return parse_paste(text, file_name=path.name, fetched_at=fetched_at)
