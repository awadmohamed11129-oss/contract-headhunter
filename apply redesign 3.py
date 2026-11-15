"""Restyles src/jobmatch/app/ui.py to the do good deep-purple design.

Styling only: no handler, binding, service call or marker is changed (the only marker that
moves is "app-title", now on the wordmark row). All edits are exact-text replacements; if any
one doesn't match the file, NOTHING is written.

Usage (from the repo root, on your new branch):
    python apply_redesign.py                      # edits src/jobmatch/app/ui.py
    python apply_redesign.py path/to/ui.py
"""

import sys
from pathlib import Path

target = Path(sys.argv[1] if len(sys.argv) > 1 else "src/jobmatch/app/ui.py")
src = target.read_text(encoding="utf-8")

EDITS: list[tuple[str, str, str, int]] = []  # (name, old, new, expected count)


def edit(name: str, old: str, new: str, count: int = 1) -> None:
    EDITS.append((name, old, new, count))


# 1. Theme constants, global CSS, nav-highlight script ------------------------------------
edit(
    "theme",
    '''# The org's theme, light purple. The header and main buttons use a medium purple so white
# text on them stays readable; the page background is the light purple. The decision colours
# (SHADE below: green / yellow / red) carry meaning and are not part of the theme.
THEME_PRIMARY = "#7E57C2"
THEME_BACKGROUND = "#EDE7F6"
''',
    '''# The org's theme (redesign): deep purple page, header and primary buttons; every screen is
# a white rounded sheet holding soft-shadow cards. The decision colours (SHADE below:
# green / yellow / red, each with a darker outer edge) carry meaning and are not the theme.
THEME_PRIMARY = "#593B9D"
THEME_ACCENT = "#7E4891"
THEME_BACKGROUND = "linear-gradient(170deg, #593B9D 0%, #4F3590 55%, #5A3D9F 100%)"

FONT_LINK = (
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800'
    '&family=Space+Mono&display=swap" rel="stylesheet">'
)
# The infinity sign, drawn as one stroked path (it replaces the "oo" of "good").
INF_PATH = (
    "M18 8c-5.5 0-10 3.6-10 8s4.5 8 10 8c8 0 14-16 22-16 5.5 0 10 3.6 10 8s-4.5 8-10 8"
    "c-8 0-14-16-22-16z"
)
WORDMARK_HTML = (
    '<div class="brand"><div class="brand-row"><span>do g</span>'
    '<svg class="inf" viewBox="2 4 54 24" aria-hidden="true">'
    '<path class="bs" d="PATH" pathLength="100"/><path class="tr" d="PATH" pathLength="100"/>'
    '</svg><span>d</span></div><div class="brand-tag">a talent company</div></div>'
).replace("PATH", INF_PATH)
# A rail under the header: the infinity sign glides to the screen you are on.
PROGRESS_HTML = (
    '<div class="dg-track"><div class="dg-rail"><div id="dg-fill" class="dg-fill"></div>'
    '<svg id="dg-knob" class="dg-knob" viewBox="2 4 54 24" aria-hidden="true">'
    '<path d="PATH"/></svg></div><div id="dg-step" class="dg-step">Find matches</div></div>'
).replace("PATH", INF_PATH)

APP_CSS = """
body { font-family: Inter, "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
  counter-reset: dgstep; }
.q-layout { position: relative; z-index: 1; }
.q-header { background: rgba(89,59,157,.94) !important; backdrop-filter: blur(8px);
  box-shadow: none; }
.orbs { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.orbs i { position: absolute; border-radius: 50%; border: 2px solid rgba(255,255,255,.2);
  background: rgba(150,80,170,.16); animation: drift 18s ease-in-out infinite alternate; }
.orbs i:nth-child(1) { width: 300px; height: 300px; right: 8%; top: 6%; }
.orbs i:nth-child(2) { width: 200px; height: 200px; left: 3%; bottom: 12%; animation-delay: -6s; }
.orbs i:nth-child(3) { width: 380px; height: 380px; right: -90px; bottom: -120px;
  animation-delay: -11s; }
@keyframes drift { to { transform: translate(18px, -24px); } }
.brand { line-height: 1; cursor: pointer; }
.brand-row { display: inline-flex; align-items: baseline; color: #fff; font-size: 34px;
  font-weight: 800; letter-spacing: -.03em; }
.inf { height: .6em; width: auto; margin: 0 .03em; overflow: visible; }
.inf path, .dg-knob path { fill: none; stroke: #fff; stroke-width: 5.5; stroke-linecap: round;
  stroke-linejoin: round; }
.inf .bs { opacity: .8; }
.inf .tr { stroke-dasharray: 16 84; animation: trace 3.6s linear infinite;
  filter: drop-shadow(0 0 3px #fff); }
@keyframes trace { from { stroke-dashoffset: 100; } to { stroke-dashoffset: 0; } }
.brand:hover .inf { animation: wobble .7s ease; }
@keyframes wobble { 30% { transform: rotate(-8deg) scale(1.12); }
  60% { transform: rotate(6deg) scale(1.06); } }
.brand-tag { color: rgba(255,255,255,.88); font: 12px "Space Mono", ui-monospace, monospace;
  letter-spacing: .06em; margin-top: 5px; }
.nav-btn { color: rgba(255,255,255,.82) !important; border-radius: 9999px !important;
  padding: 6px 16px; font-weight: 600; }
.nav-btn:hover { background: rgba(255,255,255,.12); color: #fff !important; }
.nav-btn.nav-active { background: rgba(255,255,255,.2); color: #fff !important;
  box-shadow: inset 0 -3px 0 #fff; }
.dg-rail { position: relative; height: 28px; }
.dg-rail::before { content: ""; position: absolute; left: 0; right: 0; top: 10px; height: 8px;
  border-radius: 9999px; background: #816BB3; opacity: .75; }
.dg-fill { position: absolute; left: 0; top: 10px; height: 8px; border-radius: 9999px;
  background: rgba(255,255,255,.55); width: 26px;
  transition: width .7s cubic-bezier(.34,1.3,.64,1); }
.dg-knob { position: absolute; top: 0; left: 0; width: 52px; height: 28px; overflow: visible;
  transition: left .7s cubic-bezier(.34,1.56,.64,1); animation: bob 3s ease-in-out infinite; }
@keyframes bob { 50% { transform: translateY(-2px) rotate(-3deg); } }
.dg-step { color: #fff; font-weight: 600; font-size: 17px; letter-spacing: .04em; margin-top: 6px; }
.dg-sheet { border: 3px solid #DDD9F0; animation: rise .45s ease both; }
@keyframes rise { from { opacity: 0; transform: translateY(12px); } }
.q-card { border-radius: 1.5rem; border: 2px solid #E4DFF3;
  box-shadow: 0 6px 22px rgba(89,59,157,.10), 0 1px 3px rgba(89,59,157,.08); }
.text-h5 { color: #4B3499; font-weight: 800; font-size: 2rem; letter-spacing: -.03em;
  line-height: 1.1; }
.text-h6 { color: #1E1A33; font-weight: 700; }
.step-h { display: flex; align-items: center; gap: 14px; }
.step-h::before { counter-increment: dgstep; content: counter(dgstep); width: 36px; height: 36px;
  border-radius: 50%; background: #7E4891; color: #fff; display: inline-flex;
  align-items: center; justify-content: center; font-size: 17px; font-weight: 700;
  transition: transform .25s; }
.q-card:hover .step-h::before { transform: scale(1.12) rotate(-6deg); }
.q-btn:not(.q-btn--round) { border-radius: 1.1rem; font-weight: 600;
  transition: transform .15s, box-shadow .15s; }
.q-btn:not(.q-btn--round):hover { transform: translateY(-1px); }
.q-btn--outline:before { border-width: 1.5px; }
.q-btn.bg-primary { box-shadow: 0 4px 14px rgba(89,59,157,.35); }
.q-field--outlined .q-field__control { border-radius: 1rem; }
.q-expansion-item .q-item { border-radius: .75rem; }
.q-expansion-item .q-item:hover { background: #F6F2FC; }
.nicegui-log { border-radius: 1.25rem; border: 2px solid #E4DFF3; background: #FBFAFE; }
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after { animation: none !important; transition: none !important; } }
"""

# Highlights the current screen's nav button and glides the infinity knob along the rail.
NAV_JS = """<script>
if (!window.__dgNav) {
  const PATHS = ['/', '/results', '/jobs', '/talent', '/settings'];
  const NAMES = ['Find matches', 'Results', 'Jobs', 'Talent', 'Settings'];
  window.__dgNav = setInterval(() => {
    const i = Math.max(0, PATHS.indexOf(location.pathname));
    document.querySelectorAll('.nav-btn').forEach((b) =>
      b.classList.toggle('nav-active', b.getAttribute('data-path') === location.pathname));
    const k = document.getElementById('dg-knob'), f = document.getElementById('dg-fill');
    const s = document.getElementById('dg-step');
    if (k) k.style.left = 'calc((100% - 52px) * ' + (i / 4) + ')';
    if (f) f.style.width = 'calc(26px + (100% - 52px) * ' + (i / 4) + ')';
    if (s && s.textContent !== NAMES[i]) s.textContent = NAMES[i];
  }, 150);
}
</script>"""
''',
)

