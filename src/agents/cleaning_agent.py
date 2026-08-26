"""
cleaning_agent.py  ("Cleaner" — runs before Agent 1)

Two tiers, deliberately kept separate:

  AUTO-FIXED (safe, reversible, never loses information the user could
  plausibly want):
    - exact duplicate rows -> dropped
    - leading/trailing whitespace in text columns -> trimmed

  FLAGGED ONLY (never auto-applied — these are judgment calls that could
  silently damage real data if we guessed wrong, same philosophy as the QA
  agent never guessing a chart type):
    - missing values (nulls) — a % per column
    - inconsistent casing in a categorical column (e.g. "north"/"North"/"NORTH"
      likely meaning the same category, but merging them is a decision, not
      a fact)
    - numeric outliers (IQR method) — flagged with count, not removed

Returns the same profile dict shape as excel_parser, plus a "cleaning_report"
key the report agent (Agent 4 now) folds into the final output.
"""

import pandas as pd

from src.excel_parser import profile_dataframe


def _find_inconsistent_casing(df: pd.DataFrame, columns: dict) -> dict:
    """For each categorical_low column, checks whether different-case
    versions of the same value both appear (e.g. 'north' and 'North')."""
    findings = {}
    for name, cp in columns.items():
        if cp.semantic_type != "categorical_low":
            continue
        series = df[name].dropna().astype(str)
        lowered_groups = {}
        for val in series.unique():
            lowered_groups.setdefault(val.strip().lower(), set()).add(val)
        clashes = {k: sorted(v) for k, v in lowered_groups.items() if len(v) > 1}
        if clashes:
            findings[name] = clashes
    return findings


def get_outlier_row_mask(df: pd.DataFrame, columns: dict) -> pd.Series:
    """Boolean mask, True for any row that's an IQR outlier in AT LEAST ONE
    numeric column. Used by analysis_agent to compute a 'robust' view
    alongside the raw one — a single extreme point can otherwise dominate
    a correlation coefficient or a linear trend fit and quietly mislead."""
    mask = pd.Series(False, index=df.index)
    for name, cp in columns.items():
        if cp.semantic_type not in ("numeric_continuous", "numeric_discrete"):
            continue
        s = df[name]
        valid = s.dropna()
        if len(valid) < 4:
            continue
        q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask |= (s < lower) | (s > upper)
    return mask.fillna(False)


def _find_outliers_iqr(df: pd.DataFrame, columns: dict) -> dict:
    findings = {}
    for name, cp in columns.items():
        if cp.semantic_type not in ("numeric_continuous", "numeric_discrete"):
            continue
        s = df[name].dropna()
        if len(s) < 4:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = s[(s < lower) | (s > upper)]
        if len(outliers) > 0:
            findings[name] = {
                "count": int(len(outliers)),
                "pct": round(len(outliers) / len(s) * 100, 1),
                "bounds": [round(float(lower), 2), round(float(upper), 2)],
            }
    return findings


def apply_casing_fix(df: pd.DataFrame, column: str, canonical: str, variants: list[str]) -> pd.DataFrame:
    df = df.copy()
    df[column] = df[column].replace({v: canonical for v in variants if v != canonical})
    return df


def apply_categorical_fill(df: pd.DataFrame, column: str, label: str) -> pd.DataFrame:
    df = df.copy()
    df[column] = df[column].fillna(label)
    return df


def apply_numeric_fill(df: pd.DataFrame, column: str, strategy: str) -> pd.DataFrame:
    """The actual fill VALUE is always computed here, deterministically,
    from the real data — never suggested or invented by the LLM (see
    suggestion_agent.py docstring)."""
    df = df.copy()
    if strategy == "median":
        df[column] = df[column].fillna(df[column].median())
    elif strategy == "mean":
        df[column] = df[column].fillna(df[column].mean())
    elif strategy == "forward-fill":
        df[column] = df[column].ffill()
    # "leave blank" -> no-op, intentionally
    return df


def clean_and_reprofile(profile: dict) -> dict:
    """
    Takes a profile (from excel_parser.profile_excel/profile_dataframe),
    applies the safe auto-fixes, and returns:
      {
        "profile": <re-profiled dict on the cleaned dataframe>,
        "cleaning_report": {
            "duplicates_removed": int,
            "whitespace_trimmed_columns": [...],
            "null_flags": {col: pct, ...},
            "casing_flags": {col: {lowered_value: [variants]}, ...},
            "outlier_flags": {col: {...}, ...},
        }
      }
    """
    df = profile["dataframe"].copy()
    columns = profile["columns"]

    # ── auto-fix: exact duplicate rows ──
    n_before = len(df)
    df = df.drop_duplicates()
    duplicates_removed = n_before - len(df)

    # ── auto-fix: whitespace trimming on text-like columns ──
    trimmed_columns = []
    for name, cp in columns.items():
        if cp.semantic_type in ("text", "categorical_low", "categorical_high"):
            if df[name].dtype == object or pd.api.types.is_string_dtype(df[name]):
                original = df[name]
                trimmed = original.where(original.isna(), original.astype(str).str.strip())
                if not trimmed.equals(original):
                    df[name] = trimmed
                    trimmed_columns.append(name)

    # ── re-profile the cleaned dataframe (row count / stats may have shifted) ──
    new_profile = profile_dataframe(df, profile.get("sheet_name", 0))

    # ── flag-only checks, run against the CLEANED data ──
    null_flags = {name: cp.null_pct for name, cp in new_profile["columns"].items() if cp.null_pct > 0}
    casing_flags = _find_inconsistent_casing(df, new_profile["columns"])
    outlier_flags = _find_outliers_iqr(df, new_profile["columns"])

    cleaning_report = {
        "duplicates_removed": int(duplicates_removed),
        "whitespace_trimmed_columns": trimmed_columns,
        "null_flags": null_flags,
        "casing_flags": casing_flags,
        "outlier_flags": outlier_flags,
    }

    return {"profile": new_profile, "cleaning_report": cleaning_report}
