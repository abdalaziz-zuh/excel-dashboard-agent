"""
qa_agent.py  (Agent 2 — "Reviewer")

Scores a dashboard spec 0-100 against an explicit rubric and returns a
structured issue list the design agent can act on. This is deliberately
rule-based/deterministic for the parts that HAVE a right answer (chart-type
correctness, category overload, missing titles), so the build<->check loop
actually converges instead of oscillating on a fuzzy LLM opinion each time.

Score bands:
    90-100 : ship it
    70-89  : minor issues, one more fix pass recommended
    <70    : real problems, must loop

The orchestrator stops looping when score >= PASS_THRESHOLD or
max_iterations is hit — whichever comes first.
"""

from src import chart_rules

PASS_THRESHOLD = 90
POINTS_PER_PROBLEM = 15
POINTS_MISSING_TITLE = 5


def review_spec(spec: dict, profile: dict) -> dict:
    """
    Returns {
        "score": int (0-100),
        "issues": [{"tile_index": int, "problems": [str, ...]}],
        "passed": bool
    }
    """
    columns = profile["columns"]
    tiles = spec["tiles"]
    all_issues = []
    total_deductions = 0

    for i, tile in enumerate(tiles):
        problems = []

        if len(tile["columns"]) == 2:
            col_a, col_b = tile["columns"]
            type_a, type_b = columns[col_a].semantic_type, columns[col_b].semantic_type
            problems += chart_rules.check_pair_misuse(tile["chart_type"], type_a, type_b)
        else:
            col = tile["columns"][0]
            cp = columns[col]
            n_categories = cp.n_unique if cp.semantic_type.startswith("categorical") else None
            problems += chart_rules.check_misuse(tile["chart_type"], cp.semantic_type, n_categories)
            if cp.null_pct > 30:
                problems.append(
                    f"Column '{col}' is {cp.null_pct}% empty — chart may be misleading; "
                    f"consider flagging data completeness to the user."
                )

        if not tile.get("title"):
            problems.append("Tile is missing a title.")
            total_deductions += POINTS_MISSING_TITLE

        total_deductions += POINTS_PER_PROBLEM * len(
            [p for p in problems if "missing a title" not in p]
        )

        if problems:
            all_issues.append({"tile_index": i, "problems": problems})

    score = max(0, 100 - total_deductions)
    return {
        "score": score,
        "issues": all_issues,
        "passed": score >= PASS_THRESHOLD,
    }
