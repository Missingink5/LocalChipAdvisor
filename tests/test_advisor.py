from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.requirements import RequirementParsePayload


def test_advisor_reviews_initial_request_and_builds_questions() -> None:
    from local_chip_advisor.advisor import LocalChipAdvisor

    class StubParser:
        def parse(self, raw_request: str) -> RequirementParsePayload:
            return RequirementParsePayload.model_validate(
                {
                    "vin_min_v": 18,
                    "vin_nominal_v": 24,
                    "vin_max_v": 30,
                    "vout_target_v": 5,
                    "vout_tolerance_percent": 2,
                    "iout_continuous_a": 2.5,
                    "iout_peak_a": 3,
                    "peak_duration_ms": 10,
                    "ambient_max_c": 70,
                    "thermal_conditions": "natural convection",
                }
            )

    advisor = LocalChipAdvisor(
        parser=StubParser(),
    )

    review, questions = advisor.review_request(
        "Need a buck converter."
    )

    assert isinstance(review.card, RequirementCard)
    assert review.card.raw_request == "Need a buck converter."
    assert review.card.confirmed_by_user is False
    assert review.missing_fields == ("surge_knowledge",)
    assert review.ready_for_confirmation is False
    assert questions == (
        "输入端浪涌情况是什么？请选择：存在浪涌、预计不存在额外浪涌、或目前未知。",
    )


def test_advisor_reviews_follow_up_and_returns_remaining_questions() -> None:
    from local_chip_advisor.advisor import LocalChipAdvisor

    class StubParser:
        def parse(self, raw_request: str) -> RequirementParsePayload:
            if raw_request == "Initial request.":
                return RequirementParsePayload.model_validate(
                    {
                        "vin_min_v": 18,
                        "vin_nominal_v": 24,
                        "vin_max_v": 30,
                        "vout_target_v": 5,
                        "vout_tolerance_percent": 2,
                    }
                )

            return RequirementParsePayload.model_validate(
                {
                    "surge_knowledge": "NONE_EXPECTED",
                }
            )

    advisor = LocalChipAdvisor(
        parser=StubParser(),
    )

    review1, _ = advisor.review_request(
        "Initial request."
    )

    review2, questions = advisor.review_follow_up(
        card=review1.card,
        raw_follow_up="No additional surge is expected.",
    )

    assert review2.card.surge_knowledge is SurgeKnowledge.NONE_EXPECTED
    assert review2.card.raw_request == "Initial request."
    assert review2.card.confirmed_by_user is False
    assert review2.missing_fields == (
        "iout_continuous_a",
        "iout_peak_a",
        "peak_duration_ms",
        "ambient_max_c",
        "thermal_conditions",
    )
    assert review2.ready_for_confirmation is False
    assert questions == (
        "\u8bf7\u8f93\u5165\u6301\u7eed\u8f93\u51fa\u7535\u6d41\u3001"
        "\u5cf0\u503c\u7535\u6d41\u548c\u5cf0\u503c\u6301\u7eed\u65f6\u95f4\uff0c"
        "\u4f8b\u5982\uff1a\u6301\u7eed2.5A\uff0c\u5cf0\u503c3A\u6301\u7eed10ms\u3002",
        "\u8bf7\u8f93\u5165\u6700\u9ad8\u73af\u5883\u6e29\u5ea6"
        "\u548c\u6563\u70ed\u6761\u4ef6\uff0c\u4f8b\u5982\uff1a"
        "\u6700\u9ad870\u00b0C\uff0c\u81ea\u7136\u5bf9\u6d41\u6563\u70ed\u3002",
    )


def test_advisor_confirms_complete_requirement_card() -> None:
    from local_chip_advisor.advisor import LocalChipAdvisor

    class StubParser:
        def parse(self, raw_request: str) -> RequirementParsePayload:
            return RequirementParsePayload.model_validate(
                {
                    "vin_min_v": 18,
                    "vin_nominal_v": 24,
                    "vin_max_v": 30,
                    "surge_knowledge": "NONE_EXPECTED",
                    "vout_target_v": 5,
                    "vout_tolerance_percent": 2,
                    "iout_continuous_a": 2.5,
                    "iout_peak_a": 3,
                    "peak_duration_ms": 10,
                    "ambient_max_c": 70,
                    "thermal_conditions": "natural convection",
                }
            )

    advisor = LocalChipAdvisor(
        parser=StubParser(),
    )

    review, questions = advisor.review_request(
        "Complete request."
    )

    assert questions == ()
    assert review.ready_for_confirmation is True
    assert review.card.confirmed_by_user is False

    confirmed = advisor.confirm(
        review.card,
    )

    assert confirmed.raw_request == "Complete request."
    assert confirmed.missing_minimum_fields() == ()
    assert confirmed.confirmed_by_user is True


def test_advisor_delegates_recommendation_to_deterministic_pipeline(
    monkeypatch,
) -> None:
    import local_chip_advisor.advisor as advisor_module
    from local_chip_advisor.advisor import LocalChipAdvisor

    class StubParser:
        def parse(self, raw_request: str) -> RequirementParsePayload:
            raise AssertionError("parser should not be used during recommendation")

    confirmed_card = RequirementCard.model_validate(
        {
            "raw_request": "Confirmed request.",
            "vin_min_v": 18,
            "vin_nominal_v": 24,
            "vin_max_v": 30,
            "surge_knowledge": "NONE_EXPECTED",
            "vout_target_v": 5,
            "vout_tolerance_percent": 2,
            "iout_continuous_a": 2.5,
            "iout_peak_a": 3,
            "peak_duration_ms": 10,
            "ambient_max_c": 70,
            "thermal_conditions": "natural convection",
            "confirmed_by_user": True,
        }
    )

    expected_result = object()
    captured = {}

    def fake_recommend_from_published_catalog(**kwargs):
        captured.update(kwargs)
        return expected_result

    monkeypatch.setattr(
        advisor_module,
        "recommend_from_published_catalog",
        fake_recommend_from_published_catalog,
        raising=False,
    )

    advisor = LocalChipAdvisor(
        parser=StubParser(),
    )

    policy = object()

    result = advisor.recommend(
        database_path="catalog.sqlite3",
        knowledge_base_version="kb-test",
        requirements=confirmed_card,
        policy=policy,
    )

    assert result is expected_result
    assert captured == {
        "database_path": "catalog.sqlite3",
        "knowledge_base_version": "kb-test",
        "requirements": confirmed_card,
        "policy": policy,
    }
