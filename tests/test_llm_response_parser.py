from columns import TARGET_COLUMNS


def test_parse_valid_llm_json_keeps_fixed_columns_only():
    from llm_extractor import parse_llm_response

    payload = {
        "records": [
            {
                "文章时间": "2026-05-22",
                "info_id": "A-1",
                "报销比例": "70%",
                "多余字段": "必须删除",
            }
        ],
        "evidence": {"报销比例": "报销比例为70%"},
        "confidence": {"报销比例": 0.95},
        "need_manual_review": False,
        "review_reason": "",
    }

    result = parse_llm_response(payload)

    assert result.success is True
    assert list(result.records[0].keys()) == TARGET_COLUMNS
    assert result.records[0]["报销比例"] == "70%"
    assert "多余字段" not in result.records[0]
    assert result.evidence["报销比例"] == "报销比例为70%"
    assert result.confidence["报销比例"] == 0.95


def test_parse_markdown_wrapped_json_and_fill_missing_fields():
    from llm_extractor import parse_llm_response

    raw = """```json
    {
      "records": [{"info_id": "A-2", "起付标准": "200元"}],
      "evidence": {"起付标准": "起付标准200元"},
      "confidence": {"起付标准": 0.8},
      "need_manual_review": true,
      "review_reason": "字段不完整"
    }
    ```"""

    result = parse_llm_response(raw)

    assert result.success is True
    assert result.records[0]["info_id"] == "A-2"
    assert result.records[0]["起付标准"] == "200元"
    assert result.records[0]["文章时间"] == ""
    assert result.need_manual_review is True
    assert result.review_reason == "字段不完整"


def test_parse_empty_records_does_not_crash():
    from llm_extractor import parse_llm_response

    result = parse_llm_response(
        {
            "records": [],
            "evidence": {},
            "confidence": {},
            "need_manual_review": True,
            "review_reason": "无可抽取待遇数据",
        }
    )

    assert result.success is True
    assert result.records == []
    assert result.need_manual_review is True


def test_parse_invalid_json_returns_failure():
    from llm_extractor import parse_llm_response

    result = parse_llm_response("不是 JSON")

    assert result.success is False
    assert "JSON" in result.error
