from server.retrieval import RETRIEVAL_ALGORITHM, rank_documents, retrieval_diagnostics, retrieve_documents, tokenize


DOCUMENTS = [
    {"id": 1, "title": "账号帮助", "content": "在设置页面重置密码，并重新登录。"},
    {"id": 2, "title": "任务分配规则", "content": "任务人数总和必须等于参与者人数，最多六项任务。"},
    {"id": 3, "title": "页面导航测试", "content": "重复跳转时只触发一次导航。"},
]


def test_tokenize_supports_chinese_phrases_and_latin_words():
    tokens = tokenize("Reset 密码设置 V2")
    assert "reset" in tokens
    assert "密码" in tokens
    assert "设置" in tokens
    assert "v2" in tokens


def test_bm25_ranks_relevant_chinese_document_first():
    ranked = rank_documents(DOCUMENTS, "任务人数合计可以超过参与者吗")
    assert ranked[0].row["id"] == 2
    assert ranked[0].score > ranked[1].score
    assert retrieve_documents(DOCUMENTS, "如何重置密码", limit=1)[0]["id"] == 1


def test_no_match_falls_back_deterministically_and_diagnostics_are_safe():
    selected = retrieve_documents(DOCUMENTS, "量子天气", limit=2)
    assert [row["id"] for row in selected] == [1, 2]
    detail = retrieval_diagnostics(DOCUMENTS, "任务人数", limit=2)
    assert detail["algorithm"] == RETRIEVAL_ALGORITHM
    assert detail["ranking"][0]["document_id"] == 2
    assert "content" not in str(detail)
