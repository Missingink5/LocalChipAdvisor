"""Validated domain models for evidence-bound chip selection."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class FrozenModel(BaseModel):
    """Base class for immutable, strictly validated domain values."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CheckState(StrEnum):
    """Outcome of one deterministic hard-constraint check."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class PublicationStatus(StrEnum):
    """Whether a product record may participate in formal recommendations."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CandidateBucket(StrEnum):
    """Mutually exclusive output sections for a candidate."""

    FORMAL = "FORMAL"
    NEAR_MATCH = "NEAR_MATCH"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


class LimitKind(StrEnum):
    """How a source value may be used by deterministic rules."""

    RECOMMENDED_RANGE = "RECOMMENDED_RANGE"
    GUARANTEED_MIN = "GUARANTEED_MIN"
    GUARANTEED_MAX = "GUARANTEED_MAX"
    RATED_MAX = "RATED_MAX"
    TYPICAL = "TYPICAL"
    TYPICAL_CURVE = "TYPICAL_CURVE"
    ABSOLUTE_MAXIMUM = "ABSOLUTE_MAXIMUM"


class SurgeKnowledge(StrEnum):
    """Whether the user has explicitly characterized input surge."""

    PRESENT = "PRESENT"
    NONE_EXPECTED = "NONE_EXPECTED"
    UNKNOWN = "UNKNOWN"


class RequirementCard(FrozenModel):
    """Normalized requirements that must be confirmed before formal screening."""

    raw_request: str = Field(min_length=1)
    vin_min_v: Decimal | None = Field(default=None, gt=0)
    vin_nominal_v: Decimal | None = Field(default=None, gt=0)
    vin_max_v: Decimal | None = Field(default=None, gt=0)
    surge_knowledge: SurgeKnowledge | None = None
    surge_voltage_v: Decimal | None = Field(default=None, gt=0)
    surge_duration_ms: Decimal | None = Field(default=None, gt=0)
    vout_target_v: Decimal | None = Field(default=None, gt=0)
    vout_tolerance_percent: Decimal | None = Field(default=None, gt=0)
    iout_continuous_a: Decimal | None = Field(default=None, gt=0)
    iout_peak_a: Decimal | None = Field(default=None, gt=0)
    peak_duration_ms: Decimal | None = Field(default=None, gt=0)
    ambient_max_c: Decimal | None = None
    thermal_conditions: str | None = None
    confirmed_by_user: bool = False

    def missing_minimum_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        for field_name in (
            "vin_min_v",
            "vin_nominal_v",
            "vin_max_v",
            "surge_knowledge",
            "vout_target_v",
            "vout_tolerance_percent",
            "iout_continuous_a",
            "iout_peak_a",
            "peak_duration_ms",
            "ambient_max_c",
            "thermal_conditions",
        ):
            value = getattr(self, field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                fields.append(field_name)

        if self.surge_knowledge is SurgeKnowledge.PRESENT:
            if self.surge_voltage_v is None:
                fields.append("surge_voltage_v")
            if self.surge_duration_ms is None:
                fields.append("surge_duration_ms")
        return tuple(fields)

    @model_validator(mode="after")
    def validate_relationships_and_confirmation(self) -> RequirementCard:
        vin_values = (self.vin_min_v, self.vin_nominal_v, self.vin_max_v)
        if all(value is not None for value in vin_values):
            vin_min, vin_nominal, vin_max = vin_values
            assert vin_min is not None and vin_nominal is not None and vin_max is not None
            if not vin_min <= vin_nominal <= vin_max:
                raise ValueError("input voltage must satisfy vin_min <= vin_nominal <= vin_max")

        if (
            self.iout_continuous_a is not None
            and self.iout_peak_a is not None
            and self.iout_peak_a < self.iout_continuous_a
        ):
            raise ValueError("peak output current cannot be below continuous output current")

        if self.surge_knowledge is not SurgeKnowledge.PRESENT and (
            self.surge_voltage_v is not None or self.surge_duration_ms is not None
        ):
            raise ValueError("surge values require surge_knowledge=PRESENT")

        if self.confirmed_by_user and self.missing_minimum_fields():
            missing = ", ".join(self.missing_minimum_fields())
            raise ValueError(f"confirmed requirement card is incomplete: {missing}")
        return self


class EvidenceRef(FrozenModel):
    """A program-created pointer to source material; never authored by an LLM."""

    evidence_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    product_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1, pattern=r"^[a-z0-9_.-]+$")
    knowledge_base_version: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_title: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    page: int = Field(ge=1)
    section: str | None = None
    excerpt: str = Field(min_length=1)
    limit_kind: LimitKind
    test_conditions: str | None = None
    source_url: HttpUrl
    reviewed: bool = False


class CheckResult(FrozenModel):
    """One hard-constraint result with machine-bound evidence identifiers."""

    rule_id: str = Field(min_length=1, pattern=r"^[a-z0-9_.-]+$")
    field_name: str = Field(min_length=1, pattern=r"^[a-z0-9_.-]+$")
    state: CheckState
    requirement: str = Field(min_length=1)
    actual: str | None = None
    reason: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_evidence_for_decisive_states(self) -> CheckResult:
        if self.state in {CheckState.PASS, CheckState.FAIL} and not self.evidence_ids:
            raise ValueError("PASS and FAIL checks must bind at least one evidence_id")
        return self


class CandidateEvaluation(FrozenModel):
    """Deterministic evaluation of one product against confirmed requirements."""

    product_id: str = Field(min_length=1)
    publication_status: PublicationStatus
    checks: tuple[CheckResult, ...] = Field(min_length=1)
    bucket: CandidateBucket
