"""
orchestrator.py
Runs the full pipeline:

    cleaning_agent.clean_and_reprofile()      -- auto-fix safe issues, flag the rest
        -> design_agent.build_dashboard_spec()
        -> qa_agent.review_spec()
        -> [loop] design_agent.fix_issues() -> qa_agent.review_spec()
        -> (stop when score >= PASS_THRESHOLD or MAX_ITERATIONS hit)
    -> analysis_agent.analyze()               -- correlations + trends, outlier-aware
    -> report_agent.generate_report()

Two safety nets in the build<->check loop, per the earlier design discussion:
  1. MAX_ITERATIONS hard cap — no infinite loop.
  2. best-so-far tracking — if a "fix" pass makes the score WORSE
     (agent1 introduces a new problem while solving another), we keep the
     best-scoring version seen so far rather than shipping a regression.

Cleaning runs first and REPLACES profile for every downstream step —
column names are stable across cleaning (only rows/whitespace change), so
attribute/pair selections made against the pre-cleaning profile still
resolve correctly. Callers should use result["profile"] (the cleaned one)
for anything touching the dataframe afterward, e.g. exporting.
"""

from src.agents import design_agent, qa_agent, report_agent, cleaning_agent, analysis_agent

MAX_ITERATIONS = 4


def run_pipeline(
    profile: dict,
    selected_attributes: list[str],
    chart_overrides: dict[str, str] | None = None,
    design_skill_id: str | None = None,
    pairs: list[tuple[str, str]] | None = None,
) -> dict:
    cleaned = cleaning_agent.clean_and_reprofile(profile)
    profile = cleaned["profile"]
    cleaning_report = cleaned["cleaning_report"]

    spec = design_agent.build_dashboard_spec(
        profile, selected_attributes, chart_overrides, design_skill_id, pairs
    )
    review = qa_agent.review_spec(spec, profile)

    iteration_log = [{"iteration": 0, "spec": spec, "review": review}]
    best = iteration_log[0]

    iteration = 0
    while not review["passed"] and iteration < MAX_ITERATIONS:
        iteration += 1
        spec = design_agent.fix_issues(spec, profile, review["issues"])
        review = qa_agent.review_spec(spec, profile)
        entry = {"iteration": iteration, "spec": spec, "review": review}
        iteration_log.append(entry)

        if review["score"] > best["review"]["score"]:
            best = entry
        # if this pass regressed, next fix attempt still works off the
        # regressed spec (agent1 needs to see what it broke) — but we
        # never SHIP a regression, see final_spec below.

    final_spec = best["spec"]
    analysis = analysis_agent.analyze(profile)
    report_md = report_agent.generate_report(
        iteration_log, profile, final_spec["design_skill"], cleaning_report, analysis
    )

    return {
        "profile": profile,  # cleaned — use this, not the pre-cleaning profile, for rendering/export
        "final_spec": final_spec,
        "final_score": best["review"]["score"],
        "iterations_used": iteration,
        "iteration_log": iteration_log,
        "cleaning_report": cleaning_report,
        "analysis": analysis,
        "report_markdown": report_md,
    }
