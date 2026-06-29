import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from sqlalchemy import MetaData, bindparam, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from columns import TARGET_COLUMNS
from extractor import html_to_text
from cleaner import clean_text


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    source: Dict[str, str]
    query: Dict[str, Any]
    direct_field_columns: Dict[str, str]


FIELD_MAP = {
    "source_id": "id_column",
    "info_id": "info_id_column",
    "title": "title_column",
    "html": "html_column",
    "text": "text_column",
    "article_time": "article_time_column",
    "audit_time": "audit_time_column",
    "region": "region_column",
    "related_info": "related_info_column",
}


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    return value


def load_db_config(path: str | Path = "config/db_config.yml") -> DatabaseConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = expand_env(yaml.safe_load(handle) or {})
    url = (data.get("database") or {}).get("url", "")
    source = data.get("source") or {}
    query = data.get("query") or {}
    direct = data.get("direct_field_columns") or {}
    if not url:
        raise ValueError("database.url is required")
    if not source.get("table"):
        raise ValueError("source.table is required")
    direct_fields = {str(key): str(value or "") for key, value in direct.items() if key in TARGET_COLUMNS}
    return DatabaseConfig(
        url=url,
        source={str(k): str(v or "") for k, v in source.items()},
        query=query,
        direct_field_columns=direct_fields,
    )


def _table(config: DatabaseConfig):
    engine = create_engine(config.url)
    table_name = config.source["table"]
    metadata = MetaData()
    try:
        metadata.reflect(bind=engine, only=[table_name])
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database metadata query failed for table {table_name}: {exc}") from exc
    table = metadata.tables.get(table_name)
    if table is None:
        raise RuntimeError(f"Configured table does not exist: {table_name}")
    return engine, table


def identity_column_name(config: DatabaseConfig) -> str:
    id_column = config.source.get("id_column", "")
    info_id_column = config.source.get("info_id_column", "")
    if id_column:
        return id_column
    if info_id_column:
        return info_id_column
    raise RuntimeError("source.id_column or source.info_id_column is required for stable source_id")


def _selected_columns(config: DatabaseConfig, table) -> Tuple[List[Any], Dict[str, str]]:
    selected = []
    labels: Dict[str, str] = {}
    for standard_key, config_key in FIELD_MAP.items():
        column_name = config.source.get(config_key, "")
        if standard_key == "source_id" and not column_name:
            column_name = identity_column_name(config)
        if column_name and column_name in table.c:
            selected.append(table.c[column_name].label(standard_key))
            labels[standard_key] = column_name

    for index, (target_column, db_column) in enumerate(config.direct_field_columns.items()):
        if db_column and db_column in table.c:
            label = f"direct__{index}"
            selected.append(table.c[db_column].label(label))
            labels[label] = target_column

    if not selected:
        raise RuntimeError("No configured source columns exist in the database table")
    return selected, labels


def _base_statement(config: DatabaseConfig, table, selected: List[Any]):
    statement = select(*selected)
    where_clause = str(config.query.get("where") or "").strip()
    if where_clause:
        statement = statement.where(text(where_clause))
    order_by = str(config.query.get("order_by") or "").strip()
    if order_by:
        statement = statement.order_by(text(order_by))
    return statement


def _to_standard(row: Dict[str, Any], labels: Dict[str, str], fallback_index: int = 0) -> Dict[str, Any]:
    direct_fields = {}
    for label, target_column in labels.items():
        if label.startswith("direct__"):
            direct_fields[target_column] = row.get(label, "")
    standard = {key: row.get(key, "") for key in FIELD_MAP}
    if not standard.get("source_id"):
        standard["source_id"] = standard.get("info_id") or str(fallback_index)
    standard["source_id"] = clean_text(standard.get("source_id"))
    standard["direct_fields"] = direct_fields
    standard["raw"] = dict(row)
    return standard


def _matches_keyword(record: Dict[str, Any], keyword: str) -> bool:
    if not keyword.strip():
        return True
    haystack = " ".join(
        [
            clean_text(record.get("source_id")),
            clean_text(record.get("info_id")),
            clean_text(record.get("title")),
            clean_text(record.get("region")),
            clean_text(record.get("related_info")),
            html_to_text(clean_text(record.get("html"))),
            clean_text(record.get("text")),
        ]
    )
    return keyword in haystack


def _preview(record: Dict[str, Any], max_length: int = 200) -> str:
    text_value = clean_text(record.get("text")) or html_to_text(clean_text(record.get("html")))
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value[:max_length]


def read_records(config: DatabaseConfig) -> List[Dict[str, Any]]:
    engine, table = _table(config)
    selected, labels = _selected_columns(config, table)
    statement = _base_statement(config, table, selected)
    limit = config.query.get("limit")
    if limit not in (None, ""):
        statement = statement.limit(int(limit))

    records: List[Dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            for index, row in enumerate(conn.execute(statement).mappings(), start=1):
                records.append(_to_standard(dict(row), labels, index))
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database query failed: {exc}") from exc
    return records


def read_record_page(config: DatabaseConfig, keyword: str = "", page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    page = max(int(page or 1), 1)
    page_size = max(min(int(page_size or 20), 100), 1)
    all_records = [record for record in read_records(config) if _matches_keyword(record, keyword)]
    total = len(all_records)
    start = (page - 1) * page_size
    page_records = all_records[start : start + page_size]
    return {
        "total": total,
        "records": [
            {
                "source_id": record.get("source_id", ""),
                "info_id": record.get("info_id", ""),
                "title": record.get("title", ""),
                "article_time": record.get("article_time", ""),
                "audit_time": record.get("audit_time", ""),
                "region": record.get("region", ""),
                "related_info": record.get("related_info", ""),
                "content_preview": _preview(record),
            }
            for record in page_records
        ],
    }


def read_records_by_ids(config: DatabaseConfig, selected_ids: List[str]) -> List[Dict[str, Any]]:
    selected_ids = [clean_text(item) for item in selected_ids if clean_text(item)]
    if not selected_ids:
        return []
    engine, table = _table(config)
    identity_name = identity_column_name(config)
    if identity_name not in table.c:
        raise RuntimeError(f"Configured identity column does not exist: {identity_name}")
    selected, labels = _selected_columns(config, table)
    statement = _base_statement(config, table, selected).where(table.c[identity_name].in_(bindparam("selected_ids", expanding=True)))
    try:
        with engine.connect() as conn:
            rows = conn.execute(statement, {"selected_ids": selected_ids}).mappings()
            return [_to_standard(dict(row), labels, index) for index, row in enumerate(rows, start=1)]
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database query failed for selected records: {exc}") from exc
