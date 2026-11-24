"""Make sure the user always sees the app, even when the native window cannot start.

On Windows a download from a browser marks every file (Mark of the Web). pywebview/pythonnet
can then hang before the window exists: the server runs, nothing is shown, and every further
double-click starts another hidden copy. This module is the safety net, run in the server
process (the native helper is the part that hangs):

- ConnectionWatch / run_watch: if no page has connected a few seconds after start, open the
  app's address in the default browser (once). Once that happened ("browser fallback"), stop
  the app when the last page has been gone for a while, so no hidden copy is left behind.
  When the native window connects in time, nothing happens: the normal shutdown stays as is.
- ping_url / find_running_copy: a second start finds the copy that is already serving, opens
  it in the browser and exits instead of starting another server.

The timing logic takes an injectable clock, so the tests run without waiting.
"""

import logging
import multiprocessing
import os
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable

log = logging.getLogger(__name__)

BROWSER_AFTER = 12.0  # seconds without any connected page before the browser opens
IDLE_AFTER = 20.0  # browser fallback only: seconds without any page before the app stops
POLL_EVERY = 1.0
PING_PATH = "/__ping"
PING_TOKEN = "dogoodtalent-7f3a91c2"  # fixed text that says "this is the do good talent app"
PORT_RANGE = range(8000, 8020)  # NiceGUI's native mode takes the first free port from 8000

OPEN_BROWSER = "open_browser"
SHUTDOWN = "shutdown"

_fallback = False  # set once the browser was opened (read by the page builder)


def browser_fallback_active() -> bool:
    """True once the app was opened in the browser: pages then use browser-style pickers."""
    return _fallback


class ConnectionWatch:
    """Counts connected pages and says when to open the browser or stop (no I/O, no sleeping)."""

    def __init__(
        self,
        *,
        browser_after: float = BROWSER_AFTER,
        idle_after: float = IDLE_AFTER,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._browser_after = browser_after
        self._idle_after = idle_after
        self._clock = clock
        self._started = clock()
        self._live: dict[str, int] = {}  # client id -> open sockets
        self._ever_connected = False
        self._fallback = False
        self._empty_since: float | None = None

    @property
    def fallback(self) -> bool:
        return self._fallback

    @property
    def window_connected(self) -> bool:
        """A page connected in time: no fallback will ever be needed."""
        return self._ever_connected and not self._fallback

    def connected(self, client_id: str) -> None:
        self._ever_connected = True
        self._live[client_id] = self._live.get(client_id, 0) + 1

    def disconnected(self, client_id: str) -> None:
        left = self._live.get(client_id, 0) - 1
        if left > 0:
            self._live[client_id] = left
        else:
            self._live.pop(client_id, None)

    def poll(self) -> str | None:
        """OPEN_BROWSER (once), SHUTDOWN (only after the browser fallback), or None."""
        now = self._clock()
        if not self._fallback:
            if not self._ever_connected and now - self._started >= self._browser_after:
                self._fallback = True
                self._empty_since = now
                return OPEN_BROWSER
            return None
        if self._live:
            self._empty_since = None
        elif self._empty_since is None:
            self._empty_since = now
        elif now - self._empty_since >= self._idle_after:
            return SHUTDOWN
        return None


def run_watch(
    watch: ConnectionWatch,
    on_open_browser: Callable[[], None],
    on_shutdown: Callable[[], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_every: float = POLL_EVERY,
) -> None:
    """Poll the watch until it asks for a shutdown, or until it is clear no action can follow."""
    global _fallback  # noqa: PLW0603
    while True:
        action = watch.poll()
        if action == OPEN_BROWSER:
            _fallback = True
            on_open_browser()
        elif action == SHUTDOWN:
            on_shutdown()
            return
        elif watch.window_connected:
            return  # a window connected in time: the normal native shutdown takes it from here
        sleep(poll_every)


def local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def find_running_copy(
    fetch: Callable[[str], str | None] | None = None, ports: range = PORT_RANGE
) -> int | None:
    """The port of an already serving copy of this app (answers PING_TOKEN), else None."""
    fetch = fetch or _fetch
    for port in ports:
        if fetch(f"http://127.0.0.1:{port}{PING_PATH}") == PING_TOKEN:
            return port
    return None


def _fetch(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=0.3) as response:  # noqa: S310 (local http)
            return response.read(64).decode("ascii", "replace")
    except (OSError, ValueError):
        return None


def start_watch(
    watch: ConnectionWatch, port_getter: Callable[[], int | None], stop_app: Callable[[], None]
) -> None:
    """Start the watch thread (call once the server is up). Opens the browser and stops the
    app and its window helper as described in the module doc."""

    def open_browser() -> None:
        port = port_getter()
        log.warning("No app window connected: opening the app in the browser instead.")
        if port:
            webbrowser.open(local_url(port))

    def shutdown() -> None:
        log.warning("The browser page was closed: stopping the app.")
        stop_app()
        for child in multiprocessing.active_children():  # the (possibly hung) window helper
            child.terminate()
        time.sleep(5)
        os._exit(0)  # last resort: nothing may stay behind as a hidden copy

    threading.Thread(
        target=run_watch, args=(watch, open_browser, shutdown), daemon=True, name="window-watch"
    ).start()
