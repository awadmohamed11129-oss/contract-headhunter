"""Email texts for a match (WP4): filled from the match, no unfilled slots, editable wording in
config/email_templates.yaml with a safe fallback, and a mailto: link of a safe length."""

from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from jobmatch.app.email_templates import (
    DEFAULT_TEMPLATES,
    client_email,
    contractor_email,
    contractor_email_from,
    copy_text,
    load_templates,
    mailto_url,
    render,
)

CONFIG = Path(__file__).resolve().parent.parent / "config"


def job(**kw):
    base = dict(
        title_norm="senior content designer", title_raw="Senior Content Designer",
        company_raw="Fueled", company_norm=None, location_raw="Toronto, ON", city=None,
        province=None, remote_type=NS(value="remote"), url="https://example.com/jobs/1",
        apply_url=None, contact_person="Dana Whitfield", contact_email="dana@fueled.example",
        contact_other_emails=[],
    )  # fmt: skip
    return NS(**{**base, **kw})


def view(name="Hannah Brooks", headline="Senior Content Designer", score=98, verdict="fit",
         reason="Strong agency record. Led content modeling.", mid="m1"):  # fmt: skip
    match = NS(match_id=mid, talent_id="T1", fit_score=score, verdict=NS(value=verdict),
               reason=reason)  # fmt: skip
    return NS(match=match, name=name, headline=headline)


def clean(email):
    for text in (email.subject, email.body):
        assert "None" not in text and "{" not in text and "}" not in text
    assert "\n\n\n" not in email.body


def test_render_drops_lines_without_data_and_uses_fallbacks():
    values = {"a": "x", "b": ""}
    assert render("one {a}\ntwo {b}\nthree {b|none here}\nfour {zzz}", values) == (
        "one x\nthree none here"
    )
    assert render("top\n{b}\n\n\n{b}\nbottom {b|}", {"b": ""}) == "top\n\nbottom"


def test_client_email_full():
    email = client_email(job(), [view()], sender="Josh")
    clean(email)
    assert email.to == "dana@fueled.example"
    assert email.subject == "Suggested contractor for Senior Content Designer at Fueled"
    assert email.body.startswith("Hello Dana,")
    for part in ("Fueled in Toronto, ON", "Hannah Brooks, Senior Content Designer",
                 "Strong agency record.", "https://example.com/jobs/1",
                 "Josh\ndo good"):  # fmt: skip
        assert part in email.body
    assert "98" not in email.body and "Match:" not in email.body  # no score in a client email


def test_client_email_missing_data_is_dropped_never_printed():
    bare = job(company_raw=None, location_raw=None, remote_type=NS(value="unknown"),
               contact_person=None, contact_email=None, url="manual:abc")  # fmt: skip
    email = client_email(bare, [view(headline=None, score=None, reason=None)])
    clean(email)
    assert email.to == ""
    assert email.body.startswith("Hello there,")
    assert "Your posting" not in email.body and "Match:" not in email.body
    assert email.subject == "Suggested contractor for Senior Content Designer"
    assert "Best regards,\nThe do good team" in email.body


def test_client_email_several_contractors_and_other_contact_address():
    job2 = job(contact_email=None, contact_other_emails=["hr@fueled.example"])
    views = [view(), view("Ben Lee", "UX Writer", 91, "partial", mid="m2"),
             view("Cy Park", None, None, "fit", "", mid="m3")]  # fmt: skip
    email = client_email(job2, views)
    clean(email)
    assert email.to == "hr@fueled.example"
    assert email.subject.startswith("Suggested contractors for")
    assert "Hannah Brooks, Ben Lee and Cy Park" in email.body
    assert "Ben Lee, UX Writer" in email.body
    assert "partial" not in email.body and "91" not in email.body  # no verdict words or scores


def test_contractor_email():
    email = contractor_email(job(apply_url="https://example.com/apply"), view())
    clean(email)
    assert email.to == ""
    assert email.subject == "A contract that may suit you: Senior Content Designer at Fueled"
    for part in ("Hello Hannah,", "your background as Senior Content Designer.",
                 "Where: Toronto, ON (remote)", "Posting: https://example.com/apply",
                 "interested", "available"):  # fmt: skip
        assert part in email.body
    assert "98" not in email.body  # the score is for the client, not the contractor
    assert contractor_email(job(), view(), to=" h@x.example ").to == "h@x.example"


