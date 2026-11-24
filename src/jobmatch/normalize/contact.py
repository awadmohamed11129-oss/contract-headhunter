"""The HR or hiring contact, taken from the posting text (TODO 1, user decisions 2026-11-10;
name, phone and apply link added with the usability work).

Only what the posting itself says: nothing is looked up anywhere (CLAUDE.md rule 4). The
app shows and copies it; it never sends email (rule 5). Names, addresses and phone numbers are
personal data: they stay out of logs and out of what Gemini receives (llm/payload.py masks
addresses and phone numbers).

Rules (plain regex and line heuristics, no model):
- email: addresses in order of appearance, skipping automated or policy mailboxes
  (noreply@, privacy@, support@ …), file names that look like one (logo@2x.png), the job
  boards' own domains, and addresses on a line about accommodations or privacy. The first is
  `email`, the rest `other_emails` (at most three). Assumption: the first usable one is the
  application contact.
- person: a name (two or three capitalised words) after a label such as "Contact:",
  "Recruiter:", "Hiring manager:", "Questions? Contact …", "send your resume to …", or
  right before the address ("Jordan Lee <jordan@…>", "Jordan Lee at …"). Last resort: an
  address shaped first.last@ when neither part is a generic word.
- phone: North American numbers (416-555-0100, (416) 555 0100, +1 416.555.0100 x23), not on
  a line about accommodations, accessibility or fax.
- apply link: a URL on a line that talks about applying, when it is not the posting's own URL.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from jobmatch.normalize.text import looks_like_html, to_plain_text

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}", re.UNICODE)
_NOT_CONTACT = re.compile(
    r"^(?:no-?reply|do-?not-?reply|ne-?pas-?repondre|privacy|confidentialite|unsubscribe|"
    r"webmaster|postmaster|abuse|mailer-daemon|support|help|helpdesk|accommodations?|"
    r"accessibility|accessibilite)$",
    re.IGNORECASE,
)
_FILE_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
# The job boards' and applicant-tracking systems' own addresses say nothing about the job.
_BOARD_DOMAINS = (
    "himalayas.app", "jobicy.com", "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "workday.com", "myworkday.com", "smartrecruiters.com", "recruitee.com", "icims.com",
    "indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com", "sentry.io",
)  # fmt: skip
# A line with these words is about something else than applying (accommodation requests, privacy).
_OFF_TOPIC = re.compile(
    r"accommodat|accessib|disabilit|handicap|privacy|confidentialit|unsubscribe|"
    r"accommodement|adaptation|\bfax\b|\bTTY\b",
    re.IGNORECASE,
)

_WORD = r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]+"
_NAME = rf"(?:(?:Mr|Mrs|Ms|Mme|Dr)\.?[ \t]+)?({_WORD}(?:[ \t]+{_WORD}){{1,2}})"
# A label names the contact. Unambiguous phrases count anywhere; short words that also turn up
# in job titles ("Email Marketing Specialist", "Contact Center") only at the start of a line or
# sentence, or after "please".
_STRONG_LABEL = (
    r"(?i:contact[ \t]+(?:person|name)|recruiting[ \t]+contact|reach[ \t]+out[ \t]+to|"
    r"(?:send|submit|forward)[ \t]+(?:your[ \t]+)?(?:resume|cv|application)s?[ \t]+to|"
    r"personne[ \t-]+(?:ressource|contact)|contactez)"
)
_WEAK_LABEL = (
    r"(?:^|[.!?;:(][ \t]*|(?i:please)[ \t]+)"
    r"(?i:contact|recruiter|hiring[ \t]+(?:manager|contact)|ask[ \t]+for|attn|attention|"
    r"write[ \t]+to)"
)
_AFTER_LABEL = re.compile(
    rf"(?:{_STRONG_LABEL}|{_WEAK_LABEL})[ \t]*[:\-–]?[ \t]*{_NAME}", re.MULTILINE
)
_BEFORE_EMAIL = re.compile(rf"{_NAME}[ \t]*(?:[(<,–-]|\bat\b|\bà\b)[ \t]*(?:mailto:)?$")
_NOT_A_NAME = frozenset({
    "us", "information", "details", "our", "the", "team", "human", "resources", "hr",
    "recruitment", "recruiting", "talent", "acquisition", "careers", "department", "office",
    "centre", "center", "please", "email", "phone", "call", "apply", "now", "any", "your",
    "hiring", "manager", "recruiter", "people", "culture", "staffing", "agency", "services",
    "to", "send", "submit", "application", "applications", "candidate", "candidates",
    "interested", "contact", "resume", "resumes", "detail", "attention",
})  # fmt: skip
_GENERIC_LOCAL = frozenset({
    "careers", "career", "jobs", "job", "hr", "recruiting", "recruitment", "recrutement",
    "talent", "hiring", "info", "contact", "admin", "office", "team", "human", "people",
    "apply", "applications", "resume", "resumes", "cv", "emplois", "emploi", "rh",
})  # fmt: skip
_FIRST_LAST = re.compile(r"^([a-z]{2,})\.([a-z]{2,})$")

PHONE = re.compile(
    r"(?<![\w.])(?:\+?1[ \t.-]?)?(?:\(\d{3}\)[ \t]?|\d{3}[ \t.-])\d{3}[ \t.-]\d{4}"
    r"(?:[ \t]?(?:ext\.?|x|poste)[ \t]?\d{1,5})?(?!\w)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s<>\"'\])]+", re.IGNORECASE)
_APPLY_WORDS = re.compile(r"\bapply\b|\bapplication\b|postul|candidature", re.IGNORECASE)
_NOT_APPLY = re.compile(
    r"scam|equal opportunity|learn more|policy|terms|privacy|accommodat|accessib", re.IGNORECASE
)
_ANCHOR = re.compile(
    r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL
)
_MAX_OTHER_EMAILS = 3


@dataclass(frozen=True)
class ContactInfo:
    person: str | None = None
    email: str | None = None
    other_emails: tuple[str, ...] = ()
    phone: str | None = None
    apply_url: str | None = None


def _usable(address: str) -> bool:
    local, _, domain = address.lower().partition("@")
    return not (
        _NOT_CONTACT.match(local)
        or address.lower().endswith(_FILE_ENDINGS)
        or any(domain == d or domain.endswith("." + d) for d in _BOARD_DOMAINS)
    )


def contact_email(text: str | None) -> str | None:
    """The posting's contact email, lower-cased, or None."""
    return find_contact(text).email if text else None


