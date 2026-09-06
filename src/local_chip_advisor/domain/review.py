"""Human review provenance domain contracts."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """One human review decision bound to an explicit reviewed object."""

    object_type: str
    object_id: str
    conclusion: str
    basis: str
    operator: str
    recorded_at: datetime
    review_id: str
    object_version: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        for name in ("review_id", "object_id", "object_version", "basis", "operator"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.object_type not in ("document", "evidence"):
            raise ValueError("object_type must be document or evidence")
        if self.conclusion not in ("approved", "rejected", "pending", "revoked"):
            raise ValueError("conclusion must be approved, rejected, pending or revoked")
        if self.supersedes is not None:
            if not isinstance(self.supersedes, str) or not self.supersedes.strip():
                raise ValueError("supersedes must identify an earlier review")
            if self.supersedes == self.review_id:
                raise ValueError("supersedes cannot reference the same review")
        if not isinstance(self.recorded_at, datetime):
            raise TypeError("recorded_at must be a datetime")
        if self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
