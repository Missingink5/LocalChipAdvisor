"""Explicit deterministic ranking for qualified formal candidates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from local_chip_advisor.domain import CandidateBucket
from local_chip_advisor.screening import ScreenedCandidate


class RankingCriterion(StrEnum):
    """Supported explicit ranking criteria."""

    CURRENT_HEADROOM = "CURRENT_HEADROOM"


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    """Explicit ordered criteria selected for candidate ranking."""

    criteria: tuple[RankingCriterion, ...]

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError(
                "ranking policy must contain at least one criterion"
            )

        if len(set(self.criteria)) != len(self.criteria):
            raise ValueError(
                "ranking policy cannot contain duplicate criteria"
            )


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """One explainable criterion value for one candidate."""

    criterion: RankingCriterion
    value: Decimal


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """A formal candidate plus its explicit ranking evidence."""

    candidate: ScreenedCandidate
    criteria: tuple[CriterionResult, ...]


def _current_headroom(
    *,
    candidate: ScreenedCandidate,
    required_continuous_current_a: Decimal,
) -> Decimal:
    rating = candidate.product.iout_continuous_max_a

    if rating is None:
        raise ValueError(
            f"formal candidate lacks continuous current rating: "
            f"{candidate.product_id}"
        )

    return rating - required_continuous_current_a


def rank_formal_candidates(
    *,
    candidates: tuple[ScreenedCandidate, ...],
    required_continuous_current_a: Decimal,
    policy: RankingPolicy,
) -> tuple[RankedCandidate, ...]:
    """Rank only FORMAL candidates using explicitly selected criteria."""

    if required_continuous_current_a <= 0:
        raise ValueError(
            "required_continuous_current_a must be greater than zero"
        )

    ranked: list[RankedCandidate] = []

    for candidate in candidates:
        if candidate.evaluation.bucket is not CandidateBucket.FORMAL:
            raise ValueError(
                f"only FORMAL candidates may be ranked: "
                f"{candidate.product_id}"
            )

        criterion_results: list[CriterionResult] = []

        for criterion in policy.criteria:
            if criterion is RankingCriterion.CURRENT_HEADROOM:
                value = _current_headroom(
                    candidate=candidate,
                    required_continuous_current_a=(
                        required_continuous_current_a
                    ),
                )
            else:
                raise ValueError(
                    f"unsupported ranking criterion: {criterion}"
                )

            criterion_results.append(
                CriterionResult(
                    criterion=criterion,
                    value=value,
                )
            )

        ranked.append(
            RankedCandidate(
                candidate=candidate,
                criteria=tuple(criterion_results),
            )
        )

    # Criteria are ordered by policy priority.
    # Higher values rank first for all currently supported criteria.
    return tuple(
        sorted(
            ranked,
            key=lambda item: tuple(
                result.value
                for result in item.criteria
            ),
            reverse=True,
        )
    )
