"""The size and place of the desktop window, so it always fits the screen it opens on.

A fixed 1200 x 860 window runs off the bottom of a laptop screen (effective 1280 x 720).
`fit_window` takes the size we would like and the free area of the screen (the screen minus the
taskbar) and returns a size that fits: at most about 92% of that area, never below a small
minimum, centred by the windowing library. On a screen too small for the preferred size the
window starts maximized instead. Sizes are in the logical pixels the windowing library uses
(it multiplies by the display scale itself).
"""

import sys
from dataclasses import dataclass

PREFERRED = (1200, 860)  # what we would like on a roomy screen
MINIMUM = (800, 560)  # the smallest size the person can drag the window to
SHARE = 0.92  # how much of the free screen area a window may take


@dataclass(frozen=True)
class WindowFit:
    width: int
    height: int
    min_width: int
    min_height: int
    maximized: bool  # the preferred size did not fit: start filling the free area


def fit_window(
    area: tuple[int, int] | None,
    preferred: tuple[int, int] = PREFERRED,
    minimum: tuple[int, int] = MINIMUM,
) -> WindowFit:
    """The window for a free screen area (width, height), or None when it is not known."""
    if area is None or min(area) <= 0:
        return WindowFit(*preferred, *minimum, maximized=False)
    room = (int(area[0] * SHARE), int(area[1] * SHARE))
    width, height = min(preferred[0], room[0]), min(preferred[1], room[1])
    return WindowFit(
        width,
        height,
        min(minimum[0], width),
        min(minimum[1], height),
        maximized=(width, height) != tuple(preferred),
    )


def screen_work_area() -> tuple[int, int] | None:
    """The free area (screen minus taskbar) of the main screen in logical pixels, or None when
    it cannot be read (the preferred size is used then). Best effort: never raises."""
    try:
        if sys.platform == "win32":
            return _windows_work_area()
        if sys.platform == "darwin":
            return _mac_work_area()
    except Exception:  # noqa: BLE001 (a window of the preferred size is better than no window)
        return None
    return None


def _windows_work_area() -> tuple[int, int]:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()  # this (server) process only: real pixels, not scaled ones
    rect = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    scale = (user32.GetDpiForSystem() or 96) / 96
    return round((rect.right - rect.left) / scale), round((rect.bottom - rect.top) / scale)


def _mac_work_area() -> tuple[int, int]:
    from AppKit import NSScreen  # noqa: PLC0415 (pyobjc, installed with pywebview on a Mac)

    frame = NSScreen.mainScreen().visibleFrame()
    return int(frame.size.width), int(frame.size.height)
