import io
import zipfile

import streamlit as st
from src.excel_parser import profile_excel
from src.chart_rules import recommend_single, recommend_for_pair
from src.orchestrator import run_pipeline
from src.renderer import render_tile, apply_light_chrome
from src.exporter import build_html_string
from src.excel_exporter import export_excel_bytes
from src.agents import automation_agent
from src.i18n import STRINGS

CONFIGS_DIR = "configs"  # disk-backed, for people running this app locally + the CLI automation_runner.py

st.set_page_config(page_title="Signal — AI Dashboard Generator", layout="wide", page_icon="📊")

if "lang" not in st.session_state:
    st.session_state.lang = "en"
if "pairs" not in st.session_state:
    st.session_state.pairs = []
if "templates" not in st.session_state:
    st.session_state.templates = []  # in-memory, scoped to this browser session only

lang = st.session_state.lang
t = STRINGS[lang]
is_rtl = lang == "ar"

# ── Modern & Minimalist design tokens ───────────────────────────────────
BG = "#f8f9fa"
SURFACE = "#ffffff"
TEXT = "#212529"
MUTED = "#6c757d"
ACCENT = "#0d6efd"
ACCENT_SOFT = "rgba(13,110,253,0.10)"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap');

html, body, [class*="css"] {{ font-family: 'Tajawal', sans-serif !important; }}
h1, h2, h3 {{ font-weight: 700 !important; }}

[data-testid="stAppViewContainer"] {{ direction: {"rtl" if is_rtl else "ltr"}; }}

[data-testid="stVerticalBlockBorderWrapper"] {{
    border: 1px solid rgba(0,0,0,0.06) !important;
    border-radius: 8px !important;
    background: {SURFACE};
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}}

.stButton > button {{
    border-radius: 8px !important;
}}
.stButton > button[kind="primary"] {{
    background: {ACCENT} !important; border-color: {ACCENT} !important;
}}

.hero {{
    display: flex; justify-content: space-between; align-items: center; gap: 20px;
    padding: 24px 28px; margin-bottom: 20px;
    background: {SURFACE}; border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    border-{"right" if is_rtl else "left"}: 4px solid {ACCENT};
}}
.hero-title {{ font-size: 1.7rem; font-weight:700; color:{TEXT}; margin:0; }}
.hero-sub {{ font-size:0.82rem; color:{MUTED}; margin-top:4px; letter-spacing:0.02em; }}
.lang-toggle button {{
    background: {SURFACE} !important; color: {ACCENT} !important; border: 1px solid {ACCENT} !important;
    border-radius: 8px !important;
}}

.score-badge {{
    display:inline-flex; align-items:center; padding: 8px 16px; border-radius: 999px;
    background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 500; font-size:0.9rem;
}}
</style>
""", unsafe_allow_html=True)

hero_col1, hero_col2 = st.columns([5, 1])
with hero_col1:
    st.markdown(f"""
    <div class="hero">
      <div>
        <p class="hero-title">Signal</p>
        <p class="hero-sub">{t['tagline']}</p>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hero_col2:
    st.write("")
    st.markdown('<div class="lang-toggle">', unsafe_allow_html=True)
    if st.button(t["toggle_button"], key="lang_toggle_btn"):
        st.session_state.lang = "ar" if lang == "en" else "en"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

tab_build, tab_batch = st.tabs([t["tab_build"], t["tab_batch"]])

