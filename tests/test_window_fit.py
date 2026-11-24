"""The desktop window fits the screen it opens on (app/window_fit.py)."""

from jobmatch.app.window_fit import MINIMUM, PREFERRED, fit_window


def test_a_roomy_screen_gets_the_preferred_size() -> None:
    fit = fit_window((2048, 1152))
    assert (fit.width, fit.height) == PREFERRED and not fit.maximized
    assert (fit.min_width, fit.min_height) == MINIMUM


def test_a_laptop_screen_gets_a_window_that_fits_and_starts_maximized() -> None:
    fit = fit_window((1280, 680))  # 1280 x 720 minus the taskbar
    assert fit.width <= 1280 * 0.92 and fit.height <= 680 * 0.92
    assert fit.width == int(1280 * 0.92) and fit.height == int(680 * 0.92)
    assert fit.maximized
    assert fit.min_height <= fit.height  # the minimum never exceeds the window


def test_an_unknown_or_nonsense_screen_keeps_the_preferred_size() -> None:
    for area in (None, (0, 0), (-5, 700)):
        fit = fit_window(area)
        assert (fit.width, fit.height) == PREFERRED and not fit.maximized


def test_a_tiny_screen_still_gets_a_sane_minimum() -> None:
    fit = fit_window((600, 400))
    assert fit.width == 552 and fit.height == 368
    assert fit.min_width <= fit.width and fit.min_height <= fit.height
