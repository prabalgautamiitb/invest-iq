from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID

from investiq.core.errors import AppError

SCALE = Decimal("0.00000001")


def percent(value: Decimal) -> Decimal:
    return value.quantize(SCALE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ValuedHolding:
    instrument_id: UUID
    symbol: str
    quantity: int
    initial_notional: Decimal
    price: Decimal
    sector_id: UUID | None


@dataclass(frozen=True)
class Metrics:
    holdings_value: Decimal
    total_value: Decimal
    pnl: Decimal
    return_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal
    peak_value: Decimal
    max_drawdown_pct: Decimal
    largest_position_pct: Decimal
    concentration_hhi: Decimal
    holding_count: int
    sector_count: int
    positions: list[dict[str, str | int]]


def value_portfolio(
    capital: Decimal,
    cash: Decimal,
    fee: Decimal,
    benchmark_initial: Decimal,
    benchmark_current: Decimal,
    holdings: list[ValuedHolding],
    previous_peak: Decimal | None = None,
    previous_drawdown: Decimal = Decimal(0),
) -> Metrics:
    with localcontext() as context:
        context.prec = 50
        values = [h.price * h.quantity for h in holdings]
        holdings_value = sum(values, Decimal(0))
        total = holdings_value + cash
        if not holdings or capital <= 0 or benchmark_initial <= 0 or total <= 0:
            raise AppError(409, "invalid_valuation_evidence", "Portfolio evidence cannot be valued")
        if (
            total >= Decimal("100000000000000000000")
            or abs((total - capital) / capital * 100) >= Decimal("1000000000000")
            or abs((benchmark_current / benchmark_initial - 1) * 100) >= Decimal("1000000000000")
        ):
            raise AppError(409, "valuation_out_of_range", "Valuation exceeds supported precision")
        ret = percent((total - capital) / capital * 100)
        bench = percent((benchmark_current / benchmark_initial - 1) * 100)
        if abs(ret - bench) >= Decimal("1000000000000"):
            raise AppError(409, "valuation_out_of_range", "Comparison exceeds supported precision")
        # Seed the peak at original capital: the simulated fee is an initial drawdown.
        peak = max(previous_peak or capital, capital, total)
        drawdown = max(
            previous_drawdown, percent((peak - total) / peak * 100), percent(fee / capital * 100)
        )
        shares = [v / total for v in values]
        positions: list[dict[str, str | int]] = [
            dict(
                instrument_id=str(h.instrument_id),
                symbol=h.symbol,
                quantity=h.quantity,
                price=str(h.price),
                value=str(v),
                initial_notional=str(h.initial_notional),
                pnl=str(v - h.initial_notional),
                contribution_pct=str(percent((v - h.initial_notional) / capital * 100)),
            )
            for h, v in zip(holdings, values, strict=True)
        ]
        return Metrics(
            holdings_value,
            total,
            total - capital,
            ret,
            bench,
            percent(ret - bench),
            peak,
            drawdown,
            percent(max(shares) * 100),
            percent(sum(((v / holdings_value) ** 2 for v in values), Decimal(0))),
            len(holdings),
            len({h.sector_id for h in holdings if h.sector_id}),
            positions,
        )
