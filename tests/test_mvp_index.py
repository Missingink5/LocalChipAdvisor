from local_chip_advisor.mvp.index import expand_query


def test_query_expansion_keeps_original_numbers_product_and_negation():
    query = "TPS562201 不是3A，太热会停吗？"
    expanded = expand_query(query)
    assert expanded.startswith(query)
    assert "TPS562201" in expanded and "不是3A" in expanded
    assert "thermal shutdown" in expanded


def test_query_expansion_is_auditable_and_does_not_invent_for_unrelated_query():
    assert expand_query("MP4570 的封装是什么？") == "MP4570 的封装是什么？"
