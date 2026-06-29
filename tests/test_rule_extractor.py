def test_rule_extractor_still_extracts_key_value_fields_without_llm():
    from columns import TARGET_COLUMNS
    from extractor import extract_record

    record = {
        "source_id": "A-1",
        "info_id": "A-1",
        "title": "医保政策",
        "text": "医保 类型：门诊 报销比例：70% 起付标准：200元",
        "article_time": "2026-05-22",
        "region": "西安市",
        "direct_fields": {},
        "raw": {},
    }

    records, log = extract_record(record, TARGET_COLUMNS, keyword="医保", use_llm=False)

    assert log["status"] == "success"
    assert log["llm_used"] is False
    assert len(records) == 1
    assert records[0]["info_id"] == "A-1"
    assert records[0]["报销比例"] == "70%"
    assert records[0]["起付标准"] == "200元"