# ══════════════════════════════ TAB 1 — single file, interactive build ═══
with tab_build:
    st.caption(t["build_caption"])

    uploaded = st.file_uploader(t["upload_label"], type=["xlsx", "xls"], key="single_upload")

    if uploaded:
        profile = profile_excel(uploaded)
        df = profile["dataframe"]
        st.success(t["loaded_summary"].format(rows=profile["n_rows"], cols=len(profile["columns"])))

        st.subheader(t["attributes_header"])
        chart_options = ["histogram", "bar", "bar_top_n", "pie", "donut", "line_count_over_time"]
        col_left, col_right = st.columns(2)
        selected_attributes = []
        chart_overrides = {}

        for i, (name, cp) in enumerate(profile["columns"].items()):
            target_col = col_left if i % 2 == 0 else col_right
            default_chart = recommend_single(cp.semantic_type)
            with target_col:
                with st.container(border=True):
                    checked = st.checkbox(
                        f"**{name}**", value=default_chart is not None, key=f"chk_{name}"
                    )
                    st.caption(f"{cp.semantic_type} · {cp.n_unique} unique · {cp.null_pct}% null")
                    if checked:
                        selected_attributes.append(name)
                        if default_chart:
                            idx = chart_options.index(default_chart) if default_chart in chart_options else 0
                            picked = st.selectbox(
                                t["chart_label"], chart_options, index=idx,
                                key=f"chart_{name}", label_visibility="collapsed",
                            )
                            chart_overrides[name] = picked

        st.subheader(t["compare_header"])
        col_names = list(profile["columns"].keys())
        pc1, pc2, pc3 = st.columns([1, 1, 1])
        with pc1:
            pair_a = st.selectbox(t["attr_a"], ["—"] + col_names, key="pair_a")
        with pc2:
            pair_b = st.selectbox(t["attr_b"], ["—"] + col_names, key="pair_b")
        with pc3:
            st.write("")
            st.write("")
            add_pair = st.button(t["add_comparison"])

        if add_pair and pair_a != "—" and pair_b != "—" and pair_a != pair_b:
            type_a = profile["columns"][pair_a].semantic_type
            type_b = profile["columns"][pair_b].semantic_type
            chart_type = recommend_for_pair(type_a, type_b)
            if chart_type:
                st.session_state.pairs.append((pair_a, pair_b))
            else:
                st.warning(t["no_chart_warning"].format(a=pair_a, type_a=type_a, b=pair_b, type_b=type_b))

        if st.session_state.pairs:
            for j, (a, b) in enumerate(st.session_state.pairs):
                cols = st.columns([5, 1])
                cols[0].markdown(f"`{a}` × `{b}`")
                if cols[1].button(t["remove"], key=f"rm_pair_{j}"):
                    st.session_state.pairs.pop(j)
                    st.rerun()

        st.subheader(t["design_header"])
        design_choice = st.selectbox(
            t["design_label"],
            ["Auto", "minimalist", "corporate_dark", "editorial_pastel", "corporate_classic"],
        )
        design_skill_id = None if design_choice == "Auto" else design_choice

        build_clicked = st.button(t["build_button"], type="primary", disabled=not selected_attributes)

        if build_clicked:
            with st.spinner(t["build_spinner"]):
                result = run_pipeline(
                    profile, selected_attributes, chart_overrides, design_skill_id, st.session_state.pairs
                )
            st.session_state.last_build = {
                "result": result, "profile": profile, "selected_attributes": selected_attributes,
                "chart_overrides": chart_overrides, "design_skill_id": design_skill_id,
            }

        if st.session_state.get("last_build"):
            b = st.session_state.last_build
            result, profile, df = b["result"], b["profile"], b["profile"]["dataframe"]

            st.subheader(t["dashboard_header"])
            st.markdown(
                f'<div class="score-badge">{t["badge_template"].format(score=result["final_score"], iterations=result["iterations_used"])}</div>',
                unsafe_allow_html=True,
            )
            st.write("")

            spec = result["final_spec"]
            tiles = spec["tiles"]
            n_cols = 2
            for row_start in range(0, len(tiles), n_cols):
                cols = st.columns(n_cols)
                for j, tile in enumerate(tiles[row_start:row_start + n_cols]):
                    with cols[j]:
                        fig = render_tile(tile, df, spec["design_skill"])
                        fig = apply_light_chrome(fig)
                        st.plotly_chart(fig, use_container_width=True)

            st.subheader(t["report_header"])
            st.markdown(result["report_markdown"])

            st.subheader(t["automation_header"])
            st.caption(t["automation_caption"])
            tcol1, tcol2 = st.columns([3, 1])
            template_name = tcol1.text_input(
                "template_name", value="", placeholder=t["template_name_placeholder"], label_visibility="collapsed"
            )
            if tcol2.button(t["save_template_button"], disabled=not template_name):
                cfg = automation_agent.build_config(
                    template_name, profile, b["selected_attributes"],
                    b["chart_overrides"], st.session_state.pairs, b["design_skill_id"],
                )
                st.session_state.templates.append(cfg)
                try:
                    automation_agent.save_config(
                        CONFIGS_DIR, template_name, profile, b["selected_attributes"],
                        b["chart_overrides"], st.session_state.pairs, b["design_skill_id"],
                    )
                except Exception:
                    pass  # disk write is best-effort — session copy is what Batch mode actually uses
                st.success(t["save_success"].format(name=template_name))
    else:
        st.info(t["upload_prompt"])

