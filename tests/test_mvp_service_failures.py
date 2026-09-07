from local_chip_advisor.mvp.service import AdvisorService, Selection, Support


class FakeIndex:
    def __init__(self):
        self.manifest = {"build_id": "test"}

    def search(self, *args, **kwargs):
        return [{"chunk_id": "allowed", "products": ["MP4570"], "text": "Original evidence."}]


def service_with(chat):
    service = AdvisorService.__new__(AdvisorService)
    service.index = FakeIndex()
    service._chat = chat
    return service


def test_forged_citation_cannot_be_answered():
    service = service_with(lambda *args: Selection(relevant_ids=["forged"], sufficient=True, conflict=False))
    result = service.ask("MP4570 thermal shutdown?")
    assert result["status"] == "MODEL_ERROR"
    assert result["quotes"] == []


def test_support_rejection_and_conflict():
    for conflict, expected in ((False, "INSUFFICIENT_EVIDENCE"), (True, "SOURCE_CONFLICT")):
        outputs = iter([Selection(relevant_ids=["allowed"], sufficient=True, conflict=False),
                        Support(supported=False, correct_product=True,
                                conditions_complete=False, conflict=conflict)])
        result = service_with(lambda *args, outputs=outputs: next(outputs)).ask("MP4570 thermal shutdown?")
        assert result["status"] == expected


def test_retrieval_failure_has_distinct_status():
    service = service_with(lambda *args: None)

    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    service.index.search = fail
    assert service.ask("MP4570 thermal shutdown?")["status"] == "RETRIEVAL_ERROR"