def _plain(text: str) -> str:
    """Posting text as plain lines; a link keeps its address next to its words."""
    if not looks_like_html(text):
        return text
    return to_plain_text(_ANCHOR.sub(lambda m: f"{m.group(2)} {m.group(1)} ", text))


def _name_ok(name: str) -> bool:
    return not any(w.casefold().strip("'’-") in _NOT_A_NAME for w in name.split())


def _person(text: str, email: str | None, before: str) -> str | None:
    for found in _AFTER_LABEL.finditer(text):
        if _name_ok(found.group(1)):
            return found.group(1)
    if before:
        found = _BEFORE_EMAIL.search(before)
        if found and _name_ok(found.group(1)):
            return found.group(1)
    if email:
        parts = _FIRST_LAST.match(email.split("@", 1)[0])
        if parts and not set(parts.groups()) & _GENERIC_LOCAL:
            return " ".join(p.capitalize() for p in parts.groups())
    return None


def _same_page(a: str, b: str) -> bool:
    def key(url: str) -> tuple[str, str]:
        parts = urlsplit(url.strip().lower())
        return parts.netloc.removeprefix("www."), parts.path.rstrip("/")

    return key(a) == key(b)


def find_contact(text: str | None, *, posting_url: str | None = None) -> ContactInfo:
    """Everything the posting says about who to contact and where to apply. Plain text
    or HTML in; nothing is looked up. Empty fields where the text says nothing."""
    if not text:
        return ContactInfo()
    text = _plain(text)
    emails: list[str] = []
    before = ""
    for found in EMAIL.finditer(text):
        address = found.group(0).strip(".")
        line_start = text.rfind("\n", 0, found.start()) + 1
        line_end = text.find("\n", found.end())
        line = text[line_start : line_end if line_end >= 0 else len(text)]
        if not _usable(address) or _OFF_TOPIC.search(line):
            continue
        if address.lower() not in emails:
            if not emails:
                before = text[line_start : found.start()]
            emails.append(address.lower())
    phone = apply_url = None
    for line in text.split("\n"):
        if phone is None and not _OFF_TOPIC.search(line):
            found = PHONE.search(line)
            if found:
                phone = " ".join(found.group(0).split())
        if apply_url is None and _APPLY_WORDS.search(line) and not _NOT_APPLY.search(line):
            for url in _URL.findall(line):
                url = url.rstrip(".,;:!?")
                if not posting_url or not _same_page(url, posting_url):
                    apply_url = url
                    break
    first = emails[0] if emails else None
    return ContactInfo(
        person=_person(text, first, before),
        email=first,
        other_emails=tuple(emails[1 : 1 + _MAX_OTHER_EMAILS]),
        phone=phone,
        apply_url=apply_url,
    )