# 2. Page sheets --------------------------------------------------------------------------
edit(
    "page sheets",
    '''PAGE = "w-full mx-auto max-w-[1600px] px-2 sm:px-4 lg:px-8"
PAGE_NARROW = "w-full mx-auto max-w-[900px] px-2 sm:px-4 lg:px-8"
''',
    '''SHEET = "dg-sheet bg-white rounded-[36px] shadow-2xl p-4 sm:p-6 lg:p-10"  # the white sheet on purple
PAGE = f"w-full mx-auto max-w-[1600px] {SHEET}"
PAGE_NARROW = f"w-full mx-auto max-w-[900px] {SHEET}"
''',
)

# 3. Decision colours: soft fill + darker outer edge --------------------------------------
edit(
    "shade colours",
    'SHADE = {"green": "#90DCA2", "yellow": "#F8DF9B", "red": "#E07F8A"}\n',
    '''SHADE = {"green": "#B7EBC4", "yellow": "#FBE7A1", "red": "#F4B6BD"}
SHADE_EDGE = {"green": "#2E9D5B", "yellow": "#C99A12", "red": "#C0392B"}  # the darker outer edge


def shade_style(shade: str) -> str:
    """Soft fill with a darker outer edge of the same colour."""
    return f"background-color: {SHADE[shade]}; border: 1.5px solid {SHADE_EDGE[shade]};"
''',
)
edit(
    "edge by fill",
    'OUTCOME_SHADE = {"fits": "green", "check_partial": "yellow"}  # no match / not judged: none\n',
    '''EDGE_BY_FILL = {
    SCORE_SHADE["strong"]: SHADE_EDGE["green"],
    SCORE_SHADE["good"]: SHADE_EDGE["green"],
    SCORE_SHADE["some"]: SHADE_EDGE["yellow"],
    SCORE_SHADE["low"]: SHADE_EDGE["yellow"],
}
OUTCOME_SHADE = {"fits": "green", "check_partial": "yellow"}  # no match / not judged: none
''',
)
edit(
    "shade button",
    '        .style(f"background-color: {SHADE_LIGHT[shade]}; color: {TEXT_DARK};")\n',
    '''        .style(
            f"background-color: {SHADE_LIGHT[shade]}; color: {TEXT_DARK}; "
            f"border: 1.5px solid {SHADE_EDGE[shade]};"
        )
''',
)
edit(
    "chip",
    '''    style = f"background-color: {SHADE[shade]};" if shade else "background-color: #F5F5F5;"
    ui.chip(text, icon=icon, color=None, text_color=None).props("dense square").classes(
''',
    '''    style = shade_style(shade) if shade else "background-color: #F3EEFB; border: 1.5px solid #E0D5F3;"
    ui.chip(text, icon=icon, color=None, text_color=None).props("dense").classes(
''',
)
edit(
    "decision tag",
    '''            ui.label(text + reason).classes("text-sm px-2 py-0.5 rounded").style(
                f"background-color: {SHADE[DECISION_SHADE[review.decision]]}; color: {TEXT_DARK};"
            )''',
    '''            ui.label(text + reason).classes("text-sm px-3 py-0.5 rounded-full font-medium").style(
                f"{shade_style(DECISION_SHADE[review.decision])} color: {TEXT_DARK};"
            )''',
)
edit(
    "verdict chip",
    '''                ui.label("fit" if fit else "partial").classes("text-xs px-2 rounded").style(
                    f"background-color: {score_shade(service, m.fit_score, fit)}; "
                    f"color: {TEXT_DARK};"
                ).mark("verdict-chip")''',
    '''                chip_fill = score_shade(service, m.fit_score, fit)
                ui.label("fit" if fit else "partial").classes(
                    "text-xs px-2 rounded-full font-semibold"
                ).style(
                    f"background-color: {chip_fill}; color: {TEXT_DARK}; "
                    f"border: 1.5px solid {EDGE_BY_FILL.get(chip_fill, SHADE_EDGE['green'])};"
                ).mark("verdict-chip")''',
)
edit(
    "decision left border",
    "            colour = SHADE[DECISION_SHADE[review.decision]]\n",
    "            colour = SHADE_EDGE[DECISION_SHADE[review.decision]]\n",
)
edit(
    "contractor box",
    'box = ui.column().classes("w-full gap-2 rounded-lg border border-grey-4 p-3")',
    'box = ui.column().classes("w-full gap-2 rounded-xl border border-grey-4 p-3")',
)

