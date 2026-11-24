"""The "Write the email" pop-up on a match: an email to the client or to the contractor, filled
from the match, editable, to copy or open in the person's own email program. The app never
sends email."""

import json
from collections.abc import Sequence

from nicegui import ui

from jobmatch.app.email_templates import (
    Email,
    client_email,
    contractor_email,
    contractor_email_from,
    copy_text,
    load_templates,
    mailto_url,
)
from jobmatch.app.service import DEFAULT_REVIEWER, AppError, AppService, MatchView
from jobmatch.schemas import Job

AUDIENCES = {"client": "To the client", "contractor": "To the contractor"}
COPY_FAILED = "Could not copy. Select the text and copy it by hand."


async def copy_to_clipboard(text: str) -> bool:
    """Write to the clipboard and say whether the browser accepted it (it refuses outside
    a secure page, or when the person denies it)."""
    code = (
        "(async () => { try { await navigator.clipboard.writeText("
        + json.dumps(text)
        + "); return true; } catch (e) { return false; } })()"
    )
    try:
        return await ui.run_javascript(code, timeout=3.0) is True
    except Exception:  # noqa: BLE001 (no answer from the page counts as not copied)
        return False


def email_dialog(
    service: AppService, view: MatchView, job: Job, others: Sequence[MatchView] = ()
) -> None:
    """Open the pop-up for `view` on `job`. `others`: the other contractors shown on the same
    job card; they can be ticked to pitch several people to the client in one email."""
    templates = load_templates(service.settings.config_dir)
    reviewer = service.reviewer()
    sender = "" if reviewer == DEFAULT_REVIEWER else reviewer
    try:
        contractor_to = contractor_email_from(service.contractor_fields(view.match.talent_id))
    except AppError:
        contractor_to = ""
    pool = [view] + [o for o in others if o.match.match_id != view.match.match_id]
    ticked = {view.match.match_id}

    def draft() -> Email:
        if audience.value == "client":
            chosen = [v for v in pool if v.match.match_id in ticked]
            return client_email(job, chosen, sender, templates)
        return contractor_email(job, view, sender, contractor_to, templates)

    def fill() -> None:
        picks.set_visibility(audience.value == "client" and len(pool) > 1)
        email = draft()
        to.value, subject.value, body.value = email.to, email.subject, email.body
        if email.to:
            to_note.set_visibility(False)
        else:
            to_note_text.text = (
                f"No email address on file for {view.name or 'this contractor'}. "
                "Type one in here, or copy the text below."
                if audience.value == "contractor"
                else "The posting has no contact email. Type one in here, or copy the text below "
                "and use the apply link."
            )
            to_note.set_visibility(True)
        reasoning.set_visibility(audience.value == "client")

    def tick(match_id: str, on: bool) -> None:
        if on:
            ticked.add(match_id)
        else:
            ticked.discard(match_id)
        if ticked:
            fill()

    async def copy() -> None:
        if await copy_to_clipboard(copy_text(subject.value or "", body.value or "")):
            ui.notify("Copied", type="positive")
        else:
            ui.notify(COPY_FAILED, type="warning")

    def open_in_email_app() -> None:
        url, shortened = mailto_url(to.value or "", subject.value or "", body.value or "")
        ui.run_javascript(
            f"const a = document.createElement('a'); a.href = {json.dumps(url)}; a.click();"
        )
        if shortened:
            ui.notify(
                "The text was too long for the email program and was shortened there. "
                "Use Copy for the full text.",
                type="warning",
                multi_line=True,
            )

    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full gap-2") as card:
        card.mark("email-dialog")
        ui.label("Write the email").classes("text-h6")
        audience = ui.toggle(AUDIENCES, value="client", on_change=fill).props("no-caps")
        audience.mark("email-audience")
        with ui.row().classes("items-center gap-x-4") as picks:
            for v in pool:
                ui.checkbox(
                    v.name or v.match.talent_id,
                    value=v.match.match_id in ticked,
                    on_change=lambda e, mid=v.match.match_id: tick(mid, e.value),
                )
        to = ui.input("To").classes("w-full").props("outlined dense")
        to.mark("email-to")
        with ui.row().classes("items-center gap-1 no-wrap -mt-1") as to_note:
            ui.icon("info_outline", size="16px").classes("text-orange-9")
            to_note_text = ui.label().classes("text-sm text-orange-9").mark("email-to-note")
        subject = ui.input("Subject").classes("w-full").props("outlined dense")
        subject.mark("email-subject")
        body = (
            ui.textarea("Message")
            .classes("w-full")
            .props("outlined input-style='min-height: 16rem'")
        )
        body.mark("email-body")
        with (
            ui.expansion("What the AI said (not in this email)", icon="visibility_off")
            .props("dense")
            .classes("w-full text-sm text-grey-8 dg-reasoning") as reasoning
        ):
            m = view.match
            ui.label(m.reason or "No reason given.").classes("text-sm whitespace-pre-wrap")
            for title, items in (
                ("Missing", m.requirements_missing),
                ("Flags", m.red_flags),
            ):
                if items:
                    ui.label(title).classes("font-bold text-sm")
                    for item in items:
                        ui.label(f"• {item}").classes("text-sm")
            ui.label("Only the strengths go into the email to the client.").classes(
                "text-xs text-grey-7"
            )
        ui.label(
            "The app does not send email. Copy the text, or open it in your email program."
        ).classes("text-sm text-grey-7")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Close", on_click=dialog.close).props("flat no-caps")
            ui.button("Copy", icon="content_copy", on_click=copy).props("outline no-caps").mark(
                "email-copy"
            )
            ui.button(
                "Open in my email app", icon="mail_outline", on_click=open_in_email_app
            ).props("no-caps").mark("email-open")
    fill()
    dialog.on("hide", dialog.delete)
    dialog.open()
