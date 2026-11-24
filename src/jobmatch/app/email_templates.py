"""Email texts for a match: one to the client (the company that posted the job) and one to the
contractor. Pure logic, no UI and no network; the app only shows these texts, a person copies
them or opens them in their own email program. The app never sends email.

Wording lives in config/email_templates.yaml. A template is plain text with `{field}` slots:
- a line whose slot has no data is dropped (never "None" or "{name}" in the email);
- `{field|fallback}` uses the fallback text instead of dropping the line (`{field|}`: empty).
Slots: see FIELDS_HELP. Missing or broken file: the built-in DEFAULT_TEMPLATES are used."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from jobmatch.llm.matches import MEETS_SEP

TEMPLATES_FILE = "email_templates.yaml"
MAILTO_LIMIT = 1800  # characters in the whole mailto: link; longer links fail in some programs
REASON_LIMIT = 420
CONTRACTOR_EMAIL_COLUMNS = ("email", "contractor_email", "contact_email")

FIELDS_HELP = (
    "client: {suggested} {contact_first} {contact_name} {job_title} {company} {at_company} "
    "{in_location} {link} {who} {contractor_blocks} {sender}; "
    "each contractor block: {name} {role} {name_role} {why} {highlights} (strengths only; "
    "{reason} is the same as {why}; {match_text} and {score} stay empty for a client); "
    "contractor: {first} {name} {role} {as_role} {job_title} {company} {at_company} {where} "
    "{link} {sender}"
)

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "client": {
        "subject": "{suggested} for {job_title}{at_company}",
        "body": (
            "Hello {contact_first|there},\n"
            "\n"
            "I am writing from do good, a talent company, about your {job_title} opening"
            "{at_company}{in_location}. I would like to suggest {who}.\n"
            "\n"
            "{contractor_blocks}\n"
            "\n"
            "Your posting: {link}\n"
            "\n"
            "If you would like to talk with them, reply to this email and I will set up an "
            "introduction.\n"
            "\n"
            "Best regards,\n"
            "{sender|The do good team}\n"
            "do good, a talent company"
        ),
        "contractor": "{name_role}\n{why}\n{highlights}",
    },
    "contractor": {
        "subject": "A contract that may suit you: {job_title}{at_company}",
        "body": (
            "Hello {first|there},\n"
            "\n"
            "I am writing from do good, a talent company. A contract has come up that looks "
            "like a good fit for your background{as_role}.\n"
            "\n"
            "Job: {job_title}\n"
            "Company: {company}\n"
            "Where: {where}\n"
            "Posting: {link}\n"
            "\n"
            "Are you interested, and are you available to start soon? If so, please reply and "
            "I will go over the next steps with you. If it is not for you, no problem, just "
            "let me know.\n"
            "\n"
            "Best regards,\n"
            "{sender|The do good team}\n"
            "do good, a talent company"
        ),
    },
}


def load_templates(config_dir: Path | None) -> dict[str, dict[str, str]]:
    """The texts from config/email_templates.yaml; every missing, empty or wrongly typed entry
    (or the whole file, when missing or unreadable) falls back to DEFAULT_TEMPLATES."""
    templates = {audience: dict(texts) for audience, texts in DEFAULT_TEMPLATES.items()}
    if config_dir is None:
        return templates
    try:
        raw = yaml.safe_load((Path(config_dir) / TEMPLATES_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return templates
    if not isinstance(raw, dict):
        return templates
    for audience, texts in templates.items():
        mine = raw.get(audience)
        if not isinstance(mine, dict):
            continue
        for key in texts:
            value = mine.get(key)
            if isinstance(value, str) and value.strip():
                texts[key] = value.strip()
    return templates


# ---- filling a template ----

_SLOT = re.compile(r"\{(\w+)(?:\|([^{}]*))?\}")
_OPTIONAL = {"at_company", "in_location", "as_role"}  # " at Fueled": empty is fine, line stays


def _fill_line(line: str, values: Mapping[str, str]) -> str | None:
    """The line with its slots filled, or None when a slot without fallback has no data."""
    missing = False

    def slot(m: re.Match[str]) -> str:
        nonlocal missing
        if m.group(1) in _OPTIONAL:
            return values.get(m.group(1), "")
        value = values.get(m.group(1), "").strip()
        if value:
            return value
        if m.group(2) is not None:
            return m.group(2)
        missing = True
        return ""

    done = _SLOT.sub(slot, line)
    return None if missing else done


def render(template: str, values: Mapping[str, str]) -> str:
    """Fill a template line by line (see the module note); no empty gaps, no unfilled slots."""
    lines: list[str] = []
    for line in template.splitlines():
        done = _fill_line(line.rstrip(), values)
        if done is None:
            continue
        done = done.rstrip()
        if not done and (not lines or not lines[-1]):
            continue
        lines.append(done)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


# ---- facts from the app's objects (Job, MatchView; read with getattr so they stay optional) ----

_MINOR = {"a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "de", "la", "le"}


def _text(value: object) -> str:
    value = getattr(value, "value", value)  # an Enum's text
    return " ".join(str(value).split()) if value is not None else ""


def _title(text: str) -> str:
    """ "senior data analyst" -> "Senior Data Analyst"; text that already has capitals is kept."""
    if text != text.lower():
        return text
    words = text.split()
    return " ".join(w if i and w in _MINOR else w.capitalize() for i, w in enumerate(words))


def _short(text: str, limit: int) -> str:
    """At most `limit` characters, cut at the end of a sentence or word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= limit // 2:
        return cut[: end + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _first_name(full: str) -> str:
    if "@" in full or not full:
        return ""
    return full.split()[0].strip(",.")


def _web_link(*candidates: object) -> str:
    for c in candidates:
        text = _text(c)
        if text.lower().startswith(("http://", "https://")):
            return text
    return ""


def _job_values(job: Any) -> dict[str, str]:
    title = _title(_text(getattr(job, "title_norm", None)) or _text(getattr(job, "title_raw", "")))
    company = _text(getattr(job, "company_raw", None)) or _text(getattr(job, "company_norm", None))
    location = _text(getattr(job, "location_raw", None)) or ", ".join(
        p for p in (_text(getattr(job, "city", None)), _text(getattr(job, "province", None))) if p
    )
    mode = {"remote": "remote", "hybrid": "hybrid", "onsite": "on-site"}.get(
        _text(getattr(job, "remote_type", None)), ""
    )
    remote_place = "remote" in location.lower()  # "Remote - Canada" already says it
    if location and mode and not remote_place:
        where = f"{location} ({mode})"
    else:
        where = location or mode.capitalize()
    contact = _text(getattr(job, "contact_person", None))
    return {
        "job_title": title,
        "company": company,
        "at_company": f" at {company}" if company else "",
        "in_location": f" in {location}" if location and not remote_place else "",
        "where": where,
        "contact_name": contact if "@" not in contact else "",
        "contact_first": _first_name(contact),
    }


def _match_text(verdict: str, score: object) -> str:
    base = "a strong match" if verdict == "fit" else "a partial match, worth a closer look"
    return base if score in (None, "") else f"{base} ({score} out of 100)"


def _person_values(view: Any) -> dict[str, str]:
    match = view.match
    name = _text(getattr(view, "name", None))
    role = _text(getattr(view, "headline", None))
    score = getattr(match, "fit_score", None)
    return {
        "name": name,
        "first": _first_name(name),
        "role": role,
        "as_role": f" as {role}" if role else "",
        "name_role": f"{name}, {role}" if name and role else name or role,
        "score": "" if score is None else str(score),
        "match_text": _match_text(_text(getattr(match, "verdict", "")), score),
        "reason": _short(_text(getattr(match, "reason", None)), REASON_LIMIT),
    }


# ---- what a client may read: strengths only ----
#
# The AI's "why" text mixes strengths with gaps ("lacks...", "rather than Toronto") and its flags
# carry field names ("missing_must_have: ..."). A client email never shows those: it is built from
# the requirements the person meets, plus the AI's sentences that hold no negative word. The full
# reasoning stays on screen for the reviewer.

_NEGATIVE = re.compile(
    r"\b(rather than|however|but|although|though|whereas|while|yet|lack\w*|miss\w*|no|not|"
    r"never|without|limited|only|basic|unfortunately|gap\w*|concern\w*|unclear|unknown|"
    r"unverified|despite|except|less|fewer|short|below|outside|relocat\w*|flag\w*|risk\w*|"
    r"weak\w*|insufficient|partial\w*|slight\w*|doesn't|isn't|cannot|can't|unable|"
    r"conflict\w*|mismatch\w*|score\w*)\b|\w+_\w+|\d+\s*(?:/|out of)\s*100",
    re.IGNORECASE,
)
HIGHLIGHTS = 4  # strengths listed for a client
SKILL_LIMIT = 80


def _positive_sentences(text: str) -> list[str]:
    """The sentences (and ; clauses) of `text` that hold no negative word."""
    parts = re.split(r"(?<=[.!?])\s+|;\s+", " ".join(text.split()))
    return [p.strip() for p in parts if p.strip() and not _NEGATIVE.search(p)]


def client_strengths(match: Any) -> tuple[str, str]:
    """(one clean lead sentence, a short bullet list of what the person meets); either may be
    empty. Built only from positives: never a gap, flag, score or field name."""
    lead = ""
    for sentence in _positive_sentences(_text(getattr(match, "reason", None))):
        lead = _short(sentence if sentence.endswith((".", "!", "?")) else sentence + ".", 220)
        break
    seen: set[str] = set()
    bullets: list[str] = []
    for item in getattr(match, "requirements_met", None) or []:
        skill, _, need = str(item).partition(MEETS_SEP)
        skill, need = " ".join(skill.split()), " ".join(need.split())
        pick = skill if skill and len(skill) <= SKILL_LIMIT else need or skill
        pick = _short(pick.rstrip("."), SKILL_LIMIT * 2)
        if not pick or _NEGATIVE.search(pick) or pick.casefold() in seen:
            continue
        seen.add(pick.casefold())
        bullets.append("- " + pick[0].upper() + pick[1:])
        if len(bullets) == HIGHLIGHTS:
            break
    return lead, ("Strengths:\n" + "\n".join(bullets)) if bullets else ""


def _client_person_values(view: Any) -> dict[str, str]:
    values = _person_values(view)
    lead, highlights = client_strengths(view.match)
    # An older template that still has {reason} gets the clean text; the match line stays empty.
    values.update(why=lead, highlights=highlights, reason=lead, match_text="", score="")
    return values


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


def client_email(
    job: Any,
    views: Sequence[Any],
    sender: str = "",
    templates: Mapping[str, Mapping[str, str]] | None = None,
) -> Email:
    """To the company that posted the job: pitches one or more matched contractors. `to` is
    the posting's contact email when known, else the first further address, else empty."""
    texts = (templates or DEFAULT_TEMPLATES)["client"]
    people = [_client_person_values(v) for v in views]
    names = [p["name"] for p in people if p["name"]]
    who = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
    values = {
        **_job_values(job),
        "suggested": "Suggested contractors" if len(people) > 1 else "Suggested contractor",
        "who": who,
        "link": _web_link(getattr(job, "url", None)),
        "sender": sender,
        "contractor_blocks": "\n\n".join(render(texts["contractor"], p) for p in people),
    }
    others = getattr(job, "contact_other_emails", None) or []
    to = _text(getattr(job, "contact_email", None)) or (_text(others[0]) if others else "")
    return Email(to, render(texts["subject"], values), render(texts["body"], values))


def contractor_email(
    job: Any,
    view: Any,
    sender: str = "",
    to: str = "",
    templates: Mapping[str, Mapping[str, str]] | None = None,
) -> Email:
    """To the contractor: tells them about the job and asks if they are interested and
    available. `to` is the contractor's email when the app has one (it usually does not)."""
    texts = (templates or DEFAULT_TEMPLATES)["contractor"]
    values = {
        **_job_values(job),
        **_person_values(view),
        "link": _web_link(getattr(job, "apply_url", None), getattr(job, "url", None)),
        "sender": sender,
    }
    return Email(to.strip(), render(texts["subject"], values), render(texts["body"], values))


def contractor_email_from(fields: Sequence[tuple[str, Sequence[str]]]) -> str:
    """An email column of the contractor's record (AppService.contractor_fields), if one ever
    exists; contractors.csv has none today."""
    for column, values in fields:
        if column in CONTRACTOR_EMAIL_COLUMNS and values and "@" in values[0]:
            return values[0].strip()
    return ""


# ---- output: clipboard text and mailto link ----


def copy_text(subject: str, body: str) -> str:
    return f"Subject: {subject}\n\n{body}"


def _encode(text: str) -> str:
    return quote(text.replace("\r\n", "\n").replace("\n", "\r\n"), safe="")


def mailto_url(to: str, subject: str, body: str, limit: int = MAILTO_LIMIT) -> tuple[str, bool]:
    """A mailto: link with encoded subject and body, body shortened until the whole link fits
    `limit` characters. Returns (link, shortened)."""
    head = f"mailto:{quote(to.strip(), safe='@,+')}?subject={_encode(subject[:200])}&body="
    shortened = False
    text = body
    while len(head) + len(_encode(text)) > limit and text:
        text = text[: int(len(text) * 0.9)].rstrip()
        shortened = True
    if shortened:
        text += "…"
    return head + _encode(text), shortened
