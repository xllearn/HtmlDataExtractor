from columns import TARGET_COLUMNS
from record_fusion import fuse_rule_and_llm_records


def _record(name: str) -> dict:
    return {"info_id": "A-1", "病种名称": name, "类型": "门诊"}


def test_llm_rule_fusion_keeps_rule_extra_rows():
    rule_records = [_record(f"药品{i}") for i in range(5)]
    llm_records = [_record("药品0")]

    fused, conflicts = fuse_rule_and_llm_records({"info_id": "A-1"}, rule_records, llm_records, TARGET_COLUMNS)

    assert len(fused) == 5
    assert conflicts == []
    assert fused[-1]["病种名称"] == "药品4"
    assert fused[-1]["need_manual_review"] is True
    assert "LLM 返回行数少于规则表格行数" in fused[-1]["review_reason"]


def test_llm_rule_fusion_keeps_llm_extra_rows():
    rule_records = [_record("药品0")]
    llm_records = [_record("药品0"), _record("药品1"), _record("药品2")]

    fused, conflicts = fuse_rule_and_llm_records({"info_id": "A-1"}, rule_records, llm_records, TARGET_COLUMNS)

    assert len(fused) == 3
    assert conflicts == []
    assert fused[-1]["病种名称"] == "药品2"
    assert fused[-1]["need_manual_review"] is True
    assert "LLM 返回行数多于规则表格行数" in fused[-1]["review_reason"]
