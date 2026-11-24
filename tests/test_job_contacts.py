"""Contact details and the collector's "why kept" / "fits" lines on jobs (paste files, jobs CSV,
normalizer), and the optional availability / profile_updated contractor columns."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from conftest import CONFIG_DIR
from jobmatch.normalize.pipeline import Normalizer
from jobmatch.schemas import ContractorProfile
from jobmatch.sources.contractor_upsert import read_contractor_file
from jobmatch.sources.job_csv import JobCsvError, read_job_csv
from jobmatch.sources.paste import PasteFormatError, parse_paste

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
COLLECTOR_FILE = """url: https://himalayas.app/companies/acme/jobs/analyst
title: Business Intelligence Analyst- 12-Month Contract
company: Acme
location: Remote - Canada
employment_type: Contractor
posted: 2026-11-18
# source: Himalayas (himalayas.app)
# why kept: title: analyst (low), remote in Canada, senior
# Fits: business intelligence (1)
---
12-month contract. Questions? Contact Jordan Lee at jordan.lee@acme.ca or 416-555-0100.
If you need an accommodation, call 888.692.2272.
Apply at https://acme.ca/careers/77
"""


def parse(text: str):  # noqa: ANN201
    return parse_paste(text, file_name="job.txt", fetched_at=NOW)


def test_collector_lines_are_kept_and_other_comments_still_skipped() -> None:
    raw, record = parse(COLLECTOR_FILE)
    assert raw.why_kept == "title: analyst (low), remote in Canada, senior"
    assert raw.fits_roles == "business intelligence (1)"
    assert "source" not in record.payload["fields"]
    plain, _ = parse(COLLECTOR_FILE.replace("# why kept", "# note").replace("# Fits", "# other"))
    assert plain.why_kept is None and plain.fits_roles is None


def test_repeated_label_in_the_collector_lines_is_stripped(tmp_path: Path) -> None:
    text = COLLECTOR_FILE.replace("# why kept: ", "# why kept: Why kept: ").replace(
        "# Fits: ", "# fits: Fits: "
    )
    raw, _ = parse(text)
    assert raw.why_kept == "title: analyst (low), remote in Canada, senior"
    assert raw.fits_roles == "business intelligence (1)"
    path = tmp_path / "jobs.csv"
    path.write_text(
        "url,job_title,why_kept,fits_roles\n"
        "https://example.ca/1,Analyst,Why kept: remote,Fits: sql (2)\n",
        encoding="utf-8",
    )
    [row] = read_job_csv(path, NOW)
    assert row.job is not None
    assert (row.job.why_kept, row.job.fits_roles) == ("remote", "sql (2)")


def test_paste_header_can_carry_contact_fields_but_unknown_fields_still_fail() -> None:
    raw, _ = parse(COLLECTOR_FILE.replace("posted:", "contact_phone: 647 555 0111\nposted:"))
    assert raw.contact_phone == "647 555 0111"
    with pytest.raises(PasteFormatError, match="unknown field"):
        parse(COLLECTOR_FILE.replace("posted:", "salary: 1\nposted:"))


def test_normalizer_finds_contact_and_keeps_the_collector_lines(normalizer: Normalizer) -> None:
    raw, _ = parse(COLLECTOR_FILE)
    job = normalizer.normalize(raw, now=NOW)
    assert (job.contact_person, job.contact_email) == ("Jordan Lee", "jordan.lee@acme.ca")
    assert job.contact_phone == "416-555-0100"  # not the accommodation line's number
    assert job.apply_url == "https://acme.ca/careers/77"
    assert job.why_kept == "title: analyst (low), remote in Canada, senior"
    assert job.fits_roles == "business intelligence (1)"
    typed, _ = parse(COLLECTOR_FILE.replace("posted:", "contact_email: Boss@Acme.ca\nposted:"))
    job = normalizer.normalize(typed, now=NOW)
    assert job.contact_email == "boss@acme.ca"
    assert job.contact_other_emails == ["jordan.lee@acme.ca"]


def test_jobs_csv_optional_columns(tmp_path: Path) -> None:
    path = tmp_path / "jobs.csv"
    path.write_text(
        "url,job_title,contact_phone,apply_url,why_kept,fits_roles\n"
        'https://example.ca/1,Analyst,613 555 0123,https://example.ca/apply,"remote, senior",'
        "Fits: sql (2)\nhttps://example.ca/2,Designer,,,,\n",
        encoding="utf-8",
    )
    first, second = (r.job for r in read_job_csv(path, NOW))
    assert first is not None and second is not None
    assert (first.contact_phone, first.apply_url) == ("613 555 0123", "https://example.ca/apply")
    assert (first.why_kept, first.fits_roles) == ("remote, senior", "sql (2)")
    assert (second.contact_phone, second.why_kept, second.fits_roles) == (None, None, None)


def test_jobs_csv_still_rejects_unknown_columns(tmp_path: Path) -> None:
    path = tmp_path / "jobs.csv"
    path.write_text("url,job_title,salary\nhttps://example.ca/1,Analyst,1\n", encoding="utf-8")
    with pytest.raises(JobCsvError, match="unknown column"):
        read_job_csv(path, NOW)


def one_contractor(tmp_path: Path, extra_header: str, extra_cells: str) -> ContractorProfile:
    path = tmp_path / "contractors.csv"
    path.write_text(
        f"talent_id,talent_name,rate_expectation{extra_header}\nTAL-1,Person One,90{extra_cells}\n",
        encoding="utf-8",
    )
    [profile] = read_contractor_file(path, config_dir=CONFIG_DIR, lock_timeout=5)
    return profile


def test_contractor_availability_and_profile_age_are_optional(tmp_path: Path) -> None:
    absent = one_contractor(tmp_path, "", "")
    assert (absent.availability, absent.profile_updated) == (None, None)
    both = ",availability,profile_updated"
    given = one_contractor(tmp_path, both, ",Available from 2026-12-01,2026-11-02")
    assert given.availability == "Available from 2026-12-01"
    assert given.profile_updated == date(2026, 11, 2)
    blank = one_contractor(tmp_path, both, ",,")
    assert (blank.availability, blank.profile_updated) == (None, None)


def test_an_apply_link_that_is_not_a_web_address_is_dropped(
    normalizer: Normalizer, tmp_path: Path
) -> None:
    raw, _ = parse(COLLECTOR_FILE.replace("posted:", "apply_url: javascript:alert(1)\nposted:"))
    assert raw.apply_url is None
    path = tmp_path / "jobs.csv"
    path.write_text(
        "url,job_title,apply_url\n"
        "https://example.ca/1,Analyst,file:///C:/secret.txt\n"
        "https://example.ca/2,Designer,HTTPS://example.ca/apply\n",
        encoding="utf-8",
    )
    first, second = (r.job for r in read_job_csv(path, NOW))
    assert first is not None and second is not None
    assert first.apply_url is None
    assert second.apply_url == "HTTPS://example.ca/apply"


def test_only_http_and_https_links_are_kept() -> None:
    from jobmatch.schemas import web_url_or_none

    assert web_url_or_none(" https://a.ca/x ") == "https://a.ca/x"
    assert web_url_or_none("HTTP://a.ca") == "HTTP://a.ca"
    for bad in ("javascript:alert(1)", "file:///C:/x", "data:text/html,x", "a.ca/apply", "", None):
        assert web_url_or_none(bad) is None
