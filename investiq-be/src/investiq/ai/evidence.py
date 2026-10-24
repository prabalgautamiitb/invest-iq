from decimal import ROUND_HALF_UP, Decimal

from investiq.core.errors import AppError
from investiq.models.valuation import ValuationRecord, ValuationRun
from investiq.schemas.coach import CoachEvidence, CoachPlan, Fact, LessonEvidence, ReportBody

PROMPT_VERSION = "coach-selector-v1"


def number(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_evidence(
    record: ValuationRecord,
    run: ValuationRun,
    *,
    final: bool,
    current: bool,
    lessons: list[LessonEvidence],
) -> CoachEvidence:
    source = f"valuation:{record.id}:run:{run.id}"
    facts: list[Fact] = []

    def add(identifier: str, category: str, text: str, field: str) -> None:
        facts.append(
            Fact.model_validate(
                dict(id=identifier, category=category, text=text, source=source + ":" + field)
            )
        )

    add(
        "value",
        "summary",
        f"Snapshot portfolio value is {number(record.total_value)} virtual INR, including "
        f"{number(record.cash)} residual cash.",
        "total_value,cash",
    )
    add(
        "return",
        "summary",
        f"Portfolio return is {number(record.return_pct)}%, including the initial simulated fee.",
        "return_pct",
    )
    add(
        "rank",
        "summary",
        f"Snapshot rank is {record.rank} among {run.participant_count} ranked portfolios in "
        f"this run.",
        "rank,participant_count",
    )
    add(
        "benchmark",
        "benchmark",
        f"Benchmark return is {number(record.benchmark_return_pct)}%; portfolio excess "
        f"return is {number(record.excess_return_pct)} percentage points.",
        "benchmark_return_pct,excess_return_pct",
    )
    add(
        "concentration",
        "concentration",
        f"The largest holding is {number(record.largest_position_pct)}% of total value. "
        f"Holdings concentration HHI is {number(record.concentration_hhi)} on a 0–1 scale; a "
        f"larger value means greater concentration.",
        "largest_position_pct,concentration_hhi",
    )
    add(
        "diversification",
        "concentration",
        f"The snapshot contains {record.holding_count} holdings across {record.sector_count} "
        f"identified sectors. Counts alone do not establish an optimal allocation.",
        "holding_count,sector_count",
    )
    add(
        "drawdown",
        "review",
        f"Maximum drawdown across the available end-of-day snapshots, including the initial "
        f"fee drawdown, is {number(record.max_drawdown_pct)}%. Intraday losses are not "
        f"measured.",
        "max_drawdown_pct",
    )
    add(
        "costs",
        "review",
        f"The accepted submission includes a one-time simulated fee of {number(record.fee)} "
        f"virtual INR. Review costs and whole-share rounding alongside residual cash.",
        "fee,cash",
    )
    add(
        "allocation-review",
        "review",
        f"Review whether the {number(record.largest_position_pct)}% largest-position weight "
        f"matches your original simulation plan; the evidence does not record your "
        f"intentions.",
        "largest_position_pct",
    )
    positions = record.details["positions"]
    if positions:
        ordered = sorted(positions, key=lambda p: (Decimal(str(p["pnl"])), str(p["symbol"])))
        for label, position in [("largest", ordered[-1]), ("smallest", ordered[0])]:
            add(
                "contributor-" + label,
                "contribution",
                f"{position['symbol']} has the {label} holding contribution: "
                f"{number(Decimal(str(position['pnl'])))} virtual INR and "
                f"{number(Decimal(str(position['contribution_pct'])))} percentage points of "
                f"starting capital. Contributions exclude the portfolio-level fee.",
                "positions:" + str(position["instrument_id"]),
            )
        best, worst = ordered[-1], ordered[0]
        if Decimal(str(best["pnl"])) > 0:
            add(
                "positive-contribution",
                "worked",
                f"{best['symbol']} contributed positively in this snapshot: "
                f"{number(Decimal(str(best['pnl'])))} virtual INR. This observation does not "
                f"establish why it rose or validate a repeatable strategy.",
                "positions:" + str(best["instrument_id"]),
            )
        if Decimal(str(worst["pnl"])) < 0:
            add(
                "negative-contribution",
                "review",
                f"{worst['symbol']} contributed {number(Decimal(str(worst['pnl'])))} virtual "
                f"INR. Review the original rationale without assuming a trade, motive or "
                f"causal explanation.",
                "positions:" + str(worst["instrument_id"]),
            )
    return CoachEvidence(
        contest_id=run.contest_id,
        record_id=record.id,
        run_id=run.id,
        submission_id=record.submission_id,
        session_date=run.session_date,
        is_final=final,
        is_current=current,
        metric_version=run.calculation_version,
        facts=facts,
        lessons=lessons,
        limitations=[
            "Educational simulation using synthetic end-of-day prices; not investment "
            "recommendations or forecasts.",
            "The confirmed portfolio is locked. There is no trade history or evidence of "
            "sales, exits, motives or counterfactual returns.",
            "All numbers come from the referenced immutable valuation snapshot. Displayed "
            "decimals are rounded half-up to two places.",
            "Snapshot ranks and reports do not update in place. A later valuation requires a "
            "new report.",
            "The model selects evidence and learning priorities; validated server text "
            "supplies every displayed claim. It does not diagnose personal suitability.",
            *(
                []
                if final
                else [
                    "This is an interim snapshot; the contest has not been finalized at this run."
                ]
            ),
            *(
                []
                if current
                else [
                    "This snapshot was already behind the expected valuation date when the "
                    "report was requested."
                ]
            ),
        ],
    )


def validate_plan(evidence: CoachEvidence, plan: CoachPlan) -> ReportBody:
    facts = {f.id: f for f in evidence.facts}
    lessons = {str(lesson.version_id): lesson for lesson in evidence.lessons}
    fields = [
        (plan.focus_fact_ids, set(facts)),
        (plan.worked_fact_ids, {f.id for f in evidence.facts if f.category == "worked"}),
        (plan.review_fact_ids, {f.id for f in evidence.facts if f.category == "review"}),
        (plan.lesson_version_ids, set(lessons)),
    ]
    for selections, allowed in fields:
        if len(selections) != len(set(selections)) or not set(selections) <= allowed:
            raise AppError(
                422, "invalid_model_output", "The model returned unsupported evidence or citations"
            )
    questions = {
        "allocation": (
            "What allocation rule would you write down before your next simulation, "
            "and how would you review it?"
        ),
        "benchmark": (
            "What does the benchmark comparison explain, and what does it leave uncertain?"
        ),
        "evidence": (
            "Which observation is best supported by this snapshot, "
            "and what evidence would you need before explaining its cause?"
        ),
    }
    return ReportBody(
        summary=[
            f
            for f in evidence.facts
            if f.category in {"summary", "benchmark", "concentration", "contribution"}
        ],
        focus=[facts[i] for i in plan.focus_fact_ids],
        what_worked=[facts[i] for i in plan.worked_fact_ids],
        review_points=[facts[i] for i in plan.review_fact_ids],
        learning_actions=[lessons[i] for i in plan.lesson_version_ids],
        reflection_question=questions[plan.reflection],
        limitations=evidence.limitations,
    )
