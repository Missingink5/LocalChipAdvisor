"""Deterministic hard-screening rules for Buck converter products."""

from __future__ import annotations

from decimal import Decimal

from .models import CheckResult, CheckState, SurgeKnowledge
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

def check_input_surge(
    *,
    product: BuckProductRecord,
    surge_knowledge: SurgeKnowledge,
    surge_voltage_v: Decimal | None,
    surge_duration_ms: Decimal | None,
) -> CheckResult:
    """Check input-surge knowledge without treating Absolute Maximum as transient capability."""

    if surge_knowledge is SurgeKnowledge.NONE_EXPECTED:
        if surge_voltage_v is not None or surge_duration_ms is not None:
            raise ValueError(
                "surge values must be omitted when no surge is expected"
            )

        evidence_ids = product.evidence_ids_for("vin_max_v")

        if not evidence_ids:
            return CheckResult(
                rule_id="surge.input",
                field_name="surge.input",
                state=CheckState.UNKNOWN,
                requirement="no input surge expected",
                actual=None,
                reason="decisive normal input-voltage evidence is missing",
            )

        return CheckResult(
            rule_id="surge.input",
            field_name="vin.range",
            state=CheckState.PASS,
            requirement="no input surge expected",
            actual="user confirmed no input surge is expected",
            reason=(
                "no separate transient-surge qualification is required "
                "because the user explicitly confirmed no surge is expected"
            ),
            evidence_ids=evidence_ids,
        )

    if surge_knowledge is SurgeKnowledge.PRESENT:
        if surge_voltage_v is None or surge_duration_ms is None:
            raise ValueError(
                "present surge requires surge_voltage_v and surge_duration_ms"
            )

        if surge_voltage_v <= 0 or surge_duration_ms <= 0:
            raise ValueError(
                "surge voltage and duration must be positive"
            )

        absolute_text = (
            f"; Absolute Maximum VIN={product.vin_absolute_max_v}V "
            "is not treated as a transient operating rating"
            if product.vin_absolute_max_v is not None
            else ""
        )

        return CheckResult(
            rule_id="surge.input",
            field_name="surge.input",
            state=CheckState.UNKNOWN,
            requirement=(
                f"input surge={surge_voltage_v}V "
                f"for {surge_duration_ms}ms"
            ),
            actual=None,
            reason=(
                "product transient input-surge capability is not "
                "structurally qualified"
                + absolute_text
            ),
        )

    return CheckResult(
        rule_id="surge.input",
        field_name="surge.input",
        state=CheckState.UNKNOWN,
        requirement="input surge characteristics unknown",
        actual=None,
        reason="user has not characterized the input surge condition",
    )

