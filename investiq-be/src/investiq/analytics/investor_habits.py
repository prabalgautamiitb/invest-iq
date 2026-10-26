"""Plain-language learning checks, not a financial suitability or investor-quality score.

The 5-company/3-industry/50%-industry and 25%-company checks are explicit product
teaching checkpoints, not universal investment rules. Outcome alone never establishes
discipline, emotional reactions, personal risk tolerance, or capacity to absorb losses.
"""

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from investiq.models.contest import Contest
from investiq.models.valuation import ValuationRecord, ValuationRun
from investiq.schemas.coach import OverviewPoint

Observation = tuple[ValuationRecord, ValuationRun, Contest]


def pct(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def assess_habits(
    observations: list[Observation],
    sectors: dict[tuple[UUID, str], UUID | None],
) -> tuple[list[OverviewPoint], list[OverviewPoint], str, str]:
    if not observations:
        return [], [], "", ""
    count = len(observations)
    strengths: list[OverviewPoint] = []
    improvements: list[OverviewPoint] = []

    def point(
        topic: str,
        title: str,
        assessment: str,
        text: str,
        why: str,
        practice: str,
        evidence: str,
        basis: str,
        example: Observation,
    ) -> None:
        record, run, contest = example
        item = OverviewPoint.model_validate(
            dict(
                topic=topic,
                title=title,
                assessment=assessment,
                text=text,
                why_it_matters=why,
                next_step=practice,
                evidence_summary=evidence,
                assessment_basis=basis,
                source=f"valuation:{record.id}:run:{run.id}",
                contest_id=contest.id,
                contest_name=contest.name,
                session_date=run.session_date,
            )
        )
        (strengths if assessment == "encouraging" else improvements).append(item)

    spreads: list[tuple[Observation, Decimal | None]] = []
    balanced: list[Observation] = []
    concentrated: list[Observation] = []
    unknown: list[Observation] = []
    for observation in observations:
        record, _, _ = observation
        amounts: dict[UUID, Decimal] = {}
        missing = False
        positions = record.details.get("positions", [])
        for position in positions:
            sector = sectors.get((record.run_id, str(position["instrument_id"])))
            if sector is None:
                missing = True
                continue
            amounts[sector] = amounts.get(sector, Decimal(0)) + Decimal(str(position["value"]))
        largest = max(amounts.values()) / record.holdings_value * 100 if amounts else None
        spreads.append((observation, largest))
        if missing or not positions or largest is None:
            unknown.append(observation)
        elif record.holding_count >= 5 and len(amounts) >= 3 and largest <= 50:
            balanced.append(observation)
        else:
            concentrated.append(observation)

    spread_basis = (
        "Learning checkpoint: at least 5 companies across at least 3 identified industries, "
        "with no industry above half of the stock value. These are teaching checks, not a "
        "recommended allocation. Company counts alone do not establish diversification, "
        "and this stock-only contest cannot assess a full mix of asset types."
    )
    if concentrated:
        example = max(concentrated, key=lambda row: row[0].concentration_hhi)
        share = next(share for row, share in spreads if row is example)
        record = example[0]
        point(
            "diversification",
            "Spread your risk across industries",
            "practice",
            f"You spread your investments in {len(balanced)} of {count} portfolios. "
            "Some still rely heavily on too few companies or industries.",
            "Several stocks from the same industry can fall together. A bigger stock list "
            "does not always mean your risk is spread out.",
            "Before your next simulation, group your stocks by industry and check where "
            "most of your virtual money sits.",
            f"Example: {record.holding_count} companies across {record.sector_count} industries; "
            f"the largest industry holds {pct(share or Decimal(0))}% of stock value.",
            spread_basis,
            example,
        )
    elif unknown:
        point(
            "diversification",
            "Check your industry mix",
            "not_enough_data",
            "Some saved stocks have no industry information, so we cannot reliably assess "
            "how well you spread your risk.",
            "You need to know which businesses face similar risks before judging diversification.",
            "Review the industry labels in your portfolio before deciding "
            "whether it is well spread.",
            f"Industry information is incomplete in {len(unknown)} of {count} portfolios.",
            spread_basis,
            unknown[0],
        )
    else:
        point(
            "diversification",
            "You spread your investments",
            "encouraging",
            "Your saved portfolios spread money across several companies and industries. "
            "That is a useful habit to keep practising.",
            "Spreading investments reduces reliance on one business or industry. It does not "
            "remove the risk of losses across the market.",
            "Keep checking both company weights and industry weights "
            "when you build your next portfolio.",
            f"All {count} portfolios meet this lesson's company and industry spread checks.",
            spread_basis,
            balanced[0],
        )

    heavy = [row for row in observations if row[0].largest_position_pct > 25]
    largest_holding = max(observations, key=lambda row: row[0].largest_position_pct)
    point(
        "position_sizing",
        "Avoid depending on one company" if heavy else "You limit single-company exposure",
        "practice" if heavy else "encouraging",
        "One company makes up more than a quarter of at least one portfolio, so its price "
        "has a large influence on your result."
        if heavy
        else "No single company makes up more than a quarter of your saved portfolios. "
        "You are avoiding reliance on one company alone.",
        "Even a company you believe in can disappoint. Position sizing means deciding "
        "how much of your portfolio depends on one choice.",
        "Write down your single-company limit before your next simulation, then check "
        "whether price changes have pushed a holding above it.",
        f"Largest company weight: {pct(largest_holding[0].largest_position_pct)}%. "
        f"{len(heavy)} of {count} portfolios exceed this lesson's checkpoint.",
        "We use 25% of total portfolio value as a teaching checkpoint, not a universal "
        "investment limit or a personal risk rating. "
        "Industry concentration is assessed separately.",
        largest_holding,
    )

    worst = max(observations, key=lambda row: row[0].max_drawdown_pct)
    point(
        "risk_awareness",
        "Know the risk you can live with",
        "not_enough_data",
        "Your results show what happened to your virtual money. They do not yet tell us "
        "how much loss you are comfortable with or could afford in real life.",
        "A useful investing habit is matching risk to your goals, time frame and ability "
        "to handle losses, rather than chasing the highest return.",
        "Imagine your virtual portfolio falling 10%. Write down what you would do, "
        "why, and how that fits your goal and time frame.",
        f"The largest recorded fall from an earlier high was {pct(worst[0].max_drawdown_pct)}%. "
        "This uses daily closing values and includes the initial simulation fee.",
        "Personal risk comfort and capacity need information about goals, time horizon "
        "and financial circumstances. We do not infer them from returns, concentration, "
        "a locked portfolio, or a short period with small losses.",
        worst,
    )

    completed = [row for row in observations if row[2].status == "completed"]
    ahead = sum(row[0].excess_return_pct > 0 for row in completed)
    profitable_but_behind = [
        row for row in observations if row[0].pnl > 0 and row[0].excess_return_pct <= 0
    ]
    different_ends = len({row[1].session_date for row in completed})
    if len(completed) < 3 or different_ends < 3:
        status, text = (
            "not_enough_data",
            (
                "It is too early to judge a consistent investing pattern. A short contest or "
                "a few contests ending together can reflect the same market move."
            ),
        )
    else:
        status, text = (
            "practice",
            (
                f"You finished ahead of the comparison index in {ahead} of {len(completed)} "
                "completed contests. Review what repeats across different periods before "
                "drawing conclusions about your skill."
            ),
        )
    point(
        "market_comparison",
        "Look beyond a profitable result",
        status,
        text,
        "A portfolio can make money simply because the wider market rose. Comparing "
        "with the contest's market index gives your result more context.",
        "After each contest, compare your return, the index return and the size of your "
        "losses. Write down one lesson to test next time.",
        f"{len(profitable_but_behind)} of {count} latest portfolios made a profit but did not "
        f"beat their comparison index. Completed contests: {len(completed)}, across "
        f"{different_ends} different ending dates.",
        "Three completed contests with different ending dates are a learning milestone, "
        "not statistical proof of skill. We do not infer patience, research quality, "
        "discipline, or emotional reactions from returns alone.",
        profitable_but_behind[0] if profitable_but_behind else observations[0],
    )

    if len(strengths) == 2:
        stage = (
            "Practising consistent habits"
            if len(completed) >= 3 and different_ends >= 3
            else "Encouraging start"
        )
        summary = (
            "Your saved portfolios show useful habits in spreading investments and limiting "
            "single-company exposure. Keep practising these habits and learning how risk "
            "and market conditions affect your results."
        )
    elif strengths:
        stage = "Building your foundations"
        summary = (
            "You have a useful habit to build on. Focus next on the risk checks below "
            "before judging yourself by returns."
        )
    else:
        stage = "Focus on the risk basics"
        summary = (
            "Start with how your money is spread and how much depends on each choice. "
            "A winning stock alone does not establish a strong investing process."
        )
    return strengths, improvements, stage, summary
