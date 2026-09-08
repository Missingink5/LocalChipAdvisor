"""Small, explicit data contracts for the Hybrid Search MVP."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

BOOLEAN_CONSTRAINT_FIELDS = {
    "aec_q100", "automotive", "i2c", "spi", "ocp", "ovp", "uvlo", "otp",
    "short_circuit_protection",
}
ALLOWED_CONSTRAINT_FIELDS = {
    "vin_v", "vout_v", "iout_max_a", "package_type", *BOOLEAN_CONSTRAINT_FIELDS,
}


class Intent(str, Enum):
    PART_SELECTION = "PART_SELECTION"
    PART_QA = "PART_QA"
    PART_COMPARE = "PART_COMPARE"


class Operator(str, Enum):
    EQ = "EQ"
    GTE = "GTE"
    LTE = "LTE"
    RANGE_CONTAINS = "RANGE_CONTAINS"


class CheckState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class Constraint(BaseModel):
    field: str
    operator: Operator
    value: Any
    unit: str | None = None
    hard: bool = True

    @model_validator(mode="after")
    def validate_semantics(self) -> Constraint:
        if self.field not in ALLOWED_CONSTRAINT_FIELDS:
            raise ValueError(f"unsupported constraint field: {self.field}")
        if self.field in {"vin_v", "vout_v"} and self.operator != Operator.RANGE_CONTAINS:
            raise ValueError(f"{self.field} requires RANGE_CONTAINS")
        if self.field == "iout_max_a" and self.operator != Operator.GTE:
            raise ValueError("iout_max_a requires GTE")
        if self.field in BOOLEAN_CONSTRAINT_FIELDS and (
            self.operator != Operator.EQ or not isinstance(self.value, bool)
        ):
            raise ValueError(f"{self.field} requires EQ with a boolean value")
        return self


class ParsedQuery(BaseModel):
    raw_query: str
    intent: Intent
    part_numbers: list[str] = Field(default_factory=list)
    category: str | None = None
    topology: str | None = None
    constraints: list[Constraint] = Field(default_factory=list)
    semantic_query: str | None = None

    @model_validator(mode="after")
    def validate_selection_taxonomy(self) -> ParsedQuery:
        if self.category and self.category.casefold() != "dc-dc":
            raise ValueError("MVP category must be DC-DC or null")
        if self.topology:
            topology = self.topology.casefold().replace("_", "-").replace(" ", "-")
            canonical = {"buck": "Buck", "boost": "Boost", "buck-boost": "Buck-Boost",
                         "buckboost": "Buck-Boost"}.get(topology)
            if not canonical:
                raise ValueError("unsupported topology")
            self.topology = canonical
        return self


class Product(BaseModel):
    product_id: str
    part_number: str
    family: str | None = None
    category: str
    topology: str
    vin_min_v: float | None = None
    vin_max_v: float | None = None
    vout_min_v: float | None = None
    vout_max_v: float | None = None
    vout_max_ratio_to_vin: float | None = None
    iout_max_a: float | None = None
    aec_q100: bool | None = None
    automotive: bool | None = None
    i2c: bool | None = None
    spi: bool | None = None
    ocp: bool | None = None
    ovp: bool | None = None
    uvlo: bool | None = None
    otp: bool | None = None
    short_circuit_protection: bool | None = None
    package_type: str | None = None
    reviewed: bool = False
    datasheet_id: str | None = None


class Evidence(BaseModel):
    evidence_id: str
    product_id: str
    document_id: str
    page: int
    section: str | None = None
    field_name: str | None = None
    text: str
    reviewed: bool = False


class SearchHit(BaseModel):
    evidence: Evidence
    bm25_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float = 0.0


class CandidateResult(BaseModel):
    product: Product
    checks: dict[str, CheckState] = Field(default_factory=dict)
    overall: CheckState


class AnswerResult(BaseModel):
    intent: Intent
    parsed_query: ParsedQuery
    candidates: list[CandidateResult] = Field(default_factory=list)
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
