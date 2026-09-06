from local_chip_advisor.domain import (
    RequirementCard,
    SurgeKnowledge,
)
from local_chip_advisor.requirements import build_requirement_review


def test_format_requirement_review_shows_missing_fields_and_questions() -> None:
    from local_chip_advisor.cli import format_requirement_review

    card = RequirementCard.model_validate(
        {
            "raw_request": "Need a buck converter.",
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
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    text = format_requirement_review(
        review=review,
        questions=(
            "\u8f93\u5165\u7aef\u6d6a\u6d8c\u60c5\u51b5\u662f\u4ec0\u4e48\uff1f",
        ),
    )

    assert "surge_knowledge" in text
    assert "\u8f93\u5165\u7aef\u6d6a\u6d8c\u60c5\u51b5\u662f\u4ec0\u4e48\uff1f" in text
    assert "ready_for_confirmation: False" in text


def test_format_recommendation_result_shows_candidate_buckets_and_issue() -> None:
    from types import SimpleNamespace

    from local_chip_advisor.cli import format_recommendation_result

    issue = SimpleNamespace(
        rule_id="thermal.ambient",
        state="UNKNOWN",
        requirement="ambient maximum=70\u00b0C; thermal conditions=natural convection",
        reason="explicit ambient-temperature evidence is missing",
    )

    candidate = SimpleNamespace(
        product_id="MPS-MP4570",
        issues=(issue,),
    )

    result = SimpleNamespace(
        formal=(),
        near_match=(),
        needs_verification=(candidate,),
    )

    text = format_recommendation_result(result)

    assert "formal: none" in text
    assert "near_match: none" in text
    assert "needs_verification:" in text
    assert "MPS-MP4570" in text
    assert "thermal.ambient" in text
    assert "UNKNOWN" in text
    assert "ambient maximum=70\u00b0C" in text
    assert "explicit ambient-temperature evidence is missing" in text


def test_run_cli_session_requires_explicit_confirmation_before_recommendation() -> None:
    from types import SimpleNamespace

    from local_chip_advisor.cli import run_cli_session

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete request.",
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
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    confirmed_card = card.model_copy(
        update={"confirmed_by_user": True},
    )

    result = SimpleNamespace(
        formal=(),
        near_match=(),
        needs_verification=(),
    )

    calls = []

    class StubAdvisor:
        def review_request(self, raw_request: str):
            calls.append(("review_request", raw_request))
            return review, ()

        def confirm(self, received_card):
            calls.append(("confirm", received_card))
            return confirmed_card

        def recommend(self, **kwargs):
            calls.append(("recommend", kwargs))
            return result

    answers = iter(
        (
            "Complete request.",
            "yes",
        )
    )
    outputs = []

    def fake_input(prompt: str) -> str:
        outputs.append(prompt)
        return next(answers)

    def fake_output(text: str) -> None:
        outputs.append(text)

    policy = object()

    returned = run_cli_session(
        advisor=StubAdvisor(),
        database_path="catalog.sqlite3",
        knowledge_base_version="kb-test",
        policy=policy,
        input_fn=fake_input,
        output_fn=fake_output,
    )

    assert returned is result
    assert calls[0] == (
        "review_request",
        "Complete request.",
    )
    assert calls[1] == (
        "confirm",
        card,
    )
    assert calls[2][0] == "recommend"
    assert calls[2][1] == {
        "database_path": "catalog.sqlite3",
        "knowledge_base_version": "kb-test",
        "requirements": confirmed_card,
        "policy": policy,
    }
    assert any(
        "ready_for_confirmation: True" in item
        for item in outputs
    )
    assert any(
        "formal: none" in item
        for item in outputs
    )


def test_run_cli_session_collects_follow_up_before_confirmation() -> None:
    from types import SimpleNamespace

    from local_chip_advisor.cli import run_cli_session

    initial_card = RequirementCard.model_validate(
        {
            "raw_request": "Incomplete request.",
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
            "confirmed_by_user": False,
        }
    )

    initial_review = build_requirement_review(
        initial_card,
    )

    complete_card = initial_card.model_copy(
        update={
            "surge_knowledge": SurgeKnowledge.NONE_EXPECTED,
        }
    )

    complete_review = build_requirement_review(
        complete_card,
    )

    confirmed_card = complete_card.model_copy(
        update={"confirmed_by_user": True},
    )

    result = SimpleNamespace(
        formal=(),
        near_match=(),
        needs_verification=(),
    )

    calls = []

    class StubAdvisor:
        def review_request(self, raw_request: str):
            calls.append(("review_request", raw_request))
            return (
                initial_review,
                (
                    "\u8f93\u5165\u7aef\u6d6a\u6d8c\u60c5\u51b5\u662f\u4ec0\u4e48\uff1f",
                ),
            )

        def review_follow_up(
            self,
            *,
            card,
            raw_follow_up: str,
        ):
            calls.append(
                (
                    "review_follow_up",
                    card,
                    raw_follow_up,
                )
            )
            return complete_review, ()

        def confirm(self, card):
            calls.append(("confirm", card))
            return confirmed_card

        def recommend(self, **kwargs):
            calls.append(("recommend", kwargs))
            return result

    answers = iter(
        (
            "Incomplete request.",
            "No additional surge is expected.",
            "yes",
        )
    )

    outputs = []

    def fake_input(prompt: str) -> str:
        outputs.append(prompt)
        return next(answers)

    def fake_output(text: str) -> None:
        outputs.append(text)

    policy = object()

    returned = run_cli_session(
        advisor=StubAdvisor(),
        database_path="catalog.sqlite3",
        knowledge_base_version="kb-test",
        policy=policy,
        input_fn=fake_input,
        output_fn=fake_output,
    )

    assert returned is result

    assert calls[0] == (
        "review_request",
        "Incomplete request.",
    )

    assert calls[1] == (
        "review_follow_up",
        initial_card,
        "No additional surge is expected.",
    )

    assert calls[2] == (
        "confirm",
        complete_card,
    )

    assert calls[3][0] == "recommend"

    assert sum(
        1
        for item in outputs
        if isinstance(item, str)
        and "ready_for_confirmation:" in item
    ) == 2


def test_run_cli_session_does_not_recommend_without_explicit_yes() -> None:
    from local_chip_advisor.cli import run_cli_session

    card = RequirementCard.model_validate(
        {
            "raw_request": "Complete request.",
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
            "confirmed_by_user": False,
        }
    )

    review = build_requirement_review(card)

    calls = []

    class StubAdvisor:
        def review_request(self, raw_request: str):
            calls.append(("review_request", raw_request))
            return review, ()

        def confirm(self, received_card):
            raise AssertionError(
                "confirm must not be called without explicit yes"
            )

        def recommend(self, **kwargs):
            raise AssertionError(
                "recommend must not be called without explicit yes"
            )

    answers = iter(
        (
            "Complete request.",
            "no",
        )
    )

    def fake_input(prompt: str) -> str:
        return next(answers)

    returned = run_cli_session(
        advisor=StubAdvisor(),
        database_path="catalog.sqlite3",
        knowledge_base_version="kb-test",
        policy=object(),
        input_fn=fake_input,
        output_fn=lambda text: None,
    )

    assert returned is None
    assert calls == [
        (
            "review_request",
            "Complete request.",
        ),
    ]


def test_main_builds_default_advisor_and_runs_cli_session(
    monkeypatch,
) -> None:
    import local_chip_advisor.cli as cli_module

    calls = {}

    class FakeParser:
        def __init__(
            self,
            *,
            model: str,
        ) -> None:
            calls["model"] = model

    class FakeAdvisor:
        def __init__(
            self,
            *,
            parser,
        ) -> None:
            calls["parser"] = parser

    class FakePolicy:
        def __init__(
            self,
            *,
            criteria,
        ) -> None:
            calls["criteria"] = criteria

    def fake_run_cli_session(**kwargs):
        calls["session"] = kwargs
        calls["session_result"] = object()
        return calls["session_result"]

    monkeypatch.setattr(
        cli_module,
        "OllamaRequirementParser",
        FakeParser,
        raising=False,
    )
    monkeypatch.setattr(
        cli_module,
        "LocalChipAdvisor",
        FakeAdvisor,
        raising=False,
    )
    monkeypatch.setattr(
        cli_module,
        "RankingPolicy",
        FakePolicy,
        raising=False,
    )
    monkeypatch.setattr(
        cli_module,
        "run_cli_session",
        fake_run_cli_session,
    )

    returned = cli_module.main(
        database_path="catalog.sqlite3",
        knowledge_base_version="kb-test",
        model="test-model",
    )

    assert calls["model"] == "test-model"
    assert isinstance(
        calls["parser"],
        FakeParser,
    )
    assert calls["session"]["database_path"] == "catalog.sqlite3"
    assert calls["session"]["knowledge_base_version"] == "kb-test"
    assert calls["session"]["advisor"].__class__ is FakeAdvisor
    assert returned is calls["session_result"]


def test_cli_entrypoint_parses_arguments_and_calls_main(
    monkeypatch,
) -> None:
    import local_chip_advisor.cli as cli_module

    captured = {}
    expected_result = object()

    def fake_main(**kwargs):
        captured.update(kwargs)
        return expected_result

    monkeypatch.setattr(
        cli_module,
        "main",
        fake_main,
    )

    returned = cli_module.cli_entrypoint(
        [
            "--database-path",
            "catalog.sqlite3",
            "--knowledge-base-version",
            "kb-test",
            "--model",
            "test-model",
        ]
    )

    assert returned is expected_result
    assert captured == {
        "database_path": "catalog.sqlite3",
        "knowledge_base_version": "kb-test",
        "model": "test-model",
    }


def test_cli_module_can_be_executed_with_python_m() -> None:
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "local_chip_advisor.cli",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "usage:" in completed.stdout
    assert "--database-path" in completed.stdout
    assert "--knowledge-base-version" in completed.stdout
    assert "--model" in completed.stdout


def test_format_recommendation_result_handles_real_formal_recommendation() -> None:
    from decimal import Decimal

    from local_chip_advisor.cli import format_recommendation_result
    from local_chip_advisor.domain import (
        CandidateBucket,
        CandidateEvaluation,
        CheckResult,
        CheckState,
        PublicationStatus,
    )
    from local_chip_advisor.domain.product import BuckProductRecord
    from local_chip_advisor.ranking import (
        CriterionResult,
        RankingCriterion,
    )
    from local_chip_advisor.recommendation import (
        FormalRecommendation,
        RecommendationResult,
    )
    from local_chip_advisor.screening import ScreenedCandidate

    product = BuckProductRecord(
        product_id="MPS-TEST-FORMAL",
        manufacturer="Monolithic Power Systems (MPS)",
        base_part_number="TEST-FORMAL",
        orderable_part_numbers=("TEST-FORMAL",),
        knowledge_base_version="kb-test",
        publication_status=PublicationStatus.PUBLISHED,
    )

    check = CheckResult(
        rule_id="vin.range",
        field_name="vin.range",
        state=CheckState.PASS,
        requirement="input voltage must cover 18V to 30V",
        actual="4.5V to 55V",
        reason="reviewed operating range covers the requirement",
        evidence_ids=("ev:test:vin",),
    )

    evaluation = CandidateEvaluation(
        product_id=product.product_id,
        publication_status=PublicationStatus.PUBLISHED,
        checks=(check,),
        bucket=CandidateBucket.FORMAL,
    )

    screened_candidate = ScreenedCandidate(
        product=product,
        evaluation=evaluation,
        evidence=(),
    )

    formal = FormalRecommendation(
        rank=1,
        candidate=screened_candidate,
        ranking_criteria=(
            CriterionResult(
                criterion=RankingCriterion.CURRENT_HEADROOM,
                value=Decimal("0.5"),
            ),
        ),
        key_evidence=(),
    )

    result = RecommendationResult(
        formal=(formal,),
        near_match=(),
        needs_verification=(),
    )

    text = format_recommendation_result(result)

    assert "formal:" in text
    assert "MPS-TEST-FORMAL" in text
    assert "vin.range" in text
    assert "PASS" in text
    assert "near_match: none" in text
    assert "needs_verification: none" in text


def test_format_recommendation_result_handles_all_three_real_buckets() -> None:
    from decimal import Decimal

    from local_chip_advisor.cli import format_recommendation_result
    from local_chip_advisor.domain import (
        CandidateBucket,
        CandidateEvaluation,
        CheckResult,
        CheckState,
        PublicationStatus,
    )
    from local_chip_advisor.domain.product import BuckProductRecord
    from local_chip_advisor.ranking import (
        CriterionResult,
        RankingCriterion,
    )
    from local_chip_advisor.recommendation import (
        CandidateIssue,
        FlaggedCandidate,
        FormalRecommendation,
        RecommendationResult,
    )
    from local_chip_advisor.screening import ScreenedCandidate

    def make_product(product_id: str) -> BuckProductRecord:
        return BuckProductRecord(
            product_id=product_id,
            manufacturer="Monolithic Power Systems (MPS)",
            base_part_number=product_id,
            orderable_part_numbers=(product_id,),
            knowledge_base_version="kb-test",
            publication_status=PublicationStatus.PUBLISHED,
        )

    formal_product = make_product("MPS-FORMAL")
    formal_check = CheckResult(
        rule_id="vin.range",
        field_name="vin.range",
        state=CheckState.PASS,
        requirement="VIN must cover the operating range",
        actual="4.5V to 55V",
        reason="reviewed range covers the requirement",
        evidence_ids=("ev:test:formal-vin",),
    )
    formal_screened = ScreenedCandidate(
        product=formal_product,
        evaluation=CandidateEvaluation(
            product_id=formal_product.product_id,
            publication_status=PublicationStatus.PUBLISHED,
            checks=(formal_check,),
            bucket=CandidateBucket.FORMAL,
        ),
        evidence=(),
    )
    formal = FormalRecommendation(
        rank=1,
        candidate=formal_screened,
        ranking_criteria=(
            CriterionResult(
                criterion=RankingCriterion.CURRENT_HEADROOM,
                value=Decimal("0.5"),
            ),
        ),
        key_evidence=(),
    )

    near_product = make_product("MPS-NEAR")
    near_check = CheckResult(
        rule_id="iout.continuous",
        field_name="iout.continuous",
        state=CheckState.FAIL,
        requirement="continuous current must be at least 3A",
        actual="2.5A",
        reason="continuous-current rating is below the requirement",
        evidence_ids=("ev:test:near-iout",),
    )
    near_screened = ScreenedCandidate(
        product=near_product,
        evaluation=CandidateEvaluation(
            product_id=near_product.product_id,
            publication_status=PublicationStatus.PUBLISHED,
            checks=(near_check,),
            bucket=CandidateBucket.NEAR_MATCH,
        ),
        evidence=(),
    )
    near = FlaggedCandidate(
        candidate=near_screened,
        issues=(
            CandidateIssue(
                rule_id=near_check.rule_id,
                state=near_check.state,
                requirement=near_check.requirement,
                actual=near_check.actual,
                reason=near_check.reason,
                evidence=(),
            ),
        ),
    )

    verification_product = make_product("MPS-VERIFY")
    verification_check = CheckResult(
        rule_id="thermal.ambient",
        field_name="thermal.ambient",
        state=CheckState.UNKNOWN,
        requirement="ambient operation must be supported at 70C",
        actual=None,
        reason="applicable thermal evidence is missing",
        evidence_ids=(),
    )
    verification_screened = ScreenedCandidate(
        product=verification_product,
        evaluation=CandidateEvaluation(
            product_id=verification_product.product_id,
            publication_status=PublicationStatus.PUBLISHED,
            checks=(verification_check,),
            bucket=CandidateBucket.NEEDS_VERIFICATION,
        ),
        evidence=(),
    )
    verification = FlaggedCandidate(
        candidate=verification_screened,
        issues=(
            CandidateIssue(
                rule_id=verification_check.rule_id,
                state=verification_check.state,
                requirement=verification_check.requirement,
                actual=verification_check.actual,
                reason=verification_check.reason,
                evidence=(),
            ),
        ),
    )

    result = RecommendationResult(
        formal=(formal,),
        near_match=(near,),
        needs_verification=(verification,),
    )

    output = format_recommendation_result(result)

    assert "formal:" in output
    assert "MPS-FORMAL" in output
    assert "vin.range" in output
    assert "PASS" in output

    assert "near_match:" in output
    assert "MPS-NEAR" in output
    assert "iout.continuous" in output
    assert "FAIL" in output

    assert "needs_verification:" in output
    assert "MPS-VERIFY" in output
    assert "thermal.ambient" in output
    assert "UNKNOWN" in output


def test_format_recommendation_result_handles_all_empty_buckets() -> None:
    from local_chip_advisor.cli import format_recommendation_result
    from local_chip_advisor.recommendation import RecommendationResult

    result = RecommendationResult(
        formal=(),
        near_match=(),
        needs_verification=(),
    )

    output = format_recommendation_result(result)

    assert output == (
        "formal: none\n"
        "near_match: none\n"
        "needs_verification: none"
    )
