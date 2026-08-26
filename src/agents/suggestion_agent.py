"""
suggestion_agent.py  ("Advisor" — optional, runs on the Cleaner's flagged
issues only, never on chart/QA logic)

Scope, strictly enforced:
  - For inconsistent casing (e.g. "South" vs "south"): suggests WHICH
    existing variant to standardize on. Never invents a new label — only
    picks among values that already appear in the data.
  - For missing values in a CATEGORICAL column: suggests a placeholder
    label ("Unknown", "Not specified", or similar). This is a descriptive
    label, not a data value being fabricated.
  - For missing values in a NUMERIC column: suggests a FILL STRATEGY NAME
    ("median", "mean", "forward-fill", "leave blank") based on context —
    it does NOT suggest or compute a number itself. The actual number is
    always computed deterministically by cleaning_agent.py from the real
    data. This split is intentional: an LLM choosing "median" vs
    "forward-fill" for a revenue column is a reasonable judgment call; an
    LLM inventing "3,482.50" is fabricating a business figure, and this
    project doesn't do that anywhere.

Every function falls back to a deterministic default when no Groq key is
configured — same pattern as report_agent.py.
"""

import os

NUMERIC_FILL_STRATEGIES = {"median", "mean", "forward-fill", "leave blank"}


def _get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception:
        return None


def suggest_casing_canonical(column_name: str, variants: list[str]) -> dict:
    """Returns {'canonical': <one of variants>, 'reason': str}."""
    client = _get_groq_client()
    if client:
        try:
            prompt = (
                f"Column '{column_name}' has these near-duplicate category values due to "
                f"inconsistent capitalization: {variants}. Reply with ONLY the single best "
                f"variant to standardize on (copy it exactly, no quotes, no extra text)."
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
            )
            picked = resp.choices[0].message.content.strip().strip("'\"")
            if picked in variants:
                return {"canonical": picked, "reason": "AI-suggested standard casing"}
        except Exception:
            pass
    # deterministic fallback: prefer Title Case if present, else the most common variant
    title_case = [v for v in variants if v == v.title()]
    canonical = title_case[0] if title_case else sorted(variants)[0]
    return {"canonical": canonical, "reason": "Defaulted to title case (no AI suggestion available)"}


def suggest_categorical_fill(column_name: str, sample_values: list) -> dict:
    """Returns {'label': str, 'reason': str} — a placeholder label, not a real value."""
    client = _get_groq_client()
    if client:
        try:
            prompt = (
                f"Column '{column_name}' (example values: {sample_values[:5]}) has missing "
                f"entries. Suggest ONE short placeholder label to fill them with (like "
                f"'Unknown' or 'Not specified' — something that clearly marks the value as "
                f"missing, not a guess at what it might be). Reply with ONLY the label."
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=15,
            )
            label = resp.choices[0].message.content.strip().strip("'\"")
            if label and len(label) < 40:
                return {"label": label, "reason": "AI-suggested placeholder"}
        except Exception:
            pass
    return {"label": "Unknown", "reason": "Default placeholder (no AI suggestion available)"}


def suggest_numeric_fill_strategy(column_name: str, stats: dict, null_pct: float) -> dict:
    """Returns {'strategy': one of NUMERIC_FILL_STRATEGIES, 'reason': str}.
    NEVER returns a number — see module docstring for why."""
    client = _get_groq_client()
    if client:
        try:
            prompt = (
                f"Numeric column '{column_name}' is {null_pct}% missing. Its stats: {stats}. "
                f"Which fill strategy fits best — 'median', 'mean', 'forward-fill' (for "
                f"sequential/time-ordered data), or 'leave blank' (if missing-ness itself is "
                f"meaningful, or too much data is missing to safely fill)? Reply with ONLY the "
                f"strategy name, exactly as one of those four options."
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            strategy = resp.choices[0].message.content.strip().strip("'\"").lower()
            if strategy in NUMERIC_FILL_STRATEGIES:
                return {"strategy": strategy, "reason": "AI-suggested strategy"}
        except Exception:
            pass
    # deterministic fallback: heavy missingness -> don't guess; otherwise median (robust to outliers)
    if null_pct > 30:
        return {"strategy": "leave blank", "reason": f"{null_pct}% missing is too much to safely fill (no AI suggestion available)"}
    return {"strategy": "median", "reason": "Default — robust to outliers (no AI suggestion available)"}


def build_suggestions(cleaning_report: dict, columns: dict) -> dict:
    """
    Takes a cleaning_report (from cleaning_agent.clean_and_reprofile) and
    returns a matching "suggestions" dict the UI can render next to each
    flagged issue, with an Apply action per suggestion.
    """
    suggestions = {"casing": {}, "null_categorical": {}, "null_numeric": {}}

    for col, clashes in cleaning_report.get("casing_flags", {}).items():
        for variants in clashes.values():
            suggestions["casing"][col] = suggest_casing_canonical(col, variants)

    for col, pct in cleaning_report.get("null_flags", {}).items():
        cp = columns.get(col)
        if not cp:
            continue
        if cp.semantic_type in ("categorical_low", "categorical_high", "text", "boolean"):
            suggestions["null_categorical"][col] = suggest_categorical_fill(col, cp.sample_values)
        elif cp.semantic_type in ("numeric_continuous", "numeric_discrete"):
            suggestions["null_numeric"][col] = suggest_numeric_fill_strategy(col, cp.stats, pct)

    return suggestions