# 4. Results job cards --------------------------------------------------------------------
edit(
    "result band",
    '    band = f"background-color: {SHADE[shade]};" if shade else "border-bottom: 1px solid #E0E0E0;"\n',
    '''    band = (
        f"background-color: {SHADE[shade]}; border-bottom: 2px solid {SHADE_EDGE[shade]};"
        if shade
        else "background-color: #F3EEFB; border-bottom: 1px solid #E0D5F3;"
    )
''',
)
edit(
    "result card",
    '.classes("w-full p-0 gap-0 rounded-lg overflow-hidden")',
    '''.classes("w-full p-0 gap-0 rounded-2xl overflow-hidden")
        .style(f"border: 2px solid {SHADE_EDGE[shade]};" if shade else "")''',
)

# 5. Jobs and Talent cards ----------------------------------------------------------------
edit(
    "job states",
    '''    "matched": ("#c7ffd2", "#4CAF50"),
    "no_match": ("#ffcfcf", "#D32F2F"),
    "waiting": ("#fff385", "#F9A825"),
    "inactive": ("#EEEEEE", "#BDBDBD"),
''',
    '''    "matched": ("#E4F8E9", "#2E9D5B"),
    "no_match": ("#FCE3E6", "#C0392B"),
    "waiting": ("#FFF4C7", "#D9A21B"),
    "inactive": ("#F1EFF5", "#B9B2C9"),
''',
)
edit(
    "jobs and talent card shape",
    '.classes("w-full px-4 py-3 gap-1 rounded-lg")',
    '.classes("w-full px-4 py-3 gap-1 rounded-2xl")',
    count=2,
)
edit(
    "talent states",
    'TALENT_STYLE = {True: ("#FFFFFF", "#D1C4E9"), False: ("#D6D6D6", "#9E9E9E")}',
    'TALENT_STYLE = {True: ("#FFFFFF", "#D9CEF0"), False: ("#ECE9F2", "#A79FBC")}',
)

