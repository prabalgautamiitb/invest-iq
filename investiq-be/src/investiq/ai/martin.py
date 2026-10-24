"""Checks shared by Martin generation and persistence."""

import re
from decimal import Decimal

from investiq.schemas.martin import MartinPlan, MartinSource

MAX_CITATIONS = 6


def numbers(value: str) -> set[Decimal]:
    return {
        Decimal(token.replace(",", ""))
        for token in re.findall(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?", value)
    }


def source_numbers(sources: list[MartinSource]) -> set[Decimal]:
    owned = [source for source in sources if source.kind in {"performance", "status"}]
    return numbers(" ".join(s.text + " " + s.title for s in owned))


def personal_metrics_supported(reply: str, sources: list[MartinSource]) -> bool:
    return numbers(reply) <= source_numbers(sources)


def complete_personal_citations(plan: MartinPlan, sources: list[MartinSource]) -> MartinPlan:
    """Attach omitted metric sources from an already-cited contest snapshot.

    Do not borrow evidence from another date/contest, change the reply, or accept
    numbers absent from the frozen evidence. Partial coverage still requires repair.
    """
    if plan.intent != "personal_assessment":
        return plan
    selected = [source for source in sources if source.id in plan.source_ids]
    anchors = {
        (source.contest_id, source.session_date)
        for source in selected
        if source.kind == "performance"
    }
    missing = numbers(plan.reply) - source_numbers(selected)
    candidates = [
        source
        for source in sources
        if source.kind == "performance"
        and source.id not in plan.source_ids
        and (source.contest_id, source.session_date) in anchors
    ]
    while missing and candidates and len(selected) < MAX_CITATIONS:
        best = max(candidates, key=lambda source: len(missing & source_numbers([source])))
        covered = missing & source_numbers([best])
        if not covered:
            break
        selected.append(best)
        candidates.remove(best)
        missing -= covered
    if missing:
        return plan
    added = [source.id for source in selected if source.id not in plan.source_ids]
    return plan.model_copy(update={"source_ids": [*plan.source_ids, *added]})
