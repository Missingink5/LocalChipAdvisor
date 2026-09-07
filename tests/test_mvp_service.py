import pytest
from pydantic import ValidationError

from local_chip_advisor.mvp.service import Selection, render_controlled_facts, validate_selection


def test_citations_must_be_in_current_context():
    draft = Selection(relevant_ids=["other-build:1"], sufficient=True, conflict=False)
    with pytest.raises(ValueError):
        validate_selection(draft, [{"chunk_id": "this-build:1", "text": "original"}])


def test_model_cannot_supply_facts_or_page_numbers():
    with pytest.raises(ValidationError):
        Selection.model_validate({"relevant_ids": [], "sufficient": True,
                                  "conflict": False, "page": 99, "fact": "safe"})


def test_complete_source_text_is_rendered_not_model_rewrite():
    text = "Typical 170C. Not a guarantee under all operating conditions."
    record = {"chunk_id": "a", "text": text}
    result = validate_selection(Selection(relevant_ids=["a"], sufficient=True,
                                         conflict=False), [record])
    assert result == [record]
    assert result[0]["text"] == text


def test_controlled_thermal_fact_requires_all_conditions():
    complete = [{"text": "Thermal Shutdown: typically 170oC, below 160oC, ~10oC hysteresis."}]
    assert "结温" in render_controlled_facts("MP4570 太热会停吗", complete)[0]
    assert render_controlled_facts("MP4570 电压多高", complete) == []
    assert render_controlled_facts("MP4570 太热吗", [{"text": "Typical threshold 170oC."}]) == []
