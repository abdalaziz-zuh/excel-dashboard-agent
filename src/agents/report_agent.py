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

import os


def _get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception:
        return None


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
    client = _get_groq_client()
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
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        return resp.choices[0].message.content
    except Exception:
        return None


def generate_report(iteration_log: list[dict], profile: dict, design_skill: dict) -> str:
    mechanical = _mechanical_summary(iteration_log)
    insights = _llm_data_insights(profile) or _template_data_insights(profile)

    return f"""# Dashboard Report

## Design
Theme used: **{design_skill['label']}** ({design_skill['mood']})

## What happened
{mechanical}

## What to look at in your data
{insights}
"""