def check_peak_output_current(
    *,
    product: BuckProductRecord,
    requested_iout_peak_a: Decimal,
    requested_peak_duration_ms: Decimal,
) -> CheckResult:
    """Check peak load against an explicit current-and-duration product rating."""

    if requested_iout_peak_a <= 0:
        raise ValueError("requested_iout_peak_a must be positive")

    if requested_peak_duration_ms <= 0:
        raise ValueError("requested_peak_duration_ms must be positive")

    peak_max = product.iout_peak_max_a
    duration_max = product.iout_peak_duration_max_ms

    requirement = (
        f"peak IOUT={requested_iout_peak_a}A "
        f"for {requested_peak_duration_ms}ms"
    )

    continuous_max = product.iout_continuous_max_a

    if (
        continuous_max is not None
        and requested_iout_peak_a <= continuous_max
    ):
        evidence_ids = product.evidence_ids_for(
            "iout_continuous_max_a"
        )

        if not evidence_ids:
            return CheckResult(
                rule_id="iout.peak",
                field_name="iout.continuous",
                state=CheckState.UNKNOWN,
                requirement=requirement,
                actual=(
                    f"{continuous_max}A continuous rated maximum"
                ),
                reason=(
                    "continuous rating would cover the requested peak, "
                    "but decisive continuous-current evidence is missing"
                ),
            )

        return CheckResult(
            rule_id="iout.peak",
            field_name="iout.continuous",
            state=CheckState.PASS,
            requirement=requirement,
            actual=f"{continuous_max}A continuous rated maximum",
            reason=(
                f"the product is rated to provide {continuous_max}A "
                "continuously, which is stronger than the requested "
                f"{requested_iout_peak_a}A finite-duration peak"
            ),
            evidence_ids=evidence_ids,
        )

    if peak_max is None or duration_max is None:
        return CheckResult(
            rule_id="iout.peak",
            field_name="iout.peak",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=None,
            reason=(
                "product peak output-current capability is incomplete; "
                "both peak current and allowed duration are required"
            ),
        )

    actual = (
        f"{peak_max}A peak rated maximum "
        f"for up to {duration_max}ms"
    )

    missing_evidence_fields = tuple(
        field_name
        for field_name in (
            "iout_peak_max_a",
            "iout_peak_duration_max_ms",
        )
        if not product.evidence_ids_for(field_name)
    )

    if missing_evidence_fields:
        return CheckResult(
            rule_id="iout.peak",
            field_name="iout.peak",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=actual,
            reason=(
                "decisive peak output-current evidence is missing for: "
                + ", ".join(missing_evidence_fields)
            ),
        )

    evidence_ids = _unique_evidence_ids(
        product,
        "iout_peak_max_a",
        "iout_peak_duration_max_ms",
    )

    if (
        requested_iout_peak_a > peak_max
        or requested_peak_duration_ms > duration_max
    ):
        state = CheckState.FAIL
        reason = (
            f"requested peak {requested_iout_peak_a}A for "
            f"{requested_peak_duration_ms}ms exceeds the qualified "
            f"limit of {peak_max}A for up to {duration_max}ms"
        )
    else:
        state = CheckState.PASS
        reason = (
            f"requested peak {requested_iout_peak_a}A for "
            f"{requested_peak_duration_ms}ms is within the qualified "
            f"limit of {peak_max}A for up to {duration_max}ms"
        )

    return CheckResult(
        rule_id="iout.peak",
        field_name="iout.peak",
        state=state,
        requirement=requirement,
        actual=actual,
        reason=reason,
        evidence_ids=evidence_ids,
    )

def check_ambient_thermal(
    *,
    product: BuckProductRecord,
    ambient_max_c: Decimal,
    thermal_conditions: str,
) -> CheckResult:
    """Check ambient temperature only against an explicit ambient rating."""

    if not thermal_conditions.strip():
        raise ValueError("thermal_conditions must not be blank")

    requirement = (
        f"ambient maximum={ambient_max_c}°C; "
        f"thermal conditions={thermal_conditions.strip()}"
    )

    ambient_rating = product.ambient_temp_max_c

    # Junction-temperature limits, theta_JA/theta_JC, and thermal shutdown
    # do not by themselves establish an allowable ambient temperature.
    if ambient_rating is None:
        return CheckResult(
            rule_id="thermal.ambient",
            field_name="thermal.ambient",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=None,
            reason=(
                "no explicit operating ambient-temperature rating is "
                "available; junction-temperature limits alone cannot "
                "prove ambient thermal qualification"
            ),
        )

    evidence_ids = product.evidence_ids_for("ambient_temp_max_c")

    if not evidence_ids:
        return CheckResult(
            rule_id="thermal.ambient",
            field_name="thermal.ambient",
            state=CheckState.UNKNOWN,
            requirement=requirement,
            actual=f"ambient maximum rating={ambient_rating}°C",
            reason="decisive ambient-temperature evidence is missing",
        )

    actual = f"ambient maximum rating={ambient_rating}°C"

    if ambient_max_c > ambient_rating:
        state = CheckState.FAIL
        reason = (
            f"requested ambient maximum {ambient_max_c}°C exceeds "
            f"the explicit operating ambient rating of {ambient_rating}°C"
        )
    else:
        state = CheckState.PASS
        reason = (
            f"requested ambient maximum {ambient_max_c}°C is within "
            f"the explicit operating ambient rating of {ambient_rating}°C"
        )

    return CheckResult(
        rule_id="thermal.ambient",
        field_name="ambient_temp_max_c",
        state=state,
        requirement=requirement,
        actual=actual,
        reason=reason,
        evidence_ids=evidence_ids,
    )
