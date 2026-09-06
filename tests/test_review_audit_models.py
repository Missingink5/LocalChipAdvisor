"""Contract tests for human review provenance models."""

from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from inspect import Parameter, signature

import pytest


def test_review_record_domain_api_exists() -> None:
    review = import_module("local_chip_advisor.domain.review")

    assert callable(review.ReviewRecord)


def test_review_record_identifies_reviewed_object() -> None:
    review = import_module("local_chip_advisor.domain.review")

    record = review.ReviewRecord(
        object_type="evidence",
        object_id="ev:test:1",
        review_id="review:test:1",
        object_version="kb-test-v1",
        conclusion="approved",
        basis="datasheet page 4",
        operator="reviewer-1",
        recorded_at=datetime(
            2026,
            9,
            6,
            5,
            0,
            tzinfo=UTC,
        ),
    )

    assert record.object_type == "evidence"
    assert record.object_id == "ev:test:1"


def test_review_record_requires_explicit_conclusion() -> None:
    review = import_module("local_chip_advisor.domain.review")

    record = review.ReviewRecord(
        object_type="evidence",
        object_id="ev:test:1",
        review_id="review:test:1",
        object_version="kb-test-v1",
        conclusion="approved",
        basis="datasheet page 4",
        operator="reviewer-1",
        recorded_at=datetime(
            2026,
            9,
            6,
            5,
            0,
            tzinfo=UTC,
        ),
    )

    assert record.conclusion == "approved"


def test_review_record_requires_explicit_basis() -> None:
    review = import_module("local_chip_advisor.domain.review")

    record = review.ReviewRecord(
        object_type="evidence",
        object_id="ev:test:1",
        review_id="review:test:1",
        object_version="kb-test-v1",
        conclusion="approved",
        basis="datasheet page 4",
        operator="reviewer-1",
        recorded_at=datetime(
            2026,
            9,
            6,
            5,
            0,
            tzinfo=UTC,
        ),
    )

    assert record.basis == "datasheet page 4"


def test_review_record_requires_explicit_operator() -> None:
    review = import_module("local_chip_advisor.domain.review")

    record = review.ReviewRecord(
        object_type="evidence",
        object_id="ev:test:1",
        review_id="review:test:1",
        object_version="kb-test-v1",
        conclusion="approved",
        basis="datasheet page 4",
        operator="reviewer-1",
        recorded_at=datetime(
            2026,
            9,
            6,
            5,
            0,
            tzinfo=UTC,
        ),
    )

    assert record.operator == "reviewer-1"


def test_review_record_requires_explicit_recorded_at() -> None:
    review = import_module("local_chip_advisor.domain.review")

    parameters = signature(review.ReviewRecord).parameters

    assert "recorded_at" in parameters
    assert parameters["recorded_at"].default is Parameter.empty


def test_review_record_rejects_naive_recorded_at() -> None:
    review = import_module("local_chip_advisor.domain.review")
    with pytest.raises(ValueError, match="recorded_at must be timezone-aware"):
        review.ReviewRecord(
            object_type="evidence",
            object_id="ev:test:1",
            review_id="review:test:1",
            object_version="kb-test-v1",
            conclusion="approved",
            basis="datasheet page 4",
            operator="reviewer-1",
            recorded_at=datetime(2026, 9, 6, 5, 0, tzinfo=None),  # noqa: DTZ001 -- rejection fixture
        )


def _valid_record(**changes):
    review = import_module("local_chip_advisor.domain.review")
    fields = {
        "object_type": "evidence",
        "object_id": "ev:test:1",
        "object_version": "kb-test-v1",
        "review_id": "review:test:1",
        "conclusion": "approved",
        "basis": "fixture source page 4",
        "operator": "fixture-reviewer",
        "recorded_at": datetime(2026, 9, 6, tzinfo=UTC),
    }
    fields.update(changes)
    return review.ReviewRecord(**fields)


@pytest.mark.parametrize("field", ["object_id", "object_version", "review_id", "basis", "operator"])
@pytest.mark.parametrize("value", ["", "   ", None, 123])
def test_review_identity_and_basis_must_be_explicit(field, value):
    with pytest.raises((TypeError, ValueError), match=field):
        _valid_record(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_type", "product"),
        ("object_type", ""),
        ("conclusion", "maybe"),
        ("conclusion", ""),
    ],
)
def test_review_scope_and_conclusion_are_closed(field, value):
    with pytest.raises(ValueError, match=field):
        _valid_record(**{field: value})


def test_review_time_and_history_are_explicit():
    from dataclasses import FrozenInstanceError

    now = datetime(2026, 9, 6, 13, tzinfo=timezone(timedelta(hours=8)))
    first = _valid_record(recorded_at=now)
    second = _valid_record(
        review_id="review:test:2", conclusion="revoked", supersedes=first.review_id
    )
    assert first.recorded_at.utcoffset() == timedelta(hours=8)
    assert second.supersedes == first.review_id
    assert first.conclusion == "approved"
    with pytest.raises(FrozenInstanceError):
        first.conclusion = "revoked"
    with pytest.raises(ValueError, match="supersedes"):
        _valid_record(supersedes="review:test:1")
    with pytest.raises(TypeError, match="recorded_at"):
        _valid_record(recorded_at="2026-09-06")


def test_review_versions_remain_distinct():
    old = _valid_record()
    new = _valid_record(review_id="review:test:2", object_version="kb-test-v2")
    assert (old.object_type, old.object_id, old.object_version) != (
        new.object_type,
        new.object_id,
        new.object_version,
    )


@pytest.mark.parametrize("scope", ["document", "evidence"])
@pytest.mark.parametrize("conclusion", ["approved", "rejected", "pending", "revoked"])
def test_review_supported_scopes_keep_explicit_conclusions(scope, conclusion):
    record = _valid_record(object_type=scope, conclusion=conclusion)
    assert record.object_type == scope
    assert record.conclusion == conclusion