# ══════════════════════════════ TAB 2 — batch mode, hosted-safe ═══════════
with tab_batch:
    st.caption(t["batch_caption"])
    st.markdown(
        f'<div class="score-badge">{t["templates_count"].format(n=len(st.session_state.templates))}</div>',
        unsafe_allow_html=True,
    )
    st.caption(t["session_note"])

    if not st.session_state.templates:
        st.warning(t["no_templates_warning"])
    else:
        with st.expander(t["saved_templates_expander"]):
            for cfg in st.session_state.templates:
                st.markdown(t["template_summary"].format(
                    name=cfg["template_name"], cols=len(cfg["columns"]), pairs=len(cfg["pairs"])
                ))

        batch_files = st.file_uploader(
            t["batch_upload_label"], type=["xlsx", "xls"],
            accept_multiple_files=True, key="batch_upload",
        )
        output_format = st.radio(
            t["output_format_label"], [t["output_format_html"], t["output_format_excel"]], horizontal=True
        )

        if st.button(t["process_button"], type="primary", disabled=not batch_files):
            zip_buffer = io.BytesIO()
            log_lines = []

            with st.spinner(t["batch_spinner"].format(n=len(batch_files))):
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in batch_files:
                        try:
                            profile = profile_excel(f)
                        except Exception as e:
                            log_lines.append(t["log_no_read"].format(file=f.name, error=e))
                            continue

                        match = automation_agent.find_matching_config_from_list(profile, st.session_state.templates)
                        if not match:
                            log_lines.append(t["log_no_match"].format(file=f.name))
                            continue

                        remapped = automation_agent.remap_config(match["config"], match["mapping"])
                        if not remapped["selected_attributes"]:
                            log_lines.append(t["log_all_dropped"].format(file=f.name, template=match["config"]["template_name"]))
                            continue

                        result = run_pipeline(
                            profile, remapped["selected_attributes"], remapped["chart_overrides"],
                            remapped["design_skill_id"], remapped["pairs"],
                        )

                        stem = f.name.rsplit(".", 1)[0]
                        if output_format == t["output_format_html"]:
                            content = build_html_string(result, profile, title=f"{match['config']['template_name']} — {stem}").encode("utf-8")
                            zf.writestr(f"{stem}_dashboard.html", content)
                        else:
                            content = export_excel_bytes(result, profile)
                            zf.writestr(f"{stem}_dashboard.xlsx", content)

                        note = t["log_dropped_note"].format(n=len(remapped["dropped_columns"]), cols=remapped["dropped_columns"]) if remapped["dropped_columns"] else ""
                        log_lines.append(t["log_processed"].format(
                            file=f.name, template=match["config"]["template_name"],
                            match_type=match["match_type"], coverage=match["coverage"] * 100,
                            score=result["final_score"], note=note,
                        ))

                    zf.writestr("summary.txt", "\n".join(log_lines))

            st.subheader(t["results_header"])
            for line in log_lines:
                st.markdown(line)

            st.download_button(
                t["download_button"], zip_buffer.getvalue(),
                file_name="dashboards.zip", mime="application/zip", type="primary",
            )
