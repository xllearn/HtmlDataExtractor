import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from sqlalchemy import MetaData, String, and_, bindparam, cast, create_engine, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from cleaner import clean_text
from columns import TARGET_COLUMNS
from extractor import html_to_text


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

KEYWORD_SYNONYMS = {
    "医保": ["医保", "医疗保险", "基本医疗保险", "职工医保", "居民医保"],
    "医疗保险": ["医保", "医疗保险", "基本医疗保险", "职工医保", "居民医保"],
    "门诊": ["门诊", "门诊统筹", "慢特病", "门诊慢特病", "两病"],
    "慢特病": ["慢特病", "门诊慢特病", "门诊"],
    "两病": ["两病", "高血压", "糖尿病", "门诊用药"],
    "住院": ["住院", "入院", "出院"],
    "报销": ["报销", "报销比例", "支付比例", "待遇"],
    "待遇": ["待遇", "报销", "补助"],
    "补助": ["补助", "补助限额", "限额"],
    "起付": ["起付", "起付标准", "起付线"],
    "限额": ["限额", "补助限额", "支付限额"],
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
    direct_fields = {str(key): str(value or "") for key, value in direct.items() if key in TARGET_COLUMNS and str(value or "")}
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
    if config.source.get("id_column"):
        return config.source["id_column"]
    if config.source.get("info_id_column"):
        return config.source["info_id_column"]
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


def _configured_conditions(config: DatabaseConfig) -> List[Any]:
    where_clause = str(config.query.get("where") or "").strip()
    return [text(where_clause)] if where_clause else []


def _apply_order_by(statement, config: DatabaseConfig):
    order_by = str(config.query.get("order_by") or "").strip()
    return statement.order_by(text(order_by)) if order_by else statement


def _query_limit(config: DatabaseConfig) -> int | None:
    limit = config.query.get("limit")
    if limit in (None, ""):
        return None
    return max(int(limit), 0)


def _base_statement(config: DatabaseConfig, table, selected: List[Any]):
    statement = select(*selected)
    for condition in _configured_conditions(config):
        statement = statement.where(condition)
    return _apply_order_by(statement, config)


def keyword_terms(keyword: str) -> List[List[str]]:
    parts = [part for part in re.split(r"[\s,，、;；]+", clean_text(keyword)) if part]
    groups = []
    for part in parts:
        terms = KEYWORD_SYNONYMS.get(part, [part])
        groups.append(list(dict.fromkeys(clean_text(term) for term in terms if clean_text(term))))
    return groups


def _keyword_conditions(config: DatabaseConfig, keyword: str, table, labels: Dict[str, str]) -> Tuple[List[Any], Dict[str, str]]:
    groups = keyword_terms(keyword)
    if not groups:
        return [], {}
    columns = []
    for standard_key in ("title", "text", "html", "info_id", "region", "related_info"):
        column_name = labels.get(standard_key)
        if column_name and column_name in table.c:
            columns.append(cast(table.c[column_name], String))
    if not columns:
        return [], {}
    params: Dict[str, str] = {}
    per_keyword = []
    for group_index, terms in enumerate(groups):
        term_conditions = []
        for term_index, term in enumerate(terms):
            param_name = f"keyword_{group_index}_{term_index}"
            params[param_name] = f"%{term}%"
            term_conditions.extend(column.like(bindparam(param_name)) for column in columns)
        per_keyword.append(or_(*term_conditions))
    mode = str(config.query.get("keyword_mode") or config.query.get("search_mode") or "or").lower()
    return [and_(*per_keyword) if mode == "and" else or_(*per_keyword)], params


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


def _preview(record: Dict[str, Any], max_length: int = 200) -> str:
    text_value = clean_text(record.get("text")) or html_to_text(clean_text(record.get("html")))
    return re.sub(r"\s+", " ", text_value).strip()[:max_length]


def read_records(config: DatabaseConfig) -> List[Dict[str, Any]]:
    engine, table = _table(config)
    selected, labels = _selected_columns(config, table)
    statement = _base_statement(config, table, selected)
    limit = _query_limit(config)
    if limit is not None:
        statement = statement.limit(limit)
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
    engine, table = _table(config)
    selected, labels = _selected_columns(config, table)
    keyword_filters, keyword_params = _keyword_conditions(config, keyword, table, labels)
    conditions = _configured_conditions(config) + keyword_filters
    configured_limit = _query_limit(config)
    offset = (page - 1) * page_size

    count_statement = select(func.count()).select_from(table)
    for condition in conditions:
        count_statement = count_statement.where(condition)

    statement = select(*selected)
    for condition in conditions:
        statement = statement.where(condition)
    statement = _apply_order_by(statement, config).offset(offset).limit(page_size)

    try:
        with engine.connect() as conn:
            total = int(conn.execute(count_statement, keyword_params).scalar() or 0)
            if configured_limit is not None:
                total = min(total, configured_limit)
            rows = [dict(row) for row in conn.execute(statement, keyword_params).mappings()]
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database page query failed: {exc}") from exc

    records = []
    for index, row in enumerate(rows, start=offset + 1):
        standard = _to_standard(row, labels, index)
        preview = _preview(standard)
        records.append(
            {
                "source_id": standard["source_id"],
                "info_id": clean_text(standard.get("info_id")),
                "title": clean_text(standard.get("title")),
                "article_time": clean_text(standard.get("article_time")),
                "audit_time": clean_text(standard.get("audit_time")),
                "region": clean_text(standard.get("region")),
                "related_info": clean_text(standard.get("related_info")),
                "content_preview": preview,
            }
        )
    return {"total": total, "records": records}


def read_records_by_ids(config: DatabaseConfig, selected_ids: List[str]) -> List[Dict[str, Any]]:
    if not selected_ids:
        return []
    engine, table = _table(config)
    selected, labels = _selected_columns(config, table)
    id_name = identity_column_name(config)
    if id_name not in table.c:
        raise RuntimeError(f"Configured identity column does not exist: {id_name}")
    statement = select(*selected).where(cast(table.c[id_name], String).in_([str(item) for item in selected_ids]))
    statement = _apply_order_by(statement, config)
    try:
        with engine.connect() as conn:
            rows = [dict(row) for row in conn.execute(statement).mappings()]
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database selected-id query failed: {exc}") from exc
    return [_to_standard(row, labels, index) for index, row in enumerate(rows, start=1)]
