"""
automation_agent.py  ("Repeater")

Lets the user save a dashboard configuration (which attributes, which chart
overrides, which pair comparisons, which design skill) as a named
"template", keyed by the schema of the file it was built from. New Excel
files that match a saved template's schema get the exact same pipeline
applied automatically — no manual re-clicking.

Two matching paths, in order:
  1. EXACT — schema_signature() matches byte-for-byte (same column names +
     same inferred semantic types). Fast path, common case (same report,
     re-exported next week).
  2. FUZZY — handles schema drift (a column got renamed or reordered).
     Each saved column is matched to the closest new column by name
     similarity, but ONLY among new columns that share the same semantic
     type — type mismatch is a hard disqualifier, name similarity alone is
     not enough (a "Region" column should never fuzzy-match onto a
     "Revenue" column just because a threshold was hit). A saved config is
     accepted only if at least MIN_COVERAGE of its columns found a match;
     unmatched columns are simply dropped (logged), not guessed at.
"""

import json
from difflib import SequenceMatcher
from pathlib import Path

from src.excel_parser import schema_signature

MIN_NAME_SIMILARITY = 0.55
MIN_COVERAGE = 0.7


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", " ").replace("-", " ")


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_schema(saved_columns: dict, new_columns: dict) -> tuple[dict | None, float]:
    """
    saved_columns / new_columns: {column_name: semantic_type}
    Returns (mapping {saved_name: new_name}, coverage 0-1) or (None, coverage)
    if coverage is below MIN_COVERAGE.
    """
    remaining_new = dict(new_columns)
    mapping = {}

    for old_name, old_type in saved_columns.items():
        best_name, best_score = None, 0.0
        for new_name, new_type in remaining_new.items():
            if new_type != old_type:
                continue  # type mismatch is a hard disqualifier, never fuzzy across types
            sim = _name_similarity(old_name, new_name)
            if sim > best_score:
                best_name, best_score = new_name, sim
        if best_name and (best_name == old_name or best_score >= MIN_NAME_SIMILARITY):
            mapping[old_name] = best_name
            del remaining_new[best_name]

    coverage = len(mapping) / max(len(saved_columns), 1)
    if coverage >= MIN_COVERAGE:
        return mapping, coverage
    return None, coverage


def build_config(
    template_name: str,
    profile: dict,
    selected_attributes: list[str],
    chart_overrides: dict,
    pairs: list[tuple[str, str]],
    design_skill_id: str | None,
) -> dict:
    return {
        "template_name": template_name,
        "schema_signature": schema_signature(profile),
        "columns": {name: cp.semantic_type for name, cp in profile["columns"].items()},
        "selected_attributes": selected_attributes,
        "chart_overrides": chart_overrides,
        "pairs": [list(p) for p in pairs],
        "design_skill_id": design_skill_id,
    }


def save_config(
    configs_dir: str,
    template_name: str,
    profile: dict,
    selected_attributes: list[str],
    chart_overrides: dict,
    pairs: list[tuple[str, str]],
    design_skill_id: str | None,
) -> str:
    """Disk-backed save — for the local/CLI automation flow (see build_config
    for the in-memory equivalent used by the hosted app's session state)."""
    Path(configs_dir).mkdir(parents=True, exist_ok=True)
    config = build_config(template_name, profile, selected_attributes, chart_overrides, pairs, design_skill_id)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in template_name)
    path = Path(configs_dir) / f"{safe_name}.json"
    path.write_text(json.dumps(config, indent=2))
    return str(path)


def list_configs(configs_dir: str) -> list[dict]:
    configs = []
    for f in sorted(Path(configs_dir).glob("*.json")):
        try:
            configs.append(json.loads(f.read_text()))
        except Exception:
            continue
    return configs


def find_matching_config_from_list(profile: dict, configs: list[dict]) -> dict | None:
    """
    Core matcher — works on an in-memory list of config dicts. Used directly
    by the hosted app's batch mode (configs = st.session_state.templates,
    scoped to that browser session only — see the note in app.py about why
    disk-based storage isn't the right default for a shared hosted app).

    Returns {"config": {...}, "mapping": {...}, "coverage": float, "match_type": str}
    or None if nothing matches well enough.
    """
    new_columns = {name: cp.semantic_type for name, cp in profile["columns"].items()}
    sig = schema_signature(profile)

    for cfg in configs:
        if cfg["schema_signature"] == sig:
            identity_map = {c: c for c in cfg["columns"]}
            return {"config": cfg, "mapping": identity_map, "coverage": 1.0, "match_type": "exact"}

    best = None
    for cfg in configs:
        mapping, coverage = match_schema(cfg["columns"], new_columns)
        if mapping and (best is None or coverage > best["coverage"]):
            best = {"config": cfg, "mapping": mapping, "coverage": coverage, "match_type": "fuzzy"}

    return best


def find_matching_config(profile: dict, configs_dir: str) -> dict | None:
    """Disk-backed wrapper — used by the local automation_runner.py CLI,
    where a single user's own machine makes a persistent configs/ folder
    the right call (no multi-tenant leakage concern)."""
    return find_matching_config_from_list(profile, list_configs(configs_dir))


def remap_config(config: dict, mapping: dict) -> dict:
    """Translates a saved config's column references through a schema mapping,
    dropping any references that didn't survive the match (schema drift)."""
    def remap_name(name):
        return mapping.get(name)

    selected = [remap_name(c) for c in config["selected_attributes"]]
    selected = [c for c in selected if c is not None]

    overrides = {}
    for old_name, chart in config["chart_overrides"].items():
        new_name = remap_name(old_name)
        if new_name:
            overrides[new_name] = chart

    pairs = []
    for a, b in config.get("pairs", []):
        new_a, new_b = remap_name(a), remap_name(b)
        if new_a and new_b:
            pairs.append((new_a, new_b))

    dropped = [c for c in config["columns"] if mapping.get(c) is None]

    return {
        "selected_attributes": selected,
        "chart_overrides": overrides,
        "pairs": pairs,
        "design_skill_id": config.get("design_skill_id"),
        "dropped_columns": dropped,
    }
