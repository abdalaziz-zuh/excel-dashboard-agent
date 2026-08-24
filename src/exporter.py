"""
exporter.py
Renders a pipeline result to a single self-contained, responsive HTML page
with a working client-side EN<->AR toggle. Used by both the local
automation agent (writes to disk) and the hosted batch-mode UI (bundles
into a ZIP in memory).

Scope of the language toggle: it translates the page CHROME (headings,
labels, buttons) only. Chart titles, column names, and the agent report
text are DATA — generated from whatever language the user's spreadsheet
and the report agent produced them in — and are deliberately left as-is,
same principle as everywhere else in this project: never guess-translate
data content.
"""

from pathlib import Path

from src.renderer import render_tile, apply_light_chrome

# chrome-only translations — data content (chart titles, report body) is
# never covered here on purpose, see module docstring
TRANSLATIONS = {
    "en": {
        "badge_template": "QA score {score}/100 · {iterations} fix pass(es)",
        "charts_heading": "Dashboard",
        "report_heading": "Agent report",
        "report_note": "(report text is generated in the data's own language and isn't machine-translated)",
        "toggle_label": "العربية",
    },
    "ar": {
        "badge_template": "درجة الجودة {score}/100 · {iterations} محاولة تصحيح",
        "charts_heading": "الداشبورد",
        "report_heading": "تقرير الوكيل",
        "report_note": "(نص التقرير مولّد بنفس لغة البيانات ولم تتم ترجمته آلياً)",
        "toggle_label": "English",
    },
}

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg: #f8f9fa;
  --surface: #ffffff;
  --text: #212529;
  --text-muted: #6c757d;
  --accent: #0d6efd;
  --accent-soft: rgba(13,110,253,0.10);
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
}}
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap');

* {{ box-sizing: border-box; }}
body {{
  background: var(--bg); color: var(--text); margin:0;
  font-family: 'Tajawal', sans-serif;
  padding: 24px 20px 60px;
}}
.container {{ max-width: 1100px; margin: 0 auto; }}

.topbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }}
h1 {{ font-size: 1.7rem; font-weight: 700; margin: 0; }}
.lang-btn {{
  background: var(--surface); color: var(--accent); border: 1px solid var(--accent);
  border-radius: var(--radius); padding: 8px 18px; font-family: inherit; font-size: 0.9rem;
  cursor: pointer; font-weight: 500; transition: background 0.15s ease;
}}
.lang-btn:hover {{ background: var(--accent-soft); }}

.badge {{
  display:inline-block; padding: 8px 16px; border-radius: 999px;
  background: var(--accent-soft); color: var(--accent); font-weight: 500; font-size: 0.9rem;
  margin-bottom: 24px;
}}

.grid {{ display:grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 680px) {{ .grid {{ grid-template-columns: 1fr; }} }}

.tile {{
  background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 12px; overflow: hidden;
}}

.report-section {{ margin-top: 32px; }}
.report-section h2 {{ font-size: 1.2rem; font-weight: 700; margin-bottom: 4px; }}
.report-note {{ color: var(--text-muted); font-size: 0.82rem; margin: 0 0 14px; }}
.report {{
  background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 24px 28px; white-space: pre-wrap; font-family: 'IBM Plex Mono', 'Tajawal', monospace;
  font-size: 0.9rem; line-height: 1.6;
}}
</style>
</head>
<body>
<div class="container">
  <div class="topbar">
    <h1>{title}</h1>
    <button class="lang-btn" onclick="toggleLang()" id="langBtn">العربية</button>
  </div>
  <div class="badge" id="scoreBadge"></div>

  <h2 data-i18n="charts_heading" style="font-size:1.2rem; font-weight:700; margin-bottom:14px;">Dashboard</h2>
  <div class="grid">
{tiles_html}
  </div>

  <div class="report-section">
    <h2 data-i18n="report_heading">Agent report</h2>
    <p class="report-note" data-i18n="report_note">(report text is generated in the data's own language and isn't machine-translated)</p>
    <div class="report">{report}</div>
  </div>
</div>

<script>
const TRANSLATIONS = {translations_json};
const SCORE = {score};
const ITERATIONS = {iterations};
let currentLang = 'en';

function renderBadge(lang) {{
  const tmpl = TRANSLATIONS[lang].badge_template;
  document.getElementById('scoreBadge').textContent =
    tmpl.replace('{{score}}', SCORE).replace('{{iterations}}', ITERATIONS);
}}

function toggleLang() {{
  currentLang = currentLang === 'en' ? 'ar' : 'en';
  document.documentElement.lang = currentLang;
  document.documentElement.dir = currentLang === 'ar' ? 'rtl' : 'ltr';
  document.getElementById('langBtn').textContent = TRANSLATIONS[currentLang].toggle_label;
  document.querySelectorAll('[data-i18n]').forEach(el => {{
    const key = el.getAttribute('data-i18n');
    if (TRANSLATIONS[currentLang][key]) el.textContent = TRANSLATIONS[currentLang][key];
  }});
  renderBadge(currentLang);
}}

renderBadge('en');
</script>
</body>
</html>
"""


def build_html_string(result: dict, profile: dict, title: str = "Dashboard") -> str:
    import json

    df = profile["dataframe"]
    spec = result["final_spec"]
    design_skill = spec["design_skill"]

    tiles_html = []
    for tile in spec["tiles"]:
        fig = render_tile(tile, df, design_skill)
        fig = apply_light_chrome(fig)
        fragment = fig.to_html(full_html=False, include_plotlyjs="cdn" if not tiles_html else False)
        tiles_html.append(f'    <div class="tile">{fragment}</div>')

    return _TEMPLATE.format(
        title=title,
        score=result["final_score"],
        iterations=result["iterations_used"],
        tiles_html="\n".join(tiles_html),
        report=result["report_markdown"],
        translations_json=json.dumps(TRANSLATIONS, ensure_ascii=False),
    )


def export_html(result: dict, profile: dict, output_path: str, title: str = "Dashboard") -> str:
    """Disk-writing wrapper — used by the local automation_runner.py."""
    html = build_html_string(result, profile, title)
    Path(output_path).write_text(html, encoding="utf-8")
    return output_path
