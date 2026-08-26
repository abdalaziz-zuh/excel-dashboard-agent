"""
analysis_agent.py  ("Analyst" — runs after the dashboard is built)

Adds descriptive-statistics-level analysis on top of the cleaned data:
  - correlation between numeric columns (Pearson) — flags pairs with |r| >= 0.5
  - trend direction for datetime + numeric column pairs (simple linear slope
    sign, not a forecast — this says "revenue trended up over the period",
    not "revenue will be X next month")

Outlier detection already happens in cleaning_agent.py (IQR, flag-only) —
this agent doesn't duplicate that, it just adds the correlation/trend
layer report_agent needs.

Explicitly NOT attempted here: forecasting, clustering/segmentation,
causal claims. Those need modeling choices and validation this project
doesn't do — flagging that honestly rather than faking a shallow version.
"""

import pandas as pd

from src.agents.cleaning_agent import get_outlier_row_mask

MIN_CORRELATION = 0.5
CORRELATION_DISAGREEMENT_THRESHOLD = 0.2  # |raw_r - robust_r| above this gets flagged


def compute_correlations(df: pd.DataFrame, columns: dict) -> dict:
    numeric_cols = [name for name, cp in columns.items()
                     if cp.semantic_type in ("numeric_continuous", "numeric_discrete")]
    if len(numeric_cols) < 2:
        return {"matrix": None, "notable_pairs": []}

    outlier_mask = get_outlier_row_mask(df, columns)
    df_robust = df[~outlier_mask]

    corr = df[numeric_cols].corr(numeric_only=True)
    corr_robust = df_robust[numeric_cols].corr(numeric_only=True) if outlier_mask.any() else corr

    notable_pairs = []
    seen = set()
    for a in numeric_cols:
        for b in numeric_cols:
            if a == b or (b, a) in seen:
                continue
            seen.add((a, b))
            r = corr.loc[a, b]
            r_robust = corr_robust.loc[a, b] if outlier_mask.any() else r
            if pd.isna(r):
                continue
            qualifies = abs(r) >= MIN_CORRELATION or (pd.notna(r_robust) and abs(r_robust) >= MIN_CORRELATION)
            if not qualifies:
                continue
            entry = {"a": a, "b": b, "r": round(float(r), 2)}
            if outlier_mask.any() and pd.notna(r_robust) and abs(r - r_robust) >= CORRELATION_DISAGREEMENT_THRESHOLD:
                entry["r_excluding_outliers"] = round(float(r_robust), 2)
                entry["outliers_excluded"] = int(outlier_mask.sum())
            notable_pairs.append(entry)

    notable_pairs.sort(key=lambda p: abs(p.get("r_excluding_outliers", p["r"])), reverse=True)
    return {"matrix": corr, "notable_pairs": notable_pairs}


def compute_trends(df: pd.DataFrame, columns: dict) -> list:
    """For every datetime column paired with every numeric column, fits a
    simple linear trend (numpy polyfit degree 1) and reports direction +
    how much of the variance it explains (R²) — low R² means 'no clear
    trend', which we say plainly rather than reporting a slope that isn't
    really there. Also fits the same trend excluding IQR outliers, and
    surfaces both when a single extreme point is swinging the result."""
    import numpy as np

    def fit(sub):
        x = sub.iloc[:, 0].map(pd.Timestamp.toordinal).values.astype(float)
        y = sub.iloc[:, 1].values.astype(float)
        if len(x) < 5 or x.std() == 0:
            return None
        slope, intercept = np.polyfit(x, y, 1)
        y_pred = slope * x + intercept
        ss_res = ((y - y_pred) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        direction = "no clear trend" if r_squared < 0.1 else ("increasing" if slope > 0 else "decreasing")
        return {"direction": direction, "r_squared": round(float(r_squared), 2)}

    date_cols = [name for name, cp in columns.items() if cp.semantic_type == "datetime"]
    numeric_cols = [name for name, cp in columns.items()
                     if cp.semantic_type in ("numeric_continuous", "numeric_discrete")]
    outlier_mask = get_outlier_row_mask(df, columns)
    trends = []

    for date_col in date_cols:
        for num_col in numeric_cols:
            sub = df[[date_col, num_col]].dropna()
            raw = fit(sub)
            if raw is None:
                continue

            entry = {"date_col": date_col, "num_col": num_col, **raw}

            if outlier_mask.any():
                sub_robust = df.loc[~outlier_mask, [date_col, num_col]].dropna()
                robust = fit(sub_robust)
                if robust and (robust["direction"] != raw["direction"] or abs(robust["r_squared"] - raw["r_squared"]) >= 0.2):
                    entry["excluding_outliers"] = robust
                    entry["outliers_excluded"] = int(outlier_mask.sum())

            trends.append(entry)

    return trends


def analyze(profile: dict) -> dict:
    df = profile["dataframe"]
    columns = profile["columns"]
    correlations = compute_correlations(df, columns)
    trends = compute_trends(df, columns)
    return {"correlations": correlations, "trends": trends}
