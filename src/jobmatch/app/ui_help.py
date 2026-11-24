"""Small, reusable UI pieces for the screens in ui.py and ui_home.py (NiceGUI):

- plain words:   plural(), classify_failure()
- "?" help:      help_icon()
- failures:      failure_card()   a plain message with a "Try again" button
- undo toast:    toast()          a message with one action button (Undo, See results…)
- plain dates:   plain_when(), plain_day(), plain_dates_in()   "today 9:12 am", "Dec 26, 2026"
- drag and drop: window_drop()    drop files anywhere on the window

Nothing here knows about the service: every function takes plain values and callbacks, so
the screens stay thin and this file can be read on its own.
"""

import contextlib
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from nicegui import app as nicegui_app
from nicegui import context, ui
from nicegui.events import UploadEventArguments

# ---- styles shared by the new pieces (added once, with the app's own CSS) ----

HELP_CSS = """
.dg-toast { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
  z-index: 9000; background: #2A1F4D; color: #fff; border-radius: 1rem;
  padding: 10px 14px 10px 18px;
  box-shadow: 0 10px 30px rgba(30,20,70,.35); max-width: min(92vw, 560px);
  animation: toast-in .25s ease both; }
@keyframes toast-in { from { opacity: 0; transform: translate(-50%, 12px); } }
.dg-toast .q-btn { font-weight: 700; }
.dg-toast.top { bottom: auto; top: 86px; animation-name: toast-in-top; }
@keyframes toast-in-top { from { opacity: 0; transform: translate(-50%, -12px); } }
.dg-new { font-size: 11px; font-weight: 800; letter-spacing: .02em; color: #fff;
  background: #7E4891; border-radius: 9999px; padding: 1px 8px; line-height: 1.5; }
.dg-new-tag { font-size: 11px; font-weight: 700; color: #4B3499; background: #E9DFFB;
  border: 1.5px solid #CFC2EE; border-radius: 9999px; padding: 0 8px; line-height: 1.5; }
.dg-help-pop { max-width: 340px; padding: 12px 14px; font-size: 14px; line-height: 1.45; }
.dg-veil { position: fixed; inset: 0; z-index: 8000; display: none; align-items: center;
  justify-content: center; background: rgba(60,40,120,.55); backdrop-filter: blur(3px);
  pointer-events: none; }
.dg-veil.on { display: flex; }
.dg-veil > div { border: 3px dashed #fff; border-radius: 2rem; padding: 48px 64px; color: #fff;
  font-size: 26px; font-weight: 800; text-align: center; background: rgba(255,255,255,.08); }
.dg-veil small { display: block; margin-top: 8px; font-size: 14px; font-weight: 500; opacity: .9; }
.dg-fail { border: 2px solid #F0BFC4 !important; background: #FFF6F7; }
"""


# ---- plain dates: never "2026-12-26" on a screen ----


def plain_day(d: date | datetime) -> str:
    """ "Dec 26, 2026"."""
    return f"{d:%b} {d.day}, {d.year}"


def _clock(when: datetime) -> str:
    hour = when.hour % 12 or 12
    return f"{hour}:{when.minute:02d} {'am' if when.hour < 12 else 'pm'}"


def plain_when(when: datetime, now: datetime | None = None) -> str:
    """A moment in everyday words, in the computer's own time zone: "today 9:12 am",
    "yesterday 4:05 pm", or "Dec 26, 2026" for anything older."""
    local = when.astimezone() if when.tzinfo else when
    today = (now.astimezone() if now is not None and now.tzinfo else now or datetime.now()).date()
    days = (today - local.date()).days
    if days == 0:
        return f"today {_clock(local)}"
    if days == 1:
        return f"yesterday {_clock(local)}"
    return plain_day(local)


