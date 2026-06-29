import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml
from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    source: Dict[str, str]
    query: Dict[str, Any]


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
    if not url:
        raise ValueError("database.url is required")
    if not source.get("table"):
        raise ValueError("source.table is required")
    return DatabaseConfig(url=url, source={str(k): str(v or "") for k, v in source.items()}, query=query)


def read_records(config: DatabaseConfig) -> List[Dict[str, Any]]:
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

    selected = []
    labels: Dict[str, str] = {}
    for standard_key, config_key in FIELD_MAP.items():
        column_name = config.source.get(config_key, "")
        if column_name and column_name in table.c:
            selected.append(table.c[column_name].label(standard_key))
            labels[standard_key] = column_name
    if not selected:
        raise RuntimeError("No configured source columns exist in the database table")

    statement = select(*selected)
    where_clause = str(config.query.get("where") or "").strip()
    if where_clause:
        statement = statement.where(text(where_clause))
    order_by = str(config.query.get("order_by") or "").strip()
    if order_by:
        statement = statement.order_by(text(order_by))
    limit = config.query.get("limit")
    if limit not in (None, ""):
        statement = statement.limit(int(limit))

    records: List[Dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            for index, row in enumerate(conn.execute(statement).mappings(), start=1):
                raw = dict(row)
                standard = {key: raw.get(key, "") for key in FIELD_MAP}
                if not standard.get("source_id"):
                    standard["source_id"] = str(index)
                else:
                    standard["source_id"] = str(standard["source_id"])
                standard["raw"] = raw
                records.append(standard)
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database query failed: {exc}") from exc
    return records
