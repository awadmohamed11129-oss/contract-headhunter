"""HR contact emails from posting text (TODO 1, user decisions 2026-11-10): English and
French postings, automated mailboxes skipped, masked before Gemini, filled for jobs stored
earlier. No network."""

from collections.abc import Callable

import pytest

from jobmatch.config import Settings
from jobmatch.llm.payload import job_card, render_job
from jobmatch.normalize.contact import contact_email, find_contact
from jobmatch.pipeline import fill_contact_emails
from jobmatch.schemas import Job
from jobmatch.storage.loader import create_loader


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please send your resume to Jane.Doe@Example-Insurance.ca by Friday.",
         "jane.doe@example-insurance.ca"),
        ("Faites parvenir votre CV à recrutement@ville.quebec.qc.ca avant le 30 novembre.",
         "recrutement@ville.quebec.qc.ca"),
        ("Questions? noreply@ats.com cannot answer; write to talent@acme.ca.", "talent@acme.ca"),
        ("Courriel : ne-pas-repondre@emploi.ca. Postulez via le portail.", None),
        ("<img src='logo@2x.png'> Apply online.", None),
        ("No email here, apply on our site.", None),
        ("", None),
    ],
)  # fmt: skip
def test_contact_email(text: str, expected: str | None) -> None:
    assert contact_email(text) == expected


def test_email_masked_for_gemini(app_settings: Settings, make_job: Callable[..., Job]) -> None:
    assert app_settings.llm is not None
    job = make_job(
        responsibilities=["Envoyer les rapports à marie.tremblay@ville.qc.ca chaque semaine"],
        contact_email="marie.tremblay@ville.qc.ca",
    )
    text = render_job(job_card(job, app_settings.llm.payload))
    assert "marie.tremblay" not in text and "[email]" in text


def test_jobs_stored_earlier_get_their_email(
    app_settings: Settings, make_job: Callable[..., Job]
) -> None:
    loader = create_loader(app_settings)
    loader.jobs.add_new([
        make_job(job_id="paste:1", source_id="1",
                 description_raw="Send your CV to hr@example.ca. Contract, 6 months."),
        make_job(job_id="paste:2", source_id="2", description_raw="Apply on our website."),
    ])  # fmt: skip
    assert fill_contact_emails(loader) == 1
    assert loader.jobs.get("paste:1").contact_email == "hr@example.ca"  # type: ignore[union-attr]
    assert fill_contact_emails(loader) == 0  # settled: nothing rewritten again


def test_cards_show_email_and_link_both_ways(app_settings, make_job, tmp_path) -> None:  # noqa: ANN001
    """TODO 1 and 2: the email row with its copy button, and See on Results / See on Jobs."""
    import asyncio

    from nicegui.testing.user_simulation import user_simulation

    from jobmatch.app.service import AppService
    from jobmatch.app.ui import build_root
    from test_talent import MarkerGemini

    loader = create_loader(app_settings)
    loader.jobs.add_new([
        make_job(job_id="paste:1", source_id="1", title_norm="Analyste de données (contrat)",
                 contact_email="recrutement@ville.qc.ca"),
        make_job(job_id="paste:2", source_id="2", title_norm="Data Analyst (contract)"),
    ])  # fmt: skip
    service = AppService(
        app_settings, tmp_path / "app.env", provider_factory=MarkerGemini, environ={}
    )

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/jobs")
        await user.should_see("recrutement@ville.qc.ca")
        await user.should_see("No contact email in the posting")
        await user.should_see(marker="copy-email:paste:1")
        user.find(marker="see-results:paste:1").click()
        await user.should_see("Results")
        await user.should_see(marker="see-jobs:paste:2")
        user.find(marker="see-jobs:paste:2").click()
        await user.should_see(marker="see-results:paste:2")

    async def main() -> None:
        async with user_simulation(root=build_root(service, native=False)) as user:
            await scenario(user)

    asyncio.run(main())


# ---- name, phone, apply link and more addresses (find_contact) ----


def test_find_contact_full_english_posting() -> None:
    text = (
        "Contract role, 6 months.\n"
        "Questions? Contact Jordan Lee at jordan.lee@acme.ca or 416-555-0100 ext. 23.\n"
        "Also copy hr@acme.ca. Apply online: https://careers.acme.ca/apply/77.\n"
        "Image: logo@2x.png. Privacy: privacy@acme.ca."
    )
    info = find_contact(text, posting_url="https://www.linkedin.com/jobs/view/1/")
    assert (info.person, info.email, info.other_emails) == (
        "Jordan Lee", "jordan.lee@acme.ca", ("hr@acme.ca",),
    )  # fmt: skip
    assert info.phone == "416-555-0100 ext. 23"
    assert info.apply_url == "https://careers.acme.ca/apply/77"