# 6. App shell: colours, wordmark, nav tabs -----------------------------------------------
edit(
    "header",
    '''        ui.colors(primary=THEME_PRIMARY)
        ui.query("body").style(f"background-color: {THEME_BACKGROUND}")
        with ui.header().classes("items-center"):
            ui.label(APP_TITLE).classes("text-lg font-bold").mark("app-title")
            ui.space()
''',
    '''        ui.colors(primary=THEME_PRIMARY, secondary=THEME_ACCENT, accent=THEME_ACCENT)
        ui.add_css(APP_CSS)
        ui.add_head_html(FONT_LINK)
        ui.add_body_html(NAV_JS)
        ui.add_body_html('<div class="orbs"><i></i><i></i><i></i></div>')
        ui.query("body").style(f"background: {THEME_BACKGROUND}; background-attachment: fixed;")
        with ui.header().classes("items-center px-6 py-3 gap-1"):
            ui.html(WORDMARK_HTML, sanitize=False).on("click", _go("/")).mark("app-title")
            ui.space()
''',
)
edit(
    "nav buttons",
    'ui.button(text, on_click=_go(path)).props("flat color=white")',
    '''ui.button(text, on_click=_go(path)).props(
                    f'flat no-caps data-path="{path}"'
                ).classes("nav-btn")''',
)
edit(
    "screen padding",
    ').classes("w-full items-center")',
    ').classes("w-full items-center px-3 sm:px-6 py-5")',
)

edit(
    "step badge 1",
    'ui.label("Contractors (optional)").classes("text-h6")',
    'ui.label("Contractors (optional)").classes("text-h6 step-h")',
)
edit(
    "step badge 2",
    'ui.label("Jobs").classes("text-h6")',
    'ui.label("Jobs").classes("text-h6 step-h")',
)
edit(
    "progress rail",
    "        ui.sub_pages(\n",
    '''        ui.html(PROGRESS_HTML, sanitize=False).classes(
            "w-full mx-auto max-w-[1600px] px-3 sm:px-6 pt-3"
        )
        ui.sub_pages(
''',
)

# ---- apply: all or nothing ----
for name, old, new, count in EDITS:
    found = src.count(old)
    if found != count:
        sys.exit(f"STOPPED, nothing written: '{name}' expected {count} match(es), found {found}.")
    src = src.replace(old, new)
compile(src, str(target), "exec")  # the result must still be valid Python
target.write_text(src, encoding="utf-8")
print(f"Restyled {target}: {len(EDITS)} edits applied.")
