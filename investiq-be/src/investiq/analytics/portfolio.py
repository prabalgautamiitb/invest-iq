from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID

from investiq.core.errors import AppError
from investiq.schemas.contest import RulesInput
from investiq.schemas.portfolio import PositionInput


@dataclass(frozen=True)
class Allocation:
    quantities: dict[UUID, int]
    notionals: dict[UUID, Decimal]
    notional: Decimal
    fee: Decimal
    cash: Decimal


def allocate(
    rules: RulesInput, positions: list[PositionInput], prices: dict[UUID, Decimal]
) -> Allocation:
    """Whole shares; exact four-place notionals and one aggregate fee rounded to paise."""
    with localcontext() as context:
        context.prec = 50
        if not rules.min_holdings <= len(positions) <= rules.max_holdings:
            raise AppError(
                422, "holding_count", f"Choose {rules.min_holdings}–{rules.max_holdings} holdings"
            )
        weights = [p.weight_pct for p in positions if p.weight_pct is not None]
        if weights and sum(weights) > 100:
            raise AppError(422, "weight_total", "Total target weights cannot exceed 100%")
        fee_rate = Decimal(rules.simulated_cost_bps) / 10000
        # Budget reserve makes a 100% weight allocation affordable, including rounded fees.
        reserve = (rules.capital / (1 + fee_rate)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
        quantities, notionals = {}, {}
        for p in positions:
            price = prices[p.instrument_id]
            quantity = p.quantity
            if quantity is None:
                assert p.weight_pct is not None
                target = reserve * p.weight_pct / 100
                quantity = int((target / price).to_integral_value(rounding=ROUND_FLOOR))
            if quantity < 1 or quantity > 1000000000:
                raise AppError(
                    422, "invalid_share_count", "Each target must buy 1–1000000000 whole shares"
                )
            value = price * quantity
            if value * 10000 > rules.capital * rules.max_position_bps:
                raise AppError(422, "position_limit", "A position exceeds the frozen capital limit")
            quantities[p.instrument_id], notionals[p.instrument_id] = quantity, value
        notional = sum(notionals.values(), Decimal(0))
        fee = (notional * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cash = rules.capital - notional - fee
        if cash < 0:
            raise AppError(
                422, "insufficient_capital", "Holdings and simulated cost exceed capital"
            )
        return Allocation(quantities, notionals, notional, fee, cash)
