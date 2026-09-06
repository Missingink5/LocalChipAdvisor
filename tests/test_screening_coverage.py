"""Guard: no collected requirement field may silently escape screening."""

from local_chip_advisor.domain import RequirementCard
from local_chip_advisor.domain.decision import DEFAULT_REQUIRED_RULE_IDS
from local_chip_advisor.screening import REQUIREMENT_FIELD_COVERAGE


def test_every_requirement_card_field_is_declared_in_coverage() -> None:
    """Every user condition on RequirementCard is consumed or declared context.

    The coverage map is the single inventory of what screening does with each
    collected requirement field. Adding a requirement field without declaring
    it here (as a rule input or as an intentional context/process-only field)
    fails this guard instead of being silently ignored by the rules.
    """

    assert set(REQUIREMENT_FIELD_COVERAGE) == set(RequirementCard.model_fields)


def test_coverage_rule_inputs_name_exactly_the_required_rule_set() -> None:
    """Declared rule inputs and the formal gate must name the same rules.

    The equality is deliberate in both directions: a declared input that names
    a rule outside DEFAULT_REQUIRED_RULE_IDS would never gate a decision, and
    a required rule with no requirement-field input would be unanswerable.
    """

    covered_rule_ids = {
        rule_id
        for rule_ids in REQUIREMENT_FIELD_COVERAGE.values()
        for rule_id in rule_ids
    }

    assert covered_rule_ids == set(DEFAULT_REQUIRED_RULE_IDS)