_ISO_DAY = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def plain_dates_in(text: str) -> str:
    """Every 2026-12-26 inside a text (a profile's own words, say "Available from 2026-12-26")
    becomes "Dec 26, 2026"; anything that is not a real date is left as written."""

    def one(m: re.Match[str]) -> str:
        try:
            return plain_day(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return m.group(0)

    return _ISO_DAY.sub(one, text)


def plural(n: int, one: str, many: str | None = None) -> str:
    """ "1 job", "3 jobs" (everyday words instead of "job(s)")."""
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ---- "?" help icons: a short explanation in a small pop-up instead of a long paragraph ----


def help_icon(text: str, *, marker: str = "help") -> ui.button:
    """A small round "?" that opens a short explanation when clicked."""
    with (
        ui.button(icon="help_outline")
        .props('flat round dense size=sm color=grey-7 aria-label="What is this?"')
        .classes("dg-help")
        .mark(marker)
        .tooltip("What is this?") as button,
        ui.menu().props("anchor='bottom middle' self='top middle'"),
    ):
        ui.label(text).classes("dg-help-pop")
    return button


# The existing explanation of the Gemini key (Settings), also opened from Home.
KEY_HELP = (
    "A free key from Google AI Studio. It stays on this computer and is never "
    "shown again after you save it."
)
KEY_URL = "https://aistudio.google.com/apikey"
# The page and button names are the ones doc/FIRST_LAUNCH.md already tells the person to use.
KEY_STEPS = (
    (1, "Open Google AI Studio (aistudio.google.com) and sign in with your Google account."),
    (2, "Click Get API key, then Create API key."),
    (3, "Copy the key, come back here and paste it."),
)


# ---- plain failure messages ----

# (words to look for in the raw message, short title, what to do). First match wins.
_FAILURES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("add your gemini key", "no gemini key"),
        "There is no Gemini key yet.",
        "Add it in Settings, then try again.",
    ),
    (
        ("api key", "api_key", "401", "403", "permission denied", "unauthenticated"),
        "Gemini did not accept the key.",
        "Check or paste the key again in Settings.",
    ),
    (
        ("quota", "429", "rate limit", "exhausted"),
        "Gemini is out of free requests for today.",
        "Try again tomorrow, or later when the limit resets.",
    ),
    (
        ("connect", "network", "timed out", "timeout", "resolve", "unreachable", "ssl"),
        "The app could not reach Gemini.",
        "Check the internet connection, then try again.",
    ),
    (
        ("another run is in progress",),
        "Another search is still running.",
        "Wait until it ends, then try again.",
    ),
    (
        ("no contractor list", "contractor list yet"),
        "There are no contractors yet.",
        "Add your contractors first, then try again.",
    ),
]


def classify_failure(raw: str, what: str = "This did not work.") -> tuple[str, str]:
    """A plain title and a next step for a raw error text."""
    low = raw.casefold()
    for words, title, hint in _FAILURES:
        if any(w in low for w in words):
            return title, hint
    short = raw.strip().splitlines()[0] if raw.strip() else ""
    if 0 < len(short) <= 220:
        return what, short  # the app's own message is already in plain words
    return what, "Nothing was lost. You can try again."


def failure_card(
    raw: str,
    on_retry: Callable[[], object] | None = None,
    *,
    what: str = "This did not work.",
    retry_label: str = "Try again",
) -> ui.column:
    """A calm message in plain words, a "Try again" button and the original text one click
    away (Show details). Build it inside the container that should hold it."""
    title, hint = classify_failure(raw, what)
    with ui.card().classes("dg-fail w-full gap-1").mark("failure-card") as card:
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.icon("error_outline", size="22px").classes("text-negative")
            ui.label(title).classes("font-bold").mark("failure-title")
        ui.label(hint).classes("text-sm text-grey-9")
        with ui.row().classes("items-center gap-2"):
            if on_retry is not None:
                ui.button(retry_label, icon="refresh", on_click=on_retry).props(
                    "unelevated no-caps color=primary"
                ).mark("try-again")
        if hint != raw.strip():
            with ui.expansion("Show details").props("dense").classes("text-xs text-grey-7 w-full"):
                ui.label(raw).classes("font-mono text-xs whitespace-pre-wrap")
    return card


# ---- "see why": a short list of what was left out, and the reason for each ----


def reasons_dialog(title: str, intro: str, rows: list[tuple[str, str]]) -> None:
    """A pop-up listing (what, why) pairs. Opened from a quiet "see why" link."""
    with ui.dialog() as dialog, ui.card().classes("gap-2 w-[560px] max-w-full").mark("reasons"):
        ui.label(title).classes("text-h6")
        ui.label(intro).classes("text-sm text-grey-8")
        with ui.column().classes("w-full gap-2 max-h-[50vh] overflow-auto"):
            for what, why in rows:
                with (
                    ui.column()
                    .classes("w-full gap-0")
                    .style(
                        "background:#FBFAFE;border:1.5px solid #E4DFF3;border-radius:1rem;"
                        "padding:8px 14px"
                    )
                ):
                    ui.label(what).classes("text-sm font-medium")
                    if why:
                        ui.label(why).classes("text-sm text-grey-8")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=dialog.close).props("flat no-caps")
    dialog.on("hide", dialog.delete)
    dialog.open()


def left_out_dialog(left: list) -> None:
    """Which jobs the import left off the list, and why (items with title, company, reason)."""
    reasons_dialog(
        "Jobs left out",
        "These were read, but they are not on your list of jobs, so they are not matched.",
        [(j.title + (f" · {j.company}" if j.company else ""), j.reason) for j in left],
    )


# ---- toast with one action (Undo, See results…) ----

_TOAST_KEY = "dg_toast"


