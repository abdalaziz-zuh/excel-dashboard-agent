"""
excel_parser.py
Reads an Excel file and infers a SEMANTIC type for every column, not just
the pandas dtype. This semantic type is what the rule-based chart
recommender (chart_rules.py) keys off of.

Semantic types:
    - numeric_continuous : lots of distinct float/int values (measurements, money)
    - numeric_discrete    : integers with few distinct values (counts, ratings)
    - datetime            : parseable dates/timestamps
    - categorical_low     : text/category with <= CATEGORICAL_LOW_MAX unique values
    - categorical_high    : text/category with many unique values (near-unique -> likely an ID)
    - boolean             : two-valued column
    - text                : free text (long strings, high cardinality, not boolean/id-like)
"""

from dataclasses import dataclass, field
import pandas as pd

CATEGORICAL_LOW_MAX = 12
NUMERIC_DISCRETE_MAX_UNIQUE = 10


@dataclass
class ColumnProfile:
    name: str
    semantic_type: str
    dtype: str
    n_unique: int
    n_nulls: int
    null_pct: float
    sample_values: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)  # min/max/mean for numeric, etc.


def _infer_semantic_type(series: pd.Series) -> str:
    s = series.dropna()
    if len(s) == 0:
        return "text"
    n_unique = s.nunique()

    # NOTE: don't gate this on `dtype == "O"` — pandas string-backend dtypes
    # (e.g. dtype 'str' with pyarrow) are not "O" but aren't numeric either,
    # which used to cause single-value text columns to be misread as boolean.
    if pd.api.types.is_bool_dtype(series):
        return "boolean"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    if pd.api.types.is_numeric_dtype(series):
        if n_unique == 2:
            return "boolean"  # e.g. a 0/1 flag column
        if n_unique <= NUMERIC_DISCRETE_MAX_UNIQUE:
            return "numeric_discrete"
        return "numeric_continuous"

    # everything else: text-like column (covers both legacy "O" dtype and
    # newer pandas string dtypes)
    try:
        parsed = pd.to_datetime(s, errors="raise", format="mixed")
        if parsed.notna().mean() > 0.9:
            return "datetime"
    except Exception:
        pass

    if n_unique == 2:
        return "boolean"
    if n_unique <= CATEGORICAL_LOW_MAX:
        return "categorical_low"
    if n_unique / max(len(s), 1) > 0.9:
        return "categorical_high"  # likely an ID column
    return "text"


def profile_excel(file_path: str, sheet_name=0) -> dict:
    """
    Returns {
        "sheet_name": str,
        "n_rows": int,
        "columns": {col_name: ColumnProfile, ...}
    }
    """
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]

    columns = {}
    for col in df.columns:
        series = df[col]
        sem_type = _infer_semantic_type(series)
        stats = {}
        if sem_type in ("numeric_continuous", "numeric_discrete"):
            stats = {
                "min": float(series.min()) if series.notna().any() else None,
                "max": float(series.max()) if series.notna().any() else None,
                "mean": float(series.mean()) if series.notna().any() else None,
            }
        elif sem_type in ("categorical_low", "categorical_high", "text", "boolean"):
            stats = {"top_values": series.value_counts().head(5).to_dict()}

        columns[col] = ColumnProfile(
            name=col,
            semantic_type=sem_type,
            dtype=str(series.dtype),
            n_unique=int(series.nunique()),
            n_nulls=int(series.isna().sum()),
            null_pct=round(float(series.isna().mean()) * 100, 1),
            sample_values=series.dropna().head(3).tolist(),
            stats=stats,
        )

    return {"sheet_name": str(sheet_name), "n_rows": len(df), "columns": columns, "dataframe": df}


def schema_signature(profile: dict) -> str:
    """
    A stable fingerprint of a file's schema (column names + semantic types),
    used by the automation agent to match new files against a saved config
    even if row data changes. Order-independent and tolerant of column
    renames is NOT handled here (see agents/design_agent.match_schema for
    fuzzy matching) — this is the exact-match fast path.
    """
    cols = profile["columns"]
    parts = sorted(f"{name}:{cp.semantic_type}" for name, cp in cols.items())
    return "|".join(parts)
