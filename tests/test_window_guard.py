"""Browser fallback and idle shutdown (jobmatch.app.window_guard): fake clock, no browser."""

from jobmatch.app import window_guard
from jobmatch.app.window_guard import (
    OPEN_BROWSER,
    PING_TOKEN,
    SHUTDOWN,
    ConnectionWatch,
    find_running_copy,
    run_watch,
)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_watch(clock: Clock) -> ConnectionWatch:
    return ConnectionWatch(browser_after=12, idle_after=20, clock=clock)


def test_nothing_before_the_deadline() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 11.9
    assert watch.poll() is None


def test_browser_opens_once_when_no_page_connected() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 12
    assert watch.poll() == OPEN_BROWSER
    clock.now += 5
    assert watch.poll() is None  # once only
    assert watch.fallback


def test_window_that_connects_in_time_means_no_fallback_and_no_shutdown() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 5
    watch.connected("a")
    clock.now += 60
    assert watch.poll() is None
    watch.disconnected("a")  # the native window closes: the normal shutdown path, not ours
    clock.now += 600
    assert watch.poll() is None
    assert not watch.fallback
    assert watch.window_connected


def test_shutdown_after_the_last_page_was_gone_for_the_idle_time() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 12
    assert watch.poll() == OPEN_BROWSER
    watch.connected("tab")
    clock.now += 100
    assert watch.poll() is None  # a page is connected: no shutdown however long
    watch.disconnected("tab")
    assert watch.poll() is None  # starts the idle count
    clock.now += 19
    assert watch.poll() is None
    clock.now += 1
    assert watch.poll() == SHUTDOWN


def test_a_reload_inside_the_idle_time_keeps_the_app_running() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 12
    watch.poll()
    watch.connected("tab")
    watch.disconnected("tab")
    watch.poll()
    clock.now += 15
    assert watch.poll() is None
    watch.connected("tab")  # reconnect
    assert watch.poll() is None
    watch.disconnected("tab")
    watch.poll()  # starts the new idle count
    clock.now += 15
    assert watch.poll() is None  # the idle count started over
    clock.now += 5
    assert watch.poll() == SHUTDOWN


def test_nobody_ever_connects_even_in_the_browser_stops_after_the_idle_time() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 12
    assert watch.poll() == OPEN_BROWSER
    clock.now += 20
    assert watch.poll() == SHUTDOWN


def test_two_tabs_count_separately() -> None:
    clock = Clock()
    watch = make_watch(clock)
    clock.now += 12
    watch.poll()
    watch.connected("a")
    watch.connected("b")
    watch.disconnected("a")
    clock.now += 50
    assert watch.poll() is None
    watch.disconnected("b")
    watch.poll()
    clock.now += 20
    assert watch.poll() == SHUTDOWN


def test_run_watch_drives_the_watch_with_an_injected_sleep() -> None:
    clock = Clock()
    watch = make_watch(clock)
    events: list[str] = []

    def sleep(seconds: float) -> None:
        clock.now += seconds
        if "open" in events and "connect" not in events:
            watch.connected("tab")
            events.append("connect")
        elif "connect" in events and "gone" not in events and clock.now > 130:
            watch.disconnected("tab")
            events.append("gone")

    window_guard._fallback = False
    run_watch(
        watch,
        lambda: events.append("open"),
        lambda: events.append("shutdown"),
        sleep=sleep,
        poll_every=1.0,
    )
    assert events == ["open", "connect", "gone", "shutdown"]
    assert window_guard.browser_fallback_active()
    window_guard._fallback = False


def test_run_watch_ends_quietly_when_the_window_connects_in_time() -> None:
    clock = Clock()
    watch = make_watch(clock)
    watch.connected("window")
    events: list[str] = []
    run_watch(
        watch, lambda: events.append("open"), lambda: events.append("stop"), sleep=lambda s: None
    )
    assert events == []


def test_find_running_copy_needs_the_token() -> None:
    answers = {
        "http://127.0.0.1:8000/__ping": "something else",
        "http://127.0.0.1:8001/__ping": None,
        "http://127.0.0.1:8002/__ping": PING_TOKEN,
    }
    assert find_running_copy(answers.get, range(8000, 8005)) == 8002
    assert find_running_copy(lambda url: None, range(8000, 8003)) is None
