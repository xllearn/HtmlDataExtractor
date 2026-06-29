import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import yaml

from columns import DATE_COLUMNS, DEFAULT_ZERO_COLUMNS, TARGET_COLUMNS


@dataclass(frozen=True)
class FieldMapping:
    output_columns: List[str]
    default_missing_value: str
    field_missing_values: Dict[str, str]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"(20\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", text)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m}-{d}"
    return text


def load_field_mapping(path: str | Path = "config/field_mapping.yml") -> FieldMapping:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    output_columns = list(data.get("output_columns") or TARGET_COLUMNS)
    if output_columns != TARGET_COLUMNS:
        raise ValueError("field_mapping.yml output_columns must exactly match the fixed 26 columns")
    return FieldMapping(
        output_columns=output_columns,
        default_missing_value=str(data.get("default_missing_value", "")),
        field_missing_values={str(k): str(v) for k, v in (data.get("field_missing_values") or {}).items()},
    )


def missing_value_for(column: str, mapping: FieldMapping) -> str:
    return mapping.field_missing_values.get(column, mapping.default_missing_value)


def normalize_record(record: Dict[str, Any], columns: Sequence[str] | None = None) -> Dict[str, str]:
    columns = list(columns or TARGET_COLUMNS)
    normalized: Dict[str, str] = {}
    for column in columns:
        value = record.get(column, "")
        normalized[column] = normalize_date(value) if column in DATE_COLUMNS else clean_text(value)
    for column in DEFAULT_ZERO_COLUMNS:
        if column in normalized and not normalized[column]:
            normalized[column] = "0"
    return normalized


def fill_missing_by_field(record: Dict[str, Any], mapping: FieldMapping) -> Dict[str, str]:
    normalized = normalize_record(record, mapping.output_columns)
    for column in mapping.output_columns:
        if not clean_text(normalized.get(column)):
            normalized[column] = missing_value_for(column, mapping)
    return normalized


DEDUP_COLUMNS = [
    "info_id",
    "地区名称",
    "病种名称",
    "类型",
    "标化类型",
    "保险类型",
    "人员类型",
    "病种类型",
    "就诊地域",
    "医院类型",
    "就诊情况",
    "区间",
    "起付标准",
    "补助限额",
    "报销比例",
]


def record_key(record: Dict[str, Any]) -> str:
    raw = "|".join(clean_text(record.get(column)) for column in DEDUP_COLUMNS)
    if not raw.strip("|"):
        raw = "|".join(clean_text(record.get(column)) for column in TARGET_COLUMNS)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def deduplicate_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for record in records:
        seen.setdefault(record_key(record), record)
    return list(seen.values())


def sort_by_article_time(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(record: Dict[str, Any]) -> tuple[int, str]:
        value = normalize_date(record.get("文章时间"))
        return (1, "") if not re.match(r"20\d{2}-\d{2}-\d{2}$", value) else (0, value)

    return sorted(records, key=sort_key)


def clean_records(records: Iterable[Dict[str, Any]], mapping: FieldMapping) -> List[Dict[str, str]]:
    filled = [fill_missing_by_field(record, mapping) for record in records]
    return [fill_missing_by_field(record, mapping) for record in sort_by_article_time(deduplicate_records(filled))]
