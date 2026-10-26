from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from investiq.analytics.investor_habits import assess_habits
from investiq.models.contest import Contest
from investiq.models.valuation import ValuationRecord, ValuationRun


def observation(weights=(20, 20, 20, 20, 20), industries=(0, 1, 2, 3, 4), pnl="100"):
    run_id = uuid4()
    positions = [{"instrument_id": str(uuid4()), "value": str(weight * 10)} for weight in weights]
    sectors = {i: uuid4() for i in set(industries)}
    mapping = {
        (run_id, p["instrument_id"]): sectors[i] for p, i in zip(positions, industries, strict=True)
    }
    record = ValuationRecord(
        id=uuid4(),
        run_id=run_id,
        holding_count=len(weights),
        holdings_value=Decimal(1000),
        largest_position_pct=Decimal(max(weights)),
        concentration_hhi=sum((Decimal(w) / 100) ** 2 for w in weights),
        max_drawdown_pct=Decimal("0.1"),
        pnl=Decimal(pnl),
        excess_return_pct=Decimal("-1"),
        sector_count=len(sectors),
        details={"positions": positions},
    )
    run = ValuationRun(id=run_id, session_date=date(2026, 10, 15))
    contest = Contest(id=uuid4(), name="Practice contest", status="running")
    return (record, run, contest), mapping


def test_spread_stock_choices_are_encouraged_without_equating_profit_with_skill():
    row, sectors = observation()
    strengths, improvements, stage, _ = assess_habits([row], sectors)
    assert {p.topic for p in strengths} == {"diversification", "position_sizing"}
    assert stage == "Encouraging start"
    by_topic = {p.topic: p for p in improvements}
    assert by_topic["risk_awareness"].assessment == "not_enough_data"
    assert by_topic["market_comparison"].assessment == "not_enough_data"
    assert "did not beat" in by_topic["market_comparison"].evidence_summary
    assert all(
        p.why_it_matters and p.next_step and p.assessment_basis for p in strengths + improvements
    )
    assert "contributed positively" not in str(strengths)


def test_five_profitable_stocks_in_one_industry_do_not_count_as_diversified():
    row, sectors = observation(industries=(0, 0, 0, 0, 0), pnl="100000")
    strengths, improvements, _, _ = assess_habits([row], sectors)
    assert "diversification" not in {p.topic for p in strengths}
    point = next(p for p in improvements if p.topic == "diversification")
    assert point.assessment == "practice"
    assert "100.00%" in point.evidence_summary
    assert "same industry can fall together" in point.why_it_matters


@pytest.mark.parametrize(
    "weights,industries",
    [
        ((40, 15, 15, 15, 15), (0, 1, 2, 3, 4)),
        ((20, 20, 20, 20, 20), (0, 0, 0, 1, 2)),
    ],
)
def test_company_and_industry_concentration_are_distinct_learning_checks(weights, industries):
    row, sectors = observation(weights, industries)
    strengths, improvements, _, _ = assess_habits([row], sectors)
    by_topic = {p.topic: p for p in strengths + improvements}
    if max(weights) > 25:
        assert by_topic["position_sizing"].assessment == "practice"
        assert by_topic["diversification"].assessment == "encouraging"
    else:
        assert by_topic["position_sizing"].assessment == "encouraging"
        assert by_topic["diversification"].assessment == "practice"


def test_missing_frozen_sector_data_and_quiet_markets_do_not_prove_risk_capacity():
    row, sectors = observation()
    sectors.pop(next(iter(sectors)))
    strengths, improvements, _, _ = assess_habits([row], sectors)
    by_topic = {p.topic: p for p in strengths + improvements}
    assert by_topic["diversification"].assessment == "not_enough_data"
    assert by_topic["risk_awareness"].assessment == "not_enough_data"
    assert "0.10%" in by_topic["risk_awareness"].evidence_summary
    assert "goals, time horizon" in by_topic["risk_awareness"].assessment_basis


def test_short_contests_ending_together_do_not_establish_consistency():
    rows, sectors = [], {}
    for _ in range(3):
        row, lookup = observation()
        row[2].status = "completed"
        rows.append(row)
        sectors.update(lookup)
    _, improvements, _, _ = assess_habits(rows, sectors)
    consistency = next(p for p in improvements if p.topic == "market_comparison")
    assert consistency.assessment == "not_enough_data"
    assert "3, across 1 different ending dates" in consistency.evidence_summary
    assert "too early" in consistency.text


def test_no_observations_cannot_manufacture_investor_traits():
    assert assess_habits([], {}) == ([], [], "", "")
