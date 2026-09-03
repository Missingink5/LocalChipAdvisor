"""Structured product master data for Buck converter selection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field, model_validator

from .models import FrozenModel, PublicationStatus


class BuckProductRecord(FrozenModel):
    """Reviewed or draft structured master data for one Buck converter.

    Product values are kept separate from source evidence. Fields point to
    program-created EvidenceRef objects through evidence_ids_by_field.
    """

    # Identity and versioning
    product_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    manufacturer: str = Field(min_length=1)
    base_part_number: str = Field(min_length=1)
    orderable_part_numbers: tuple[str, ...] = Field(min_length=1)
    knowledge_base_version: str = Field(min_length=1)
    publication_status: PublicationStatus

    # Lifecycle
    lifecycle_status: str | None = None
    lifecycle_checked_date: date | None = None

    # Recommended operating range
    vin_min_v: Decimal | None = Field(default=None, gt=0)
    vin_max_v: Decimal | None = Field(default=None, gt=0)
    vout_min_v: Decimal | None = Field(default=None, gt=0)
    vout_max_v: Decimal | None = Field(default=None, gt=0)
    iout_continuous_max_a: Decimal | None = Field(default=None, gt=0)
    iout_peak_max_a: Decimal | None = Field(default=None, gt=0)

    # Absolute maximum ratings.
    # These are stored for warning/risk analysis, not normal hard qualification.
    vin_absolute_max_v: Decimal | None = Field(default=None, gt=0)

    # Performance
    switching_frequency_min_khz: Decimal | None = Field(default=None, gt=0)
    switching_frequency_max_khz: Decimal | None = Field(default=None, gt=0)
    quiescent_current_ua: Decimal | None = Field(default=None, ge=0)
    shutdown_current_ua: Decimal | None = Field(default=None, ge=0)
    feedback_reference_v: Decimal | None = Field(default=None, gt=0)

    # Thermal / package
    junction_temp_min_c: Decimal | None = None
    junction_temp_max_c: Decimal | None = None
    package: str | None = None
    package_length_mm: Decimal | None = Field(default=None, gt=0)
    package_width_mm: Decimal | None = Field(default=None, gt=0)

    # Feature flags remain optional while a draft is incomplete.
    synchronous_rectification: bool | None = None
    power_good: bool | None = None
    enable: bool | None = None
    soft_start: bool | None = None

    # Protection flags
    over_current_protection: bool | None = None
    over_voltage_protection: bool | None = None
    under_voltage_lockout: bool | None = None
    over_temperature_protection: bool | None = None
    short_circuit_protection: bool | None = None

    # Each item is:
    # ("vin_max_v", ("ev:mp4570:vin-range", ...))
    evidence_ids_by_field: tuple[
        tuple[str, tuple[str, ...]],
        ...
    ] = ()

    @model_validator(mode="after")
    def validate_ranges_and_evidence(self) -> BuckProductRecord:
        if (
            self.vin_min_v is not None
            and self.vin_max_v is not None
            and self.vin_min_v > self.vin_max_v
        ):
            raise ValueError("vin_min_v must be <= vin_max_v")

        if (
            self.vout_min_v is not None
            and self.vout_max_v is not None
            and self.vout_min_v > self.vout_max_v
        ):
            raise ValueError("vout_min_v must be <= vout_max_v")

        if (
            self.vin_absolute_max_v is not None
            and self.vin_max_v is not None
            and self.vin_absolute_max_v < self.vin_max_v
        ):
            raise ValueError("vin_absolute_max_v cannot be below vin_max_v")

        if (
            self.junction_temp_min_c is not None
            and self.junction_temp_max_c is not None
            and self.junction_temp_min_c > self.junction_temp_max_c
        ):
            raise ValueError(
                "junction_temp_min_c must be <= junction_temp_max_c"
            )

        if (
            self.switching_frequency_min_khz is not None
            and self.switching_frequency_max_khz is not None
            and self.switching_frequency_min_khz
            > self.switching_frequency_max_khz
        ):
            raise ValueError(
                "switching_frequency_min_khz must be <= "
                "switching_frequency_max_khz"
            )

        seen_fields: set[str] = set()

        for field_name, evidence_ids in self.evidence_ids_by_field:
            if field_name in seen_fields:
                raise ValueError(
                    f"duplicate evidence binding for field: {field_name}"
                )

            seen_fields.add(field_name)

            if field_name not in type(self).model_fields:
                raise ValueError(
                    f"evidence binding references unknown field: {field_name}"
                )

            if not evidence_ids:
                raise ValueError(
                    f"evidence binding must contain at least one evidence_id: "
                    f"{field_name}"
                )

        return self

    def evidence_ids_for(self, field_name: str) -> tuple[str, ...]:
        """Return evidence IDs bound to one structured product field."""

        for bound_field, evidence_ids in self.evidence_ids_by_field:
            if bound_field == field_name:
                return evidence_ids

        return ()
