import argparse
from pathlib import Path
from typing import Any, Dict, List

from cleaner import clean_records, load_field_mapping
from db_reader import load_db_config, read_records
from excel_writer import write_excel
from extractor import extract_record


def run_pipeline(
    config_path: str | Path = "config/db_config.yml",
    field_config_path: str | Path = "config/field_mapping.yml",
    output_path: str | Path = "outputs/result.xlsx",
    keyword: str = "",
    template_path: str | Path = "template/陕西西安.xlsx",
) -> Dict[str, Any]:
    db_config = load_db_config(config_path)
    field_mapping = load_field_mapping(field_config_path)
    try:
        db_records = read_records(db_config)
    except Exception as exc:
        raise RuntimeError(f"数据库查询失败: {exc}") from exc

    extracted: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    for db_record in db_records:
        try:
            records, log = extract_record(db_record, field_mapping.output_columns, keyword=keyword)
            extracted.extend(records)
            logs.append(log)
        except Exception as exc:
            logs.append(
                {
                    "source_id": db_record.get("source_id", ""),
                    "info_id": db_record.get("info_id", ""),
                    "title": db_record.get("title", ""),
                    "status": "failed",
                    "message": str(exc),
                    "records": 0,
                }
            )

    cleaned = clean_records(extracted, field_mapping)
    output_file = write_excel(cleaned, logs, output_path, field_mapping.output_columns, template_path=template_path)
    return {
        "read_count": len(db_records),
        "success_count": sum(1 for log in logs if log.get("status") == "success"),
        "failed_count": sum(1 for log in logs if log.get("status") == "failed"),
        "skipped_count": sum(1 for log in logs if log.get("status") == "skipped_keyword"),
        "empty_count": sum(1 for log in logs if log.get("status") == "empty_content"),
        "output_file": output_file,
        "records": cleaned,
        "logs": logs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从数据库读取文章内容并生成固定 26 列 Excel")
    parser.add_argument("--config", default="config/db_config.yml", help="数据库配置文件路径")
    parser.add_argument("--field-config", default="config/field_mapping.yml", help="字段配置文件路径")
    parser.add_argument("--output", default="outputs/result.xlsx", help="输出 Excel 路径")
    parser.add_argument("--keyword", default="", help="关键词/语义搜索词")
    parser.add_argument("--template", default="template/陕西西安.xlsx", help="Excel 模板路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_pipeline(args.config, args.field_config, args.output, keyword=args.keyword, template_path=args.template)
    print(f"读取记录数: {summary['read_count']}")
    print(f"成功记录数: {summary['success_count']}")
    print(f"失败记录数: {summary['failed_count']}")
    print(f"输出文件路径: {summary['output_file']}")


if __name__ == "__main__":
    main()
