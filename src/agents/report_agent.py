"""
report_agent.py  (Agent 3 — "Reporter")

Reads the full iteration log from the build<->check loop plus the raw data
profile, and produces a markdown report with two sections:

  1. "What happened" — how many fix cycles it took, what was changed,
     final QA score. Purely mechanical, built from the log — no LLM needed.
  2. "What to look at" — actual data insights (nulls, outliers, top
     categories, extreme values) computed from the profile stats. If a
     Groq key is available, the LLM turns the raw stats into 3-5 plain-
     language callouts; if not, we fall back to a template-based version
     so the tool still works with zero API cost.
"""

from src.agents.groq_client import get_groq_client, DEFAULT_MODEL


def _mechanical_summary(iteration_log: list[dict]) -> str:
    n_iters = len(iteration_log)
    final = iteration_log[-1]
    lines = [
        f"- Dashboard was validated in **{n_iters} pass(es)**.",
        f"- Final QA score: **{final['review']['score']}/100** "
        f"({'passed threshold' if final['review']['passed'] else 'stopped at max iterations, needs manual look'}).",
    ]
    fixed_tiles = set()
    for it in iteration_log[:-1]:
        for issue in it["review"]["issues"]:
            fixed_tiles.add(issue["tile_index"])
    if fixed_tiles:
        lines.append(f"- {len(fixed_tiles)} tile(s) were auto-corrected during review (bad chart type, category overload, or missing title).")
    remaining = final["review"]["issues"]
    if remaining:
        lines.append(f"- **{len(remaining)} issue(s) remain unresolved** — see below, needs a human decision.")
        for issue in remaining:
            for p in issue["problems"]:
                lines.append(f"  - Tile {issue['tile_index']}: {p}")
    return "\n".join(lines)


def _template_data_insights(profile: dict) -> str:
    lines = []
    for name, cp in profile["columns"].items():
        if cp.null_pct > 20:
            lines.append(f"- ⚠️ **{name}** is {cp.null_pct}% empty — worth checking the source data.")
        if cp.semantic_type == "categorical_high":
            lines.append(f"- **{name}** looks like an identifier ({cp.n_unique} unique values) — probably not useful as a chart axis.")
        if cp.semantic_type in ("numeric_continuous", "numeric_discrete") and cp.stats.get("max") is not None:
            lines.append(f"- **{name}** ranges from {cp.stats['min']:.2f} to {cp.stats['max']:.2f} (avg {cp.stats['mean']:.2f}).")
    return "\n".join(lines) if lines else "- No notable data-quality flags found."


def _llm_data_insights(profile: dict) -> str | None:
    client = get_groq_client()
    if not client:
        return None
    col_summary = "\n".join(
        f"{name}: type={cp.semantic_type}, nulls={cp.null_pct}%, unique={cp.n_unique}, stats={cp.stats}"
        for name, cp in profile["columns"].items()
    )
    prompt = (
        "You are a data analyst. Given this column profile summary, write 3-5 short, "
        "plain-language bullet points highlighting the most important things a business "
        "user should notice (data quality issues, notable ranges, likely ID columns). "
        "No preamble, bullets only.\n\n" + col_summary
    )
    try:
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"[Signal] Groq insight generation failed, using template fallback: {e}")
        return None


def _cleaning_summary(cleaning_report: dict | None) -> str:
    if not cleaning_report:
        return None
    lines = []
    if cleaning_report["duplicates_removed"]:
        lines.append(f"- Removed **{cleaning_report['duplicates_removed']} exact duplicate row(s)**.")
    if cleaning_report["whitespace_trimmed_columns"]:
        cols = ", ".join(cleaning_report["whitespace_trimmed_columns"])
        lines.append(f"- Trimmed stray whitespace in: {cols}.")
    if cleaning_report["casing_flags"]:
        lines.append("- ⚠️ **Possible duplicate categories from inconsistent casing** (not auto-merged — a decision, not a fact):")
        for col, clashes in cleaning_report["casing_flags"].items():
            for variants in clashes.values():
                lines.append(f"  - '{col}': {', '.join(repr(v) for v in variants)} — likely the same category")
    if cleaning_report["outlier_flags"]:
        lines.append("- ⚠️ **Statistical outliers found** (flagged, not removed):")
        for col, info in cleaning_report["outlier_flags"].items():
            lines.append(f"  - '{col}': {info['count']} value(s) ({info['pct']}%) outside [{info['bounds'][0]}, {info['bounds'][1]}]")
    if cleaning_report["null_flags"]:
        lines.append("- Missing values remaining after cleaning:")
        for col, pct in cleaning_report["null_flags"].items():
            lines.append(f"  - '{col}': {pct}% empty")
    return "\n".join(lines) if lines else "- Data was already clean — no duplicates, stray whitespace, casing clashes, or outliers found."


def _analysis_summary(analysis: dict | None) -> str:
    if not analysis:
        return None
    lines = []

    pairs = analysis["correlations"]["notable_pairs"]
    if pairs:
        lines.append("**Correlations:**")
        for p in pairs:
            base = f"- '{p['a']}' and '{p['b']}': r = {p['r']}"
            if "r_excluding_outliers" in p:
                base += (f" — ⚠️ but this is skewed by {p['outliers_excluded']} outlier row(s); "
                         f"excluding them, r = {p['r_excluding_outliers']}")
            lines.append(base)
    else:
        lines.append("**Correlations:** no numeric column pairs with a notable relationship (|r| ≥ 0.5).")

    trends = analysis["trends"]
    if trends:
        lines.append("\n**Trends over time:**")
        for t in trends:
            base = f"- '{t['num_col']}' over '{t['date_col']}': {t['direction']} (R² = {t['r_squared']})"
            if "excluding_outliers" in t:
                ex = t["excluding_outliers"]
                base += (f" — ⚠️ skewed by {t['outliers_excluded']} outlier row(s); "
                         f"excluding them: {ex['direction']} (R² = {ex['r_squared']})")
            lines.append(base)

    return "\n".join(lines) if lines else None


def generate_report(
    iteration_log: list[dict], profile: dict, design_skill: dict,
    cleaning_report: dict | None = None, analysis: dict | None = None,
) -> str:
    mechanical = _mechanical_summary(iteration_log)
    insights = _llm_data_insights(profile) or _template_data_insights(profile)
    cleaning_section = _cleaning_summary(cleaning_report)
    analysis_section = _analysis_summary(analysis)

    report = f"""# Dashboard Report

## Design
Theme used: **{design_skill['label']}** ({design_skill['mood']})

## What happened
{mechanical}
"""
    if cleaning_section:
        report += f"\n## Data cleaning\n{cleaning_section}\n"
    if analysis_section:
        report += f"\n## Analysis\n{analysis_section}\n"

    report += f"\n## What to look at in your data\n{insights}\n"
    return report
