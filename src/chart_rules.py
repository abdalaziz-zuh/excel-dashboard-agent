"""
chart_rules.py
Deterministic, rule-based chart-type recommendation. This is intentionally
NOT an LLM call: chart-type-for-data-shape is a solved, well-documented
problem (Cleveland & McGill / standard BI heuristics), so we keep it cheap,
fast, and 100% reproducible. The design agent uses this as the DEFAULT,
which the user can override, and the QA agent uses the same table to
validate whatever ends up selected.
"""

# single-column recommendations
SINGLE_COLUMN_RULES = {
    "numeric_continuous": "histogram",
    "numeric_discrete": "bar",
    "categorical_low": "pie",
    "categorical_high": "bar_top_n",   # only show top N to avoid clutter
    "datetime": "line_count_over_time",
    "boolean": "donut",
    "text": None,                      # no default chart, exclude from dashboard by default
}

# two-column combination recommendations, keyed by a frozenset-safe tuple
# order doesn't matter for lookup — see recommend_for_pair()
PAIR_RULES = {
    ("categorical_low", "numeric_continuous"): "grouped_bar",
    ("categorical_low", "numeric_discrete"): "grouped_bar",
    ("datetime", "numeric_continuous"): "line",
    ("datetime", "numeric_discrete"): "line",
    ("numeric_continuous", "numeric_continuous"): "scatter",
    ("categorical_low", "categorical_low"): "heatmap",
    ("datetime", "categorical_low"): "stacked_area",
}

# chart types considered inappropriate for a semantic type — used by the QA agent
CHART_MISUSE_RULES = {
    "pie": {
        "max_categories": 6,
        "invalid_for": {"numeric_continuous", "text", "categorical_high"},
    },
    "donut": {
        "max_categories": 6,
        "invalid_for": {"numeric_continuous", "text", "categorical_high"},
    },
    "line": {
        "invalid_for": {"categorical_low", "categorical_high", "text", "boolean"},
    },
    "scatter": {
        "invalid_for": {"categorical_low", "categorical_high", "text", "boolean", "datetime"},
    },
    "histogram": {
        "invalid_for": {"categorical_low", "categorical_high", "text", "boolean", "datetime"},
    },
}


# which chart types are acceptable for a given pair of semantic types —
# used by the QA agent to validate two-column tiles the same way
# CHART_MISUSE_RULES validates single-column tiles
PAIR_VALID_CHARTS = {
    frozenset({"categorical_low", "numeric_continuous"}): {"grouped_bar", "box"},
    frozenset({"categorical_low", "numeric_discrete"}): {"grouped_bar", "box"},
    frozenset({"datetime", "numeric_continuous"}): {"line"},
    frozenset({"datetime", "numeric_discrete"}): {"line"},
    frozenset({"numeric_continuous", "numeric_continuous"}): {"scatter"},
    frozenset({"categorical_low", "categorical_low"}): {"heatmap"},
    frozenset({"datetime", "categorical_low"}): {"stacked_area"},
}


def check_pair_misuse(chart_type: str, type_a: str, type_b: str) -> list[str]:
    key = frozenset({type_a, type_b})
    valid = PAIR_VALID_CHARTS.get(key)
    if valid is None:
        return [
            f"No validated chart mapping exists for a '{type_a}' + '{type_b}' pair — "
            f"'{chart_type}' is unverified for this combination."
        ]
    if chart_type not in valid:
        return [
            f"'{chart_type}' is not an appropriate pairing for '{type_a}' + '{type_b}' "
            f"(expected one of: {', '.join(sorted(valid))})."
        ]
    return []


def recommend_single(semantic_type: str) -> str | None:
    return SINGLE_COLUMN_RULES.get(semantic_type)


def recommend_for_pair(type_a: str, type_b: str) -> str | None:
    return PAIR_RULES.get((type_a, type_b)) or PAIR_RULES.get((type_b, type_a))


def check_misuse(chart_type: str, semantic_type: str, n_categories: int | None = None) -> list[str]:
    """Returns a list of human-readable problems, empty list if fine."""
    problems = []
    rule = CHART_MISUSE_RULES.get(chart_type)
    if not rule:
        return problems

    if semantic_type in rule.get("invalid_for", set()):
        problems.append(
            f"'{chart_type}' is not appropriate for a '{semantic_type}' column."
        )

    max_cat = rule.get("max_categories")
    if max_cat and n_categories is not None and n_categories > max_cat:
        problems.append(
            f"'{chart_type}' shown with {n_categories} categories (recommended max {max_cat}) "
            f"— consider 'bar_top_n' or grouping the rest into 'Other'."
        )

    return problems
