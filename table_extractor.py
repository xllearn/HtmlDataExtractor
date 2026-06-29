import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd
import yaml

from cleaner import clean_text, normalize_record
from columns import TARGET_COLUMNS


@dataclass
class TableExtractionResult:
    records: List[Dict[str, str]] = field(default_factory=list)
    field_evidence: List[Dict[str, Any]] = field(default_factory=list)
    table_count: int = 0
    table_row_count: int = 0
    extraction_mode: str = ""
    need_manual_review: bool = False
    review_reason: str = ""


def load_table_mapping(path: str | Path = "config/table_mapping.yml") -> Dict[str, Any]:
    mapping_path = Path(path)
    if not mapping_path.exists():
        return {"table_column_aliases": {}, "ignored_columns": ["序号", "编号"]}
    return yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}


def normalize_header(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^Unnamed:\d+_level_\d+$", "", text)
    return text.strip("：:")


def alias_to_target(mapping: Dict[str, Any]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for target, values in (mapping.get("table_column_aliases") or {}).items():
        aliases[normalize_header(target)] = target
        for alias in values or []:
            aliases[normalize_header(alias)] = target
    for column in TARGET_COLUMNS:
        aliases.setdefault(normalize_header(column), column)
    return aliases


def map_header(header: Any, aliases: Dict[str, str]) -> str:
    normalized = normalize_header(header)
    if normalized in aliases:
        return aliases[normalized]
    for alias, target in aliases.items():
        if alias and alias in normalized:
            return target
    return normalized


def _is_repeated_header(row: Dict[str, Any], mapped_columns: Sequence[str]) -> bool:
    values = {clean_text(row.get(column)) for column in mapped_columns}
    return bool(values) and values.issubset(set(mapped_columns))


def _has_catalog_or_business_value(record: Dict[str, str]) -> bool:
    catalog_fields = ["病种名称", "类型", "标化类型", "起付标准", "补助限额", "报销比例"]
    return any(clean_text(record.get(field)) for field in catalog_fields)


def _append_evidence(
    rows: List[Dict[str, Any]],
    source_id: str,
    info_id: str,
    row_index: int,
    field_name: str,
    value: str,
    evidence: str,
    source: str,
    rule_name: str,
) -> None:
    rows.append(
        {
            "source_id": source_id,
            "info_id": info_id,
            "row_index": row_index,
            "field": field_name,
            "value": value,
            "evidence": evidence,
            "confidence": 0.9,
            "source": source,
            "rule_name": rule_name,
        }
    )


def _row_to_record(
    row: Dict[str, Any],
    mapped_columns: Sequence[str],
    base: Dict[str, str],
    columns: Sequence[str],
    source_id: str,
    row_index: int,
    source: str,
    evidence_rows: List[Dict[str, Any]],
) -> Dict[str, str] | None:
    if _is_repeated_header(row, mapped_columns):
        return None
    record = dict(base)
    raw_notes = []
    for column in mapped_columns:
        if column not in columns:
            continue
        value = clean_text(row.get(column))
        if not value:
            continue
        record[column] = value
        _append_evidence(
            evidence_rows,
            source_id,
            clean_text(base.get("info_id")),
            row_index,
            column,
            value,
            f"{column}: {value}",
            source,
            "table_column_mapping",
        )
    for raw_column, raw_value in row.items():
        if raw_column in mapped_columns:
            continue
        value = clean_text(raw_value)
        name = clean_text(raw_column)
        if value and name and not name.startswith("Unnamed") and name not in {"序号", "编号"}:
            raw_notes.append(f"{name}={value}")
    if raw_notes:
        existing = clean_text(record.get("备注"))
        record["备注"] = "；".join(part for part in [existing, "原始列：" + "，".join(raw_notes)] if part)
    record = normalize_record(record, columns)
    return record if _has_catalog_or_business_value(record) else None


def extract_html_tables(
    html: str,
    base: Dict[str, str],
    columns: Sequence[str] | None = None,
    mapping_path: str | Path = "config/table_mapping.yml",
    source_id: str = "",
) -> TableExtractionResult:
    columns = list(columns or TARGET_COLUMNS)
    result = TableExtractionResult(extraction_mode="table_html")
    if not clean_text(html):
        return result
    mapping = load_table_mapping(mapping_path)
    aliases = alias_to_target(mapping)
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return result
    result.table_count = len(tables)
    for table in tables:
        if table.empty:
            continue
        table = table.dropna(how="all").copy()
        original_columns = list(table.columns)
        mapped = [map_header(column, aliases) for column in original_columns]
        table.columns = mapped
        mapped_columns = [column for column in mapped if column in columns]
        if not mapped_columns:
            continue
        for _, row in table.iterrows():
            row_dict = {column: row.get(column, "") for column in table.columns}
            record = _row_to_record(
                row_dict,
                mapped_columns,
                base,
                columns,
                source_id,
                len(result.records),
                "html_table",
                result.field_evidence,
            )
            if record:
                result.records.append(record)
    result.table_row_count = len(result.records)
    return result


TEXT_HEADER_RE = re.compile(r"序号\s+(.+)")
TEXT_ROW_WITH_DOSAGE_RE = re.compile(
    r"^\s*(?P<seq>\d+)\s+(?P<name>.+?)\s+(?P<dosage>注射剂|口服常释剂型|缓释控释剂型|口服缓释剂型|口服液|胶囊剂|片剂|颗粒剂|散剂|丸剂|滴丸|胶囊|片)\s+(?P<class>甲类|乙类|丙类)\s*$"
)


def _split_text_line(line: str) -> List[str]:
    if "\t" in line:
        return [clean_text(part) for part in line.split("\t") if clean_text(part)]
    parts = [clean_text(part) for part in re.split(r"\s{2,}", line) if clean_text(part)]
    if len(parts) > 1:
        return parts
    return [clean_text(part) for part in line.split(" ") if clean_text(part)]


def extract_text_tables(
    text: str,
    base: Dict[str, str],
    columns: Sequence[str] | None = None,
    mapping_path: str | Path = "config/table_mapping.yml",
    source_id: str = "",
) -> TableExtractionResult:
    columns = list(columns or TARGET_COLUMNS)
    result = TableExtractionResult(extraction_mode="table_text")
    mapping = load_table_mapping(mapping_path)
    aliases = alias_to_target(mapping)
    lines = [clean_text(line) for line in re.split(r"[\r\n]+", text or "") if clean_text(line)]
    headers: List[str] = []
    mapped_headers: List[str] = []
    for line in lines:
        if any(token in line for token in ["药品名称", "项目名称", "病种名称", "疾病名称"]) and any(
            token in line for token in ["序号", "剂型", "类别", "报销比例", "支付限额", "补助限额", "起付标准"]
        ):
            headers = _split_text_line(line)
            mapped_headers = [map_header(header, aliases) for header in headers]
            result.table_count += 1
            continue
        match = TEXT_ROW_WITH_DOSAGE_RE.match(line)
        if match:
            mapped_headers = ["序号", "病种名称", "类型", "标化类型"]
            values = [match.group("seq"), match.group("name"), match.group("dosage"), match.group("class")]
        elif mapped_headers and re.match(r"^\d+\s+", line):
            values = _split_text_line(line)
            if mapped_headers and mapped_headers[0] != "序号" and values and values[0].isdigit() and len(values) == len(mapped_headers) + 1:
                values = values[1:]
            if len(values) != len(mapped_headers):
                continue
        else:
            continue
        row = {mapped_headers[index]: values[index] for index in range(min(len(values), len(mapped_headers)))}
        record = _row_to_record(
            row,
            [header for header in mapped_headers if header in columns],
            base,
            columns,
            source_id,
            len(result.records),
            "text_table",
            result.field_evidence,
        )
        if record:
            result.records.append(record)
    result.table_row_count = len(result.records)
    return result


def combine_table_results(*results: TableExtractionResult) -> TableExtractionResult:
    combined = TableExtractionResult()
    for result in results:
        combined.records.extend(result.records)
        combined.field_evidence.extend(result.field_evidence)
        combined.table_count += result.table_count
        combined.table_row_count += result.table_row_count
        if result.records and not combined.extraction_mode:
            combined.extraction_mode = result.extraction_mode
        combined.need_manual_review = combined.need_manual_review or result.need_manual_review
        combined.review_reason = "；".join(
            part for part in [combined.review_reason, result.review_reason] if clean_text(part)
        )
    return combined