def toast(
    message: str,
    action: str | None = None,
    on_action: Callable[[], object] | None = None,
    *,
    seconds: float = 8,
    icon: str = "check_circle",
    marker: str = "toast",
    extra: str | None = None,
    on_extra: Callable[[], object] | None = None,
    parent: ui.element | None = None,
    top: bool = False,
) -> None:
    """A short message at the bottom of the window with one button (and, if given, a second
    one: `extra`, e.g. "Write the email"). One at a time: a new
    toast replaces the old one. It lives on the page's layout, so redrawing a card (which
    deletes the card's own elements) never removes it. `parent`: put it inside a screen's own
    element instead, so it goes away when that screen is left (Review mode). `top`: show it at
    the top of the window, where it never covers a screen's buttons (Review mode)."""
    store = nicegui_app.storage.client
    old = store.pop(_TOAST_KEY, None)
    if old is not None:
        with contextlib.suppress(Exception):  # already gone with its page
            old.delete()

    with (
        parent or context.client.layout,
        ui.row().classes("dg-toast items-center no-wrap gap-3" + (" top" if top else "")) as box,
    ):
        box.mark(marker)
        ui.icon(icon, size="20px").classes("text-green-3")
        ui.label(message).classes("text-sm")

        def go() -> None:
            box.delete()
            store.pop(_TOAST_KEY, None)
            if on_action is not None:
                on_action()

        def go_extra() -> None:
            box.delete()
            store.pop(_TOAST_KEY, None)
            if on_extra is not None:
                on_extra()

        if action:
            ui.button(action, on_click=go).props("flat no-caps dense color=white").mark(
                f"{marker}-action"
            )
        if extra:
            ui.button(extra, on_click=go_extra, color=None).props(
                "unelevated no-caps dense"
            ).classes("px-3").style("background: #fff; color: #593B9D;").mark(f"{marker}-extra")
        ui.button(icon="close", on_click=box.delete).props(
            'flat round dense size=sm color=white aria-label="Close"'
        ).tooltip("Close")
        ui.timer(seconds, box.delete, once=True)
    store[_TOAST_KEY] = box


def dismiss_toast() -> None:
    """Remove the toast now on screen, if any (e.g. after its action was done another way)."""
    old = nicegui_app.storage.client.pop(_TOAST_KEY, None)
    if old is not None:
        with contextlib.suppress(Exception):
            old.delete()


def undo_toast(message: str, undo: Callable[[], object], *, seconds: float = 8) -> None:
    """After approve / reject / remove style actions: say what happened, offer Undo."""
    toast(message, "Undo", undo, seconds=seconds, marker="undo-toast")


# ---- drag and drop: drop files anywhere on the window ----

_DROP_JS = """
(() => {
  const state = window.__dgDrop || (window.__dgDrop = {depth: 0, target: null});
  if (!state.veil) {
    const veil = document.createElement('div');
    veil.className = 'dg-veil';
    veil.innerHTML = '<div>Drop your files here<small>VEIL_HINT</small></div>';
    document.body.appendChild(veil);
    state.veil = veil;
    const files = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files');
    window.addEventListener('dragenter', (e) => {
      if (!files(e)) return;
      e.preventDefault();
      state.depth += 1;
      if (state.target) veil.classList.add('on');
    });
    window.addEventListener('dragover', (e) => { if (files(e)) e.preventDefault(); });
    window.addEventListener('dragleave', (e) => {
      if (!files(e)) return;
      state.depth = Math.max(0, state.depth - 1);
      if (!state.depth) veil.classList.remove('on');
    });
    window.addEventListener('drop', (e) => {
      if (!files(e)) return;
      e.preventDefault();
      state.depth = 0;
      veil.classList.remove('on');
      if (state.target) { try { state.target(e.dataTransfer.files); } catch (_) {} }
    });
  }
  state.veil.querySelector('small').textContent = 'VEIL_HINT';
  state.target = (files) => getElement(UPLOAD_ID).$refs.qRef.addFiles(files);
})();
"""


def window_drop(
    on_file: Callable[[str, bytes], Awaitable[None] | None],
    *,
    hint: str = "Contractor list (.csv, .xlsx, .zip) or job files (.txt, .csv, .pdf, .html)",
) -> ui.upload:
    """Let the person drop files anywhere on the window. A hidden upload box receives them
    (the same way the buttons' browser chooser does); `on_file(name, data)` is called once per
    file, in order. Build it inside the page that should accept drops."""

    async def uploaded(e: UploadEventArguments) -> None:
        result = on_file(e.file.name, await e.file.read())
        if result is not None:
            await result

    upload = (
        ui.upload(on_upload=uploaded, auto_upload=True, multiple=True)
        .classes("hidden")
        .mark("window-drop-upload")
    )
    js = _DROP_JS.replace("UPLOAD_ID", str(upload.id)).replace("VEIL_HINT", hint)
    ui.timer(0.2, lambda: ui.run_javascript(js), once=True)
    return upload
