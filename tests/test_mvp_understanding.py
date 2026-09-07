from local_chip_advisor.mvp.understanding import understand


def params(query):
    result = understand(query)
    for parameter in result["parameters"]:
        assert query[parameter["start"]:parameter["end"]] == parameter["source_text"]
    return {p["field"]: p["value"] for p in result["parameters"]}


def test_explicit_values_and_source_offsets():
    query = "推荐MP4570，24V转5V、持续3A"
    assert params(query) == {"vin": 24, "vout": 5, "iout_continuous": 3}
    assert understand(query)["products"] == ["MP4570"]
    assert understand(query)["selection"]


def test_correction_with_role_keeps_continuous():
    """A correction whose surrounding context already names the role is allowed."""
    assert params("持续3A，不是3A，是300mA") == {"iout_continuous": .3}


def test_correction_without_role_does_not_invent_continuous():
    """Bare '不是3A是300mA' has no role; the parser must refuse to write
    iout_continuous and must emit an ambiguity instead."""
    result = understand("不是3A是300mA")
    assert "iout_continuous" not in params("不是3A是300mA")
    assert any("电流" in a for a in result["ambiguities"])


def test_peak_correction_records_peak_not_continuous():
    assert params("峰值不是3A，是300mA") == {"iout_peak": .3}


def test_repeated_continuous_current_correction_uses_new_source():
    query = "推荐24V转5V，持续3A；不是3A，是300mA"
    result = understand(query)
    current = next(p for p in result["parameters"] if p["field"] == "iout_continuous")
    assert current["value"] == .3
    assert current["source_text"] == "300mA"


def test_unknown_and_negation_do_not_invent_conditions():
    assert params("未知浪涌，不要强制风冷") == {
        "surge": "UNKNOWN", "cooling_method": "NOT_FORCED_AIR",
    }


def test_ambiguous_voltage_is_not_chosen():
    result = understand("推荐24V或48V转5V的芯片")
    assert result["ambiguities"]
    assert not result["parameters"]


def test_english_and_mixed_input():
    assert params("Recommend TPS54331 24V to 5V continuous 300mA") == {
        "vin": 24, "vout": 5, "iout_continuous": .3,
    }
    assert params("输入24V output 5V") == {"vin": 24, "vout": 5}


def test_bare_numbers_and_models_are_not_requirements():
    assert params("LT8610 3A current limit?") == {}
    assert understand("它会过热停机吗？")["ambiguities"]
    assert understand("MP45700")["products"] == []


def test_negated_requirements_are_not_positive_values():
    assert params("不是24V转5V") == {}
    assert params("不是输入24V") == {}
    assert params("不要持续3A") == {}
    assert params("持续电流未知，峰值3A") == {}
    assert params("不是峰值3A，是300mA") == {}
    assert params("不知道有没有浪涌") == {"surge": "UNKNOWN"}
