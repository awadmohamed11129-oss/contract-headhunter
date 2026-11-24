"""Get latest: the screen pieces of the do good link.

- the link field (Settings card, and the pop-up behind the first-run hint "Have a do good
  link?"): paste once with a Paste button, Test link says in plain words what it found, Save
  link keeps it like the Gemini key (only its last 4 characters are ever shown again);
- the plain words for Home: the Contractors / Jobs rows ("31 contractors, from your intake
  form, checked today 9:10 am") and the one calm line when the list could not be reached.

No download code is here (sync_client.py), and no secret ever reaches a label: the service
only hands out the hint "…a1b2".
"""

import inspect
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from nicegui import run, ui

from jobmatch.app.service import AppError, AppService, LatestStatus, LinkTest, PartStatus
from jobmatch.app.ui_help import help_icon, plain_when, plural
from jobmatch.sync_client import Progress

logger = logging.getLogger("jobmatch.app")

LINK_HELP = (
    "Your do good link brings your newest contractors and job files to this computer by "
    "itself. Copy it once from your contractor Sheet (menu: Contractor intake, then Set up). "
    "It is private: anyone who has it can download your list, so do not share it. Nothing "
    "is ever sent from this computer."
)
SOURCE = {"contractors": "your intake form", "jobs": "your job collector"}


def link_test_words(result: LinkTest) -> tuple[str, str]:
    """What Test link says: (tone, plain sentence). Tone: "positive" or "warning"."""
    if result.kind == "ok":
        if not result.people and not result.jobs:
            return "positive", "It works, but nobody is on the list yet."
        found = plural(result.people, "contractor")
        if result.jobs is None:
            return (
                "positive",
                f"It works. {found} found. Jobs are not switched on for this link yet.",
            )
        return "positive", f"It works. {found} and {plural(result.jobs, 'job')} found."
    return "warning", {
        "bad_link": "Your do good link was not recognised. Copy all of it again from your Sheet.",
        "offline": "No internet. Check your connection and try again.",
        "busy": "Your list is busy right now. Try again in a minute.",
    }.get(result.kind, "Could not check the link right now. Try again later.")


def progress_words(progress: Progress) -> str:
    """What the Get latest card says while it runs: "Getting your contractors… 3 found",
    "Getting your jobs… 40 of 71" (the total is only known on the first download)."""
    if progress.part == "contractors":
        found = f" {progress.found} found" if progress.found else ""
        return f"Getting your contractors…{found}"
    if progress.part == "jobs":
        if progress.total:
            return f"Getting your jobs… {min(progress.found, progress.total)} of {progress.total}"
        found = f" {progress.found} found so far" if progress.found else ""
        return f"Getting your jobs…{found}"
    if progress.part == "reading":
        return "Reading what arrived…"
    return "Getting your latest list…"


class LatestPanel:
    """The card on Home while Get latest runs: one plain sentence, a thin bar (the same look
    as the matching card, ui_progress.RunPanel). Home calls tick() on its timer."""

    def build(self) -> ui.column:
        with (
            ui.column().classes("dg-run w-full max-w-3xl mx-auto px-5 py-4 gap-2") as self.box,
        ):
            self.headline = ui.label().classes("text-base font-bold").mark("latest-headline")
            self.bar = ui.linear_progress(value=0, show_value=False).props("rounded size=8px")
            self.bar.classes("w-full")
            ui.label("You can keep using the app while this runs.").classes("text-sm text-grey-8")
        self.box.set_visibility(False)
        return self.box

    def tick(self, progress: Progress) -> None:
        self.headline.text = progress_words(progress)
        self.bar.value = progress.share


def short_day(when: datetime, now: datetime | None = None) -> str:
    """ "Nov 23" (with the year when it is not this year)."""
    local = when.astimezone() if when.tzinfo else when
    this_year = (now or datetime.now()).year
    return f"{local:%b} {local.day}" + ("" if local.year == this_year else f", {local.year}")


def calm_line(status: LatestStatus) -> str:
    """One quiet sentence when the last check could not finish; "" when all is well."""
    if not status.has_link or not status.problem or status.problem == "busy":
        return ""
    last = (
        f"showing the last copy from {short_day(status.last_ok_at)}"
        if status.last_ok_at
        else "nothing has been downloaded yet"
    )
    lead = {
        "offline": "Could not reach your list",
        "bad_link": "Your do good link is not recognised any more (paste a new one in Settings)",
    }.get(status.problem, "Could not get the latest right now")
    return f"{lead}, {last}."


def row_text(
    kind: str, count: int, part: PartStatus, linked: bool, updated: datetime | None
) -> str:
    """The Contractors / Jobs row: where it comes from and when it was checked."""
    text = plural(count, "contractor" if kind == "contractors" else "job")
    if linked and part.from_link:
        text += f", from {SOURCE[kind]}"
        if part.checked_at:
            text += f", checked {plain_when(part.checked_at)}"
    elif updated:
        text += f", updated {plain_when(updated)}"
    return text


