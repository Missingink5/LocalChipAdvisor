import pytest
from pydantic import ValidationError

from local_chip_advisor.models import CheckState, Constraint, Intent, Operator, ParsedQuery, Product
from local_chip_advisor.store import ChipStore


def make_store(tmp_path):
    store = ChipStore(tmp_path / "test.db")
    store.init_db()
    store.upsert_product(Product(
        product_id="wide", part_number="DEMO-WIDE-001", category="DC-DC",
        topology="Buck-Boost", vin_min_v=4, vin_max_v=36, vout_min_v=1,
        vout_max_v=24, vout_max_ratio_to_vin=0.9, iout_max_a=5,
        aec_q100=True, reviewed=True,
    ))
    store.upsert_product(Product(
        product_id="small", part_number="DEMO-SMALL-001", category="DC-DC",
        topology="Buck-Boost", vin_min_v=4, vin_max_v=24, vout_min_v=1,
        vout_max_v=12, vout_max_ratio_to_vin=0.9, iout_max_a=3,
        aec_q100=False, reviewed=True,
    ))
    store.upsert_product(Product(
        product_id="unknown", part_number="DEMO-UNKNOWN-001", category="DC-DC",
        topology="Buck-Boost", vin_min_v=4, vin_max_v=36, vout_min_v=1,
        vout_max_v=24, vout_max_ratio_to_vin=0.9, iout_max_a=5,
        aec_q100=None, reviewed=True,
    ))
    return store


def test_numeric_ranges_and_current_are_deterministic(tmp_path):
    store = make_store(tmp_path)
    parsed = ParsedQuery(raw_query="q", intent=Intent.PART_SELECTION, constraints=[
        Constraint(field="vin_v", operator=Operator.RANGE_CONTAINS, value=28),
        Constraint(field="vout_v", operator=Operator.RANGE_CONTAINS, value=24),
        Constraint(field="iout_max_a", operator=Operator.GTE, value=5),
    ])
    results = store.filter_products(parsed)
    assert {item.product.part_number for item in results} == {"DEMO-WIDE-001", "DEMO-UNKNOWN-001"}
    store.close()


def test_dynamic_vout_limit_uses_requested_input_voltage(tmp_path):
    store = make_store(tmp_path)
    parsed = ParsedQuery(raw_query="q", intent=Intent.PART_SELECTION, constraints=[
        Constraint(field="vin_v", operator=Operator.RANGE_CONTAINS, value=24),
        Constraint(field="vout_v", operator=Operator.RANGE_CONTAINS, value=24),
    ])
    assert store.filter_products(parsed) == []
    store.close()


def test_false_and_unknown_never_become_formal_pass(tmp_path):
    store = make_store(tmp_path)
    parsed = ParsedQuery(raw_query="q", intent=Intent.PART_SELECTION, constraints=[
        Constraint(field="aec_q100", operator=Operator.EQ, value=True),
    ])
    results = store.filter_products(parsed)
    by_part = {item.product.part_number: item for item in results}
    assert "DEMO-SMALL-001" not in by_part
    assert by_part["DEMO-WIDE-001"].overall == CheckState.PASS
    assert by_part["DEMO-UNKNOWN-001"].overall == CheckState.UNKNOWN
    store.close()


def test_parser_contract_rejects_legal_json_with_wrong_semantics():
    with pytest.raises(ValidationError):
        Constraint(field="iout_a", operator=Operator.RANGE_CONTAINS, value=5)
    with pytest.raises(ValidationError):
        Constraint(field="i2c", operator=Operator.EQ, value="I2C")
    with pytest.raises(ValidationError):
        ParsedQuery(raw_query="q", intent=Intent.PART_SELECTION, category="Buck-Boost")
