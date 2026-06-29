from typing import Any, Dict, List, Sequence, Tuple

from cleaner import clean_text, normalize_record
from columns import BASE_COLUMNS, TARGET_COLUMNS


def _review(record: Dict[str, Any], reason: str) -> None:
    record["need_manual_review"] = True
    existing = clean_text(record.get("review_reason"))
    record["review_reason"] = "；".join(part for part in [existing, reason] if part)


def _conflict_row(
    base: Dict[str, str],
    row_index: int,
    field: str,
    rule_value: str,
    llm_value: str,
    final_value: str,
    reason: str,
) -> Dict[str, Any]:
    return {
        "source_id": clean_text(base.get("source_id")),
        "info_id": clean_text(base.get("info_id")),
        "row_index": row_index,
        "field": field,
        "rule_value": rule_value,
        "llm_value": llm_value,
        "final_value": final_value,
        "reason": reason,
    }


def merge_one(
    base: Dict[str, str],
    rule: Dict[str, Any],
    llm: Dict[str, Any],
    columns: Sequence[str],
    row_index: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    merged: Dict[str, Any] = dict(rule)
    conflicts: List[Dict[str, Any]] = []
    for column in columns:
        base_value = clean_text(base.get(column))
        rule_value = clean_text(rule.get(column))
        llm_value = clean_text(llm.get(column))
        if column in BASE_COLUMNS and base_value:
            final_value = base_value
        elif rule_value and llm_value and rule_value != llm_value:
            final_value = rule_value
            _review(merged, f"{column} 规则值与 LLM 值冲突")
            conflicts.append(_conflict_row(base, row_index, column, rule_value, llm_value, final_value, "规则表格值优先"))
        else:
            final_value = llm_value or rule_value or base_value
        merged[column] = final_value
    return normalize_record(merged, columns) | {
        key: value for key, value in merged.items() if key not in columns
    }, conflicts


def fuse_rule_and_llm_records(
    base: Dict[str, str],
    rule_records: Sequence[Dict[str, Any]],
    llm_records: Sequence[Dict[str, Any]],
    columns: Sequence[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    columns = list(columns or TARGET_COLUMNS)
    rule_records = list(rule_records or [])
    llm_records = list(llm_records or [])
    conflicts: List[Dict[str, Any]] = []
    if not llm_records:
        return list(rule_records), conflicts
    if not rule_records:
        result = []
        for record in llm_records:
            item = normalize_record({**base, **record}, columns)
            _review(item, "仅由 LLM 提取，缺少规则校验")
            result.append(item)
        return result, conflicts

    result: List[Dict[str, Any]] = []
    shared = min(len(rule_records), len(llm_records))
    for index in range(shared):
        merged, row_conflicts = merge_one(base, rule_records[index], llm_records[index], columns, index)
        result.append(merged)
        conflicts.extend(row_conflicts)

    if len(rule_records) > len(llm_records):
        reason = "LLM 返回行数少于规则表格行数，已保留规则多行结果"
        for record in rule_records[shared:]:
            item = dict(record)
            _review(item, reason)
            result.append(item)
    elif len(llm_records) > len(rule_records):
        reason = "LLM 返回行数多于规则表格行数，需人工复核"
        for record in llm_records[shared:]:
            item = normalize_record({**base, **record}, columns)
            _review(item, reason)
            result.append(item)
    return result, conflicts