# ---- the link field ----


def link_editor(
    service: AppService,
    *,
    on_saved: Callable[[], Any] | None = None,
    note: str = "",
) -> None:
    """Paste, Test link, Save link (and Remove link). Draws into the current container."""
    state = ui.label().classes("text-sm").mark("sync-link-state")

    def show_state() -> None:
        hint = service.sync_link_hint()
        state.text = (
            f"Your do good link is saved. It ends in {hint}." if hint else "No do good link yet."
        )
        remove.set_visibility(bool(hint))

    def say(tone: str, text: str) -> None:
        notice.clear()
        with notice, ui.row().classes("dg-attn items-center gap-2 w-full no-wrap"):
            ui.icon("check_circle" if tone == "positive" else "info", size="20px").classes(
                "text-positive" if tone == "positive" else "text-orange-9"
            )
            ui.label(text).classes("flex-1 text-sm")

    with ui.row().classes("w-full items-center gap-2 no-wrap"):
        field = (
            ui.input("Paste your do good link", password=True, password_toggle_button=True)
            .props('outlined dense placeholder="https://script.google.com/…"')
            .classes("flex-1")
            .mark("sync-link-input")
        )

        async def paste() -> None:
            try:
                text = await ui.run_javascript("navigator.clipboard.readText()", timeout=5.0)
            except Exception:  # noqa: BLE001 (no permission, or not a page that may read it)
                text = ""
            if text and str(text).strip():
                field.value = str(text).strip()
            else:
                say("warning", "Could not read what you copied. Click in the box and press Ctrl+V.")

        ui.button("Paste", icon="content_paste", on_click=paste).props(
            "outline dense no-caps"
        ).classes("bg-white").mark("sync-link-paste")

    async def test() -> None:
        text = (field.value or "").strip()
        if not text and not service.sync_link_hint():
            say("warning", "Paste your do good link first.")
            return
        test_button.props("loading")
        test_button.disable()
        try:
            result = await run.io_bound(service.test_sync_link, text or None)
        except Exception:  # noqa: BLE001 (details go to the log; never a stack trace on screen)
            logger.exception("link_test_failed")
            result = LinkTest(kind="failed")
        finally:
            test_button.props(remove="loading")
            test_button.enable()
        say(*link_test_words(result))

    async def save() -> None:
        try:
            service.save_sync_link(field.value or "")
        except AppError as exc:
            say("warning", str(exc))
            return
        field.value = ""
        show_state()
        say("positive", note or "Your do good link is saved.")
        if on_saved is not None:
            done = on_saved()
            if inspect.isawaitable(done):
                await done

    def forget() -> None:
        service.forget_sync_link()
        show_state()
        say(
            "positive",
            "Your do good link was removed. What was already downloaded stays on this computer.",
        )

    with ui.row().classes("items-center gap-2"):
        test_button = (
            ui.button("Test link", icon="network_check", on_click=test)
            .props("outline no-caps")
            .classes("bg-white")
            .mark("sync-link-test")
        )
        ui.button("Save link", icon="save", on_click=save).props(
            "unelevated no-caps color=primary"
        ).mark("sync-link-save")
        remove = (
            ui.button("Remove link", on_click=forget)
            .props("flat no-caps color=grey-8")
            .mark("sync-link-remove")
        )
    notice = ui.column().classes("w-full gap-1").mark("sync-link-notice")  # under the buttons
    field.on("keydown.enter", save)
    show_state()


def link_card(service: AppService) -> None:
    """Settings: "Your do good link"."""
    with ui.card().classes("w-full gap-2").mark("sync-link-card"):
        with ui.row().classes("items-center gap-1"):
            ui.label("Your do good link").classes("text-h6")
            help_icon(LINK_HELP, marker="sync-link-help")
        ui.label(
            "Paste it once. Your newest contractors and jobs then arrive by themselves."
        ).classes("text-sm text-grey-8")
        link_editor(
            service,
            note="Your do good link is saved. Open Home: your contractors and jobs load by "
            "themselves.",
        )


def link_dialog(page: ui.element, service: AppService, on_saved: Callable[[], Any]) -> None:
    """The first-run hint's pop-up (the same field)."""
    with (
        page,
        ui.dialog() as dialog,
        ui.card().classes("gap-2 w-[560px] max-w-full").mark("sync-link-dialog"),
    ):
        ui.label("Your do good link").classes("text-h6")
        ui.label("Paste it once. Your contractors and jobs then load by themselves.").classes(
            "text-sm text-grey-8"
        )

        async def saved() -> None:
            dialog.close()
            done = on_saved()
            if inspect.isawaitable(done):
                await done

        link_editor(service, on_saved=saved)
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=dialog.close).props("flat no-caps")
    dialog.on("hide", dialog.delete)
    dialog.open()