def test_find_contact_french_name_before_the_address() -> None:
    info = find_contact(
        "Envoyez votre CV à Marie Tremblay <marie.tremblay@ville.qc.ca>. Tél. 514 555 0188"
    )
    assert (info.person, info.email, info.phone) == (
        "Marie Tremblay", "marie.tremblay@ville.qc.ca", "514 555 0188",
    )  # fmt: skip


def test_find_contact_ignores_accommodation_lines_and_board_addresses() -> None:
    text = (
        "To request an accommodation please call 888.692.2272 or email accommodations@acme.com.\n"
        "Job board help: support@himalayas.app. Send questions to talent@acme.ca.\n"
        "Our privacy policy: https://acme.ca/privacy. Learn how we apply equal opportunity."
    )
    info = find_contact(text)
    assert (info.email, info.other_emails, info.phone, info.apply_url, info.person) == (
        "talent@acme.ca", (), None, None, None,
    )  # fmt: skip


def test_find_contact_apply_link_must_differ_from_the_posting() -> None:
    text = "Apply here: https://www.example.org/jobs/42/ or at https://apply.example.org/x?id=1"
    assert (
        find_contact(text, posting_url="https://example.org/jobs/42").apply_url
        == "https://apply.example.org/x?id=1"
    )
    only = "Apply here: https://example.org/jobs/42"
    assert find_contact(only, posting_url="https://example.org/jobs/42").apply_url is None


def test_find_contact_reads_html_links_and_does_not_guess_from_generic_addresses() -> None:
    html = (
        '<p>Please <a href="mailto:Sam.Roy@acme.ca">email us</a>.</p>'
        '<p><a href="https://acme.ca/apply">Apply now</a></p>'
    )
    info = find_contact(html)
    assert (info.email, info.person, info.apply_url) == (
        "sam.roy@acme.ca", "Sam Roy", "https://acme.ca/apply",
    )  # fmt: skip
    generic = find_contact("Write to careers@acme.ca or human.resources@acme.ca")
    assert generic.person is None and generic.other_emails == ("human.resources@acme.ca",)


@pytest.mark.parametrize(
    "text",
    [
        "We are looking for a Lifecycle Email Marketing Specialist to join the team.",
        "Role: Email Marketing Specialist. Contact Center experience is an asset.",
    ],
)
def test_a_job_title_is_never_a_contact_person(text: str) -> None:
    assert find_contact(text).person is None


def test_find_contact_labels_at_line_start_or_after_please() -> None:
    assert find_contact("Recruiter: Sarah Chen").person == "Sarah Chen"
    assert find_contact("Apply soon. Please contact Sarah Chen.").person == "Sarah Chen"


def test_find_contact_nothing_found() -> None:
    assert find_contact(None) == find_contact("No details, 2026-11-18, $29 - 31 CAD per hour.")


def test_stored_jobs_get_name_phone_and_link_too(
    app_settings: Settings, make_job: Callable[..., Job]
) -> None:
    loader = create_loader(app_settings)
    text = "Contact: Jordan Lee, jordan@acme.ca, 416-555-0100. Apply at https://acme.ca/a"
    loader.jobs.add_new([
        make_job(job_id="paste:1", source_id="1", contact_person="Typed Name",
                 description_raw=text),
    ])  # fmt: skip
    assert fill_contact_emails(loader) == 1
    job = loader.jobs.get("paste:1")
    assert job is not None
    assert (job.contact_person, job.contact_email) == ("Typed Name", "jordan@acme.ca")
    assert (job.contact_phone, job.apply_url) == ("416-555-0100", "https://acme.ca/a")
    assert fill_contact_emails(loader) == 0


@pytest.mark.parametrize(
    "text",
    [
        "Interested Candidates Contact: hr@acme.ca",
        "Submit Applications To: hr@acme.ca",
        "Attention To Detail is a must.\nSend your CV to hr@acme.ca",
    ],
)
def test_a_line_label_is_never_a_contact_person(text: str) -> None:
    assert find_contact(text).person is None


def test_a_name_before_the_address_still_works_without_a_colon() -> None:
    assert find_contact("Sarah Chen <sarah.chen@acme.ca>").person == "Sarah Chen"
