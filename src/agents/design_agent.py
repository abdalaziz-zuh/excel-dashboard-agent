"""
design_agent.py  (Agent 1 — "Builder")

Responsibilities:
  1. build_dashboard_spec(): turn the user's checkbox selections into a
     concrete dashboard spec (chart per attribute/pair, using chart_rules
     defaults unless the user overrode them) and attach a design skill
     (visual theme) from src/design_skills/.
  2. fix_issues(): given the QA agent's list of problems, patch the spec
     (swap a bad chart type, cap category count, add missing titles) and
     return a new version. This is what closes the build -> check -> fix
     loop from the orchestrator.

The LLM (Groq) is used ONLY for things that are genuinely subjective/
creative: writing chart titles/captions and picking between multiple
otherwise-valid design skills. Chart-type correctness itself is rule-based
(see chart_rules.py) — we don't want the "is this the right chart" question
answered by an LLM that can hallucinate a plausible-sounding wrong answer.
"""

import json
import random
from pathlib import Path

from src import chart_rules
from src.agents.groq_client import get_groq_client  # noqa: F401 — kept for the future real design-LLM upgrade noted in README

DESIGN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "design_skills"


def _load_design_skills() -> list[dict]:
    skills = []
    for f in sorted(DESIGN_SKILLS_DIR.glob("*.json")):
        skills.append(json.loads(f.read_text()))
    return skills


def pick_design_skill(profile: dict, previous_skill_id: str | None = None) -> dict:
    """
    Picks a design skill. Simple, explainable heuristic (no LLM needed):
    rotate away from whatever was used last time for the same schema, so
    repeated runs via the automation agent don't all look identical.
    """
    skills = _load_design_skills()
    candidates = [s for s in skills if s["id"] != previous_skill_id] or skills
    return random.choice(candidates)


def _default_title(chart_type: str, cols: list[str]) -> str:
    return f"{chart_type.replace('_', ' ').title()} — {' vs '.join(cols)}"


def build_dashboard_spec(
    profile: dict,
    selected_attributes: list[str],
    chart_overrides: dict[str, str] | None = None,
    design_skill_id: str | None = None,
    pairs: list[tuple[str, str]] | None = None,
) -> dict:
    """
    selected_attributes: columns the user checked to include (single-column tiles)
    chart_overrides: {column: chart_type} — user's manual picks, override the
                      rule-based single-column default
    pairs: [(col_a, col_b), ...] — columns the user explicitly wants compared
           in a two-column tile (e.g. Revenue by Region). Chart type comes
           from chart_rules.recommend_for_pair(); there is no per-pair
           override in the MVP UI, keeping the rubric unambiguous.
    Returns a dashboard spec: {
        "design_skill": {...},
        "tiles": [{"columns": [...], "chart_type": "...", "title": "..."}]
    }
    """
    chart_overrides = chart_overrides or {}
    pairs = pairs or []
    columns = profile["columns"]
    tiles = []

    for col in selected_attributes:
        cp = columns[col]
        override = chart_overrides.get(col)
        chart_type = override or chart_rules.recommend_single(cp.semantic_type)
        if not chart_type:
            continue  # e.g. free-text column with no sensible default chart
        tiles.append({
            "columns": [col],
            "semantic_types": [cp.semantic_type],
            "chart_type": chart_type,
            "title": _default_title(chart_type, [col]),
        })

    for col_a, col_b in pairs:
        cp_a, cp_b = columns[col_a], columns[col_b]
        chart_type = chart_rules.recommend_for_pair(cp_a.semantic_type, cp_b.semantic_type)
        if not chart_type:
            continue  # no sensible pairing for this type combo, skip rather than guess
        tiles.append({
            "columns": [col_a, col_b],
            "semantic_types": [cp_a.semantic_type, cp_b.semantic_type],
            "chart_type": chart_type,
            "title": _default_title(chart_type, [col_a, col_b]),
        })

    skills = _load_design_skills()
    if design_skill_id:
        design_skill = next((s for s in skills if s["id"] == design_skill_id), skills[0])
    else:
        design_skill = pick_design_skill(profile)

    return {"design_skill": design_skill, "tiles": tiles}


def fix_issues(spec: dict, profile: dict, issues: list[dict]) -> dict:
    """
    Applies the QA agent's flagged issues to the spec and returns a new
    (patched) spec. issues: [{"tile_index": int, "problems": [str, ...]}]
    Pure rule-based patch — no LLM call, so this step is fast, free, and
    deterministic, which matters since it can run multiple times per loop.
    """
    new_spec = json.loads(json.dumps(spec))  # deep copy, spec is JSON-safe
    columns = profile["columns"]

    for issue in issues:
        idx = issue["tile_index"]
        tile = new_spec["tiles"][idx]

        if len(tile["columns"]) == 2:
            col_a, col_b = tile["columns"]
            type_a, type_b = columns[col_a].semantic_type, columns[col_b].semantic_type
            for problem in issue["problems"]:
                if "not an appropriate pairing" in problem or "unverified for this combination" in problem:
                    fallback = chart_rules.recommend_for_pair(type_a, type_b)
                    if fallback:
                        tile["chart_type"] = fallback
                        tile["title"] = _default_title(fallback, tile["columns"])
                    else:
                        tile["_drop"] = True  # no valid pairing exists — orchestrator/QA will still see it flagged; simplest safe fallback
            continue

        col = tile["columns"][0]
        cp = columns[col]

        for problem in issue["problems"]:
            if "not appropriate for" in problem:
                # fall back to the rule-based default for this semantic type
                fallback = chart_rules.recommend_single(cp.semantic_type) or "bar_top_n"
                tile["chart_type"] = fallback
                tile["title"] = _default_title(fallback, tile["columns"])
            elif "recommended max" in problem and "categories" in problem:
                tile["chart_type"] = "bar_top_n"
                tile["title"] = _default_title("bar_top_n", tile["columns"])

    # drop any tiles marked unfixable (no valid pairing found)
    new_spec["tiles"] = [t for t in new_spec["tiles"] if not t.get("_drop")]
    return new_spec
