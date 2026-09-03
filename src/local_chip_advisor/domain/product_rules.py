"""Deterministic hard-screening rules for Buck converter products."""

from __future__ import annotations

from decimal import Decimal

from .models import CheckResult, CheckState
from .product import BuckProductRecord


def _unique_evidence_ids(
    product: BuckProductRecord,
    *field_names: str,
) -> tuple[str, ...]:
    """Collect evidence IDs for fields while preserving order."""

    seen: set[str] = set()
    result: list[str] = []

    for field_name in field_names:
        for evidence_id in product.evidence_ids_for(field_name):
            if evidence_id not in seen:
                seen.add(evidence_id)
                result.append(evidence_id)

    return tuple(result)


def check_output_voltage(
    *,
    product: BuckProductRecord,
    requested_vout_v: Decimal,
    operating_vin_min_v: Decimal,
) -> CheckResult:
    """Check whether requested VOUT is valid at the minimum operating VIN.

    A Buck converter may have:
    - a fixed maximum output voltage;
    - an input-dependent maximum such as VOUT <= 0.9 * VIN;
    - or both, in which case the stricter limit applies.
    """

    if requested_vout_v <= 0:
        raise ValueError("requested_vout_v must be positive")

    if operating_vin_min_v <= 0:
        raise ValueError("operating_vin_min_v must be positive")

    lower = product.vout_min_v

    upper_candidates: list[Decimal] = []
    upper_evidence_fields: list[str] = []

    if product.vout_max_v is not None:
        upper_candidates.append(product.vout_max_v)
        upper_evidence_fields.append("vout_max_v")

    if product.vout_max_vin_ratio is not None:
        upper_candidates.append(
            product.vout_max_vin_ratio * operating_vin_min_v
        )
        upper_evidence_fields.append("vout_max_vin_ratio")

    if lower is None or not upper_candidates:
        return CheckResult(
            rule_id="vout.range",
            field_name="vout.range",
            state=CheckState.UNKNOWN,
            requirement=f"VOUT={requested_vout_v}V",
            actual=None,
            reason="product output-voltage operating range is incomplete",
        )

    upper = min(upper_candidates)

    evidence_fields = (
        "vout_min_v",
        *upper_evidence_fields,
    )

    missing_evidence_fields = tuple(
        field_name
        for field_name in evidence_fields
        if not product.evidence_ids_for(field_name)
    )

    actual = (
        f"{lower}V to {upper}V "
        f"at VIN={operating_vin_min_v}V"
    )

    if missing_evidence_fields:
        return CheckResult(
            rule_id="vout.range",
            field_name="vout.range",
            state=CheckState.UNKNOWN,
            requirement=f"VOUT={requested_vout_v}V",
            actual=actual,
            reason=(
                "decisive output-voltage evidence is missing for: "
                + ", ".join(missing_evidence_fields)
            ),
        )

    evidence_ids = _unique_evidence_ids(
        product,
        *evidence_fields,
    )

    if requested_vout_v < lower or requested_vout_v > upper:
        state = CheckState.FAIL
        reason = (
            f"requested VOUT={requested_vout_v}V is outside "
            f"the allowed range {lower}V to {upper}V "
            f"at VIN={operating_vin_min_v}V"
        )
    else:
        state = CheckState.PASS
        reason = (
            f"requested VOUT={requested_vout_v}V is inside "
            f"the allowed range {lower}V to {upper}V "
            f"at VIN={operating_vin_min_v}V"
        )

    return CheckResult(
        rule_id="vout.range",
        field_name="vout.range",
        state=state,
        requirement=f"VOUT={requested_vout_v}V",
        actual=actual,
        reason=reason,
        evidence_ids=evidence_ids,
    )



def check_input_voltage(
    *,
    product: BuckProductRecord,
    operating_vin_min_v: Decimal,
    operating_vin_max_v: Decimal,
) -> CheckResult:
    """Check the required operating VIN range against the recommended range."""

    if operating_vin_min_v <= 0 or operating_vin_max_v <= 0:
        raise ValueError("operating input voltages must be positive")

    if operating_vin_min_v > operating_vin_max_v:
        raise ValueError(
            "operating_vin_min_v must be <= operating_vin_max_v"
        )

    lower = product.vin_min_v
    upper = product.vin_max_v

    requirement = (
        f"VIN={operating_vin_min_v}V to {operating_vin_max_v}V"
    )

    if lower is None or upper is None:
        return CheckResult(
            rule_id="vin.range",
            field_name="vin.range",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=None,
            reason="product recommended input-voltage range is incomplete",
        )

    actual = f"{lower}V to {upper}V"

    missing_evidence_fields = tuple(
        field_name
        for field_name in ("vin_min_v", "vin_max_v")
        if not product.evidence_ids_for(field_name)
    )

    if missing_evidence_fields:
        return CheckResult(
            rule_id="vin.range",
            field_name="vin.range",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=actual,
            reason=(
                "decisive input-voltage evidence is missing for: "
                + ", ".join(missing_evidence_fields)
            ),
        )

    evidence_ids = _unique_evidence_ids(
        product,
        "vin_min_v",
        "vin_max_v",
    )

    if (
        operating_vin_min_v < lower
        or operating_vin_max_v > upper
    ):
        state = CheckState.FAIL
        reason = (
            f"required VIN range {operating_vin_min_v}V to "
            f"{operating_vin_max_v}V is outside the recommended "
            f"range {lower}V to {upper}V"
        )
    else:
        state = CheckState.PASS
        reason = (
            f"required VIN range {operating_vin_min_v}V to "
            f"{operating_vin_max_v}V is inside the recommended "
            f"range {lower}V to {upper}V"
        )

    return CheckResult(
        rule_id="vin.range",
        field_name="vin.range",
        state=state,
        requirement=requirement,
        actual=actual,
        reason=reason,
        evidence_ids=evidence_ids,
    )



def check_continuous_output_current(
    *,
    product: BuckProductRecord,
    requested_iout_a: Decimal,
) -> CheckResult:
    """Check required continuous load current against the rated maximum."""

    if requested_iout_a <= 0:
        raise ValueError("requested_iout_a must be positive")

    rated_max = product.iout_continuous_max_a
    requirement = f"continuous IOUT={requested_iout_a}A"

    if rated_max is None:
        return CheckResult(
            rule_id="iout.continuous",
            field_name="iout.continuous",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=None,
            reason="product continuous output-current rating is missing",
        )

    actual = f"{rated_max}A continuous rated maximum"

    evidence_ids = product.evidence_ids_for(
        "iout_continuous_max_a"
    )

    if not evidence_ids:
        return CheckResult(
            rule_id="iout.continuous",
            field_name="iout.continuous",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=actual,
            reason="decisive continuous output-current evidence is missing",
        )

    if requested_iout_a > rated_max:
        state = CheckState.FAIL
        reason = (
            f"requested continuous IOUT={requested_iout_a}A exceeds "
            f"the rated maximum of {rated_max}A"
        )
    else:
        state = CheckState.PASS
        reason = (
            f"requested continuous IOUT={requested_iout_a}A does not exceed "
            f"the rated maximum of {rated_max}A"
        )

    return CheckResult(
        rule_id="iout.continuous",
        field_name="iout.continuous",
        state=state,
        requirement=requirement,
        actual=actual,
        reason=reason,
        evidence_ids=evidence_ids,
    )
