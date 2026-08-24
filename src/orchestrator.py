"""
orchestrator.py
Runs the full pipeline:

    design_agent.build_dashboard_spec()
        -> qa_agent.review_spec()
        -> [loop] design_agent.fix_issues() -> qa_agent.review_spec()
        -> (stop when score >= PASS_THRESHOLD or MAX_ITERATIONS hit)
    -> report_agent.generate_report()

Two safety nets baked in, per the earlier design discussion:
  1. MAX_ITERATIONS hard cap — no infinite loop.
  2. best-so-far tracking — if a "fix" pass makes the score WORSE
     (agent1 introduces a new problem while solving another), we keep the
     best-scoring version seen so far rather than shipping a regression.
"""

from src.agents import design_agent, qa_agent, report_agent

MAX_ITERATIONS = 4


def run_pipeline(
    profile: dict,
    selected_attributes: list[str],
    chart_overrides: dict[str, str] | None = None,
    design_skill_id: str | None = None,
    pairs: list[tuple[str, str]] | None = None,
) -> dict:
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
    report_md = report_agent.generate_report(iteration_log, profile, final_spec["design_skill"])

    return {
        "final_spec": final_spec,
        "final_score": best["review"]["score"],
        "iterations_used": iteration,
        "iteration_log": iteration_log,
        "report_markdown": report_md,
    }
