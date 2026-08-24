"""
renderer.py
Turns a dashboard-spec tile into a Plotly figure, themed with the chosen
design skill's colors/fonts. Handles both single-column tiles (histogram,
bar, pie...) and two-column pair tiles (grouped_bar, scatter, line,
heatmap, stacked_area, box) — the pair types come from chart_rules.PAIR_RULES
and are validated by qa_agent before ever reaching here.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def _base_layout(fig, tile, design_skill):
    fig.update_layout(
        title=tile["title"],
        paper_bgcolor=design_skill["surface"],
        plot_bgcolor=design_skill["surface"],
        font=dict(color=design_skill["text_primary"], family=design_skill.get("font", "sans-serif")),
        showlegend=True,
        margin=dict(t=48, l=24, r=24, b=24),
    )
    grid_color = "rgba(255,255,255,0.08)" if design_skill.get("chart_style", {}).get("gridlines") else "rgba(0,0,0,0)"
    fig.update_xaxes(showgrid=True, gridcolor=grid_color, color=design_skill["text_secondary"])
    fig.update_yaxes(showgrid=True, gridcolor=grid_color, color=design_skill["text_secondary"])
    return fig


def _render_single(tile, df, palette):
    col = tile["columns"][0]
    chart_type = tile["chart_type"]

    if chart_type == "histogram":
        return px.histogram(df, x=col, color_discrete_sequence=palette)
    if chart_type == "bar":
        counts = df[col].value_counts().reset_index()
        counts.columns = [col, "count"]
        return px.bar(counts, x=col, y="count", color_discrete_sequence=palette)
    if chart_type == "bar_top_n":
        counts = df[col].value_counts().head(10).reset_index()
        counts.columns = [col, "count"]
        return px.bar(counts, x=col, y="count", color_discrete_sequence=palette)
    if chart_type == "pie":
        counts = df[col].value_counts().reset_index()
        counts.columns = [col, "count"]
        return px.pie(counts, names=col, values="count", color_discrete_sequence=palette)
    if chart_type == "donut":
        counts = df[col].value_counts().reset_index()
        counts.columns = [col, "count"]
        return px.pie(counts, names=col, values="count", hole=0.5, color_discrete_sequence=palette)
    if chart_type == "line_count_over_time":
        s = df[col].value_counts().sort_index().reset_index()
        s.columns = [col, "count"]
        return px.line(s, x=col, y="count", color_discrete_sequence=palette)

    fig = go.Figure()
    fig.add_annotation(text=f"Chart type '{chart_type}' not wired in renderer", showarrow=False)
    return fig


def _render_pair(tile, df, palette):
    col_a, col_b = tile["columns"]
    type_a, type_b = tile["semantic_types"]
    chart_type = tile["chart_type"]

    if chart_type == "grouped_bar":
        cat_col, num_col = (col_a, col_b) if type_a.startswith("categorical") else (col_b, col_a)
        agg = df.groupby(cat_col, as_index=False)[num_col].mean().sort_values(num_col, ascending=False)
        return px.bar(agg, x=cat_col, y=num_col, color_discrete_sequence=palette)

    if chart_type == "box":
        cat_col, num_col = (col_a, col_b) if type_a.startswith("categorical") else (col_b, col_a)
        return px.box(df, x=cat_col, y=num_col, color_discrete_sequence=palette)

    if chart_type == "line":
        date_col, num_col = (col_a, col_b) if type_a == "datetime" else (col_b, col_a)
        s = df[[date_col, num_col]].dropna().sort_values(date_col)
        s = s.groupby(date_col, as_index=False)[num_col].sum()
        return px.line(s, x=date_col, y=num_col, color_discrete_sequence=palette)

    if chart_type == "scatter":
        return px.scatter(df, x=col_a, y=col_b, color_discrete_sequence=palette, opacity=0.7)

    if chart_type == "heatmap":
        cross = pd.crosstab(df[col_a], df[col_b])
        return px.imshow(cross, color_continuous_scale=[palette[-1], palette[0]], aspect="auto")

    if chart_type == "stacked_area":
        date_col, cat_col = (col_a, col_b) if type_a == "datetime" else (col_b, col_a)
        s = df.groupby([pd.Grouper(key=date_col, freq="W"), cat_col]).size().reset_index(name="count")
        return px.area(s, x=date_col, y="count", color=cat_col, color_discrete_sequence=palette)

    fig = go.Figure()
    fig.add_annotation(text=f"Pair chart type '{chart_type}' not wired in renderer", showarrow=False)
    return fig


def render_tile(tile: dict, df, design_skill: dict):
    palette = design_skill["accent_palette"]
    if len(tile["columns"]) == 2:
        fig = _render_pair(tile, df, palette)
    else:
        fig = _render_single(tile, df, palette)
    return _base_layout(fig, tile, design_skill)


# ── Light-theme chrome override ─────────────────────────────────────────
# design_skill still drives the DATA colors (bars/lines/slices) so charts
# keep visual variety across builds — this only overrides the chart's own
# background/gridlines/font so it sits cleanly on a white/light-gray page
# shell, regardless of which design_skill (some of which are dark, e.g.
# corporate_dark) was picked when the spec was built.
LIGHT_CHROME = {
    "surface": "#ffffff",
    "text_primary": "#212529",
    "text_secondary": "#6c757d",
}


def apply_light_chrome(fig):
    fig.update_layout(
        paper_bgcolor=LIGHT_CHROME["surface"],
        plot_bgcolor=LIGHT_CHROME["surface"],
        font=dict(color=LIGHT_CHROME["text_primary"]),
    )
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.06)", color=LIGHT_CHROME["text_secondary"])
    fig.update_yaxes(gridcolor="rgba(0,0,0,0.06)", color=LIGHT_CHROME["text_secondary"])
    return fig