def test_contractor_email_with_little_data():
    email = contractor_email(job(company_raw=None, location_raw=None, url="manual:1"),
                             view(name=None, headline=None))  # fmt: skip
    clean(email)
    assert email.body.startswith("Hello there,")
    assert "Company:" not in email.body and "Posting:" not in email.body
    assert "your background." in email.body
    assert "Where: Remote" in email.body


def test_contractor_email_column():
    assert contractor_email_from([("talent_id", ["T1"]), ("email", ["a@b.example"])]) == (
        "a@b.example"
    )
    assert contractor_email_from([("talent_id", ["T1"]), ("email", [])]) == ""
    assert contractor_email_from([("talent_id", ["T1"])]) == ""


def test_templates_file_matches_built_in_defaults():
    assert load_templates(CONFIG) == DEFAULT_TEMPLATES


def test_templates_fall_back_when_file_missing_or_broken(tmp_path):
    assert load_templates(tmp_path) == DEFAULT_TEMPLATES
    assert load_templates(None) == DEFAULT_TEMPLATES
    (tmp_path / "email_templates.yaml").write_text("client: [unclosed", encoding="utf-8")
    assert load_templates(tmp_path) == DEFAULT_TEMPLATES
    (tmp_path / "email_templates.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    assert load_templates(tmp_path) == DEFAULT_TEMPLATES


def test_edited_wording_is_used_and_bad_entries_fall_back(tmp_path):
    custom = {"client": {"subject": "Hi {job_title}", "body": 5},
              "contractor": {"subject": "  ", "body": "Hey {first|you}"}}  # fmt: skip
    (tmp_path / "email_templates.yaml").write_text(yaml.safe_dump(custom), encoding="utf-8")
    templates = load_templates(tmp_path)
    assert client_email(job(), [view()], templates=templates).subject == (
        "Hi Senior Content Designer"
    )
    assert templates["client"]["body"] == DEFAULT_TEMPLATES["client"]["body"]
    assert contractor_email(job(), view(), templates=templates).body == "Hey Hannah"
    assert templates["contractor"]["subject"] == DEFAULT_TEMPLATES["contractor"]["subject"]


def test_mailto_is_encoded_and_round_trips():
    subject, body = "Fit: R&D #1", "Line one\nLine two é & more = ok?"
    url, shortened = mailto_url("a@b.example", subject, body)
    assert not shortened and url.startswith("mailto:a@b.example?")
    assert " " not in url and "\n" not in url
    query = parse_qs(urlsplit(url).query)
    assert query["subject"] == [subject]
    assert query["body"] == ["Line one\r\nLine two é & more = ok?"]
    assert mailto_url("", subject, body)[0].startswith("mailto:?subject=")


def test_mailto_is_trimmed_to_a_safe_length():
    long_body = "A fairly long sentence with é accents & symbols. " * 200
    url, shortened = mailto_url("a@b.example", "Subject", long_body, limit=1800)
    assert shortened and len(url) <= 1810
    assert unquote(url).endswith("…")
    assert not mailto_url("a@b.example", "S", "short")[1]


def test_copy_text():
    assert copy_text("Subj", "Body") == "Subject: Subj\n\nBody"


def test_remote_place_name_is_not_repeated():
    remote = job(location_raw="Remote - Canada")
    assert "Where: Remote - Canada\n" in contractor_email(remote, view()).body
    assert "opening at Fueled. I would" in client_email(remote, [view()]).body


def test_client_email_holds_only_strengths():
    """Gaps, flags and field names in the AI text never reach the client."""
    reason = (
        "Senior brand designer with ten years of experience creating identities. "
        "They meet all core requirements but are located in Victoria rather than Toronto for "
        "hybrid work."
    )
    match = NS(match_id="m9", talent_id="T9", fit_score=80, verdict=NS(value="fit"), reason=reason,
               requirements_met=["Brand identity \u2192 4+ years of brand design",
                                 "Packaging \u2192 label systems"],
               requirements_missing=["Hybrid in Toronto"],
               red_flags=["missing_must_have: Based in Victoria, BC."])  # fmt: skip
    email = client_email(job(), [NS(match=match, name="Chloe Martin", headline="Brand Designer")])
    body = email.body
    assert "ten years of experience creating identities." in body
    assert "- Brand identity" in body and "- Packaging" in body
    for bad in ("Victoria", "rather than", "missing_must_have", "Toronto for", "80", "flag"):
        assert bad not in body, bad
