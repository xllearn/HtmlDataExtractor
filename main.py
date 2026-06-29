import argparse
from pathlib import Path
from typing import Any, Dict, List

from cleaner import clean_records, load_field_mapping
from db_reader import load_db_config, read_records, read_records_by_ids
from excel_writer import write_excel
from extractor import extract_record
from llm_extractor import llm_available, load_llm_config


def run_pipeline(
    config_path: str | Path = "config/db_config.yml",
    field_config_path: str | Path = "config/field_mapping.yml",
    output_path: str | Path = "outputs/result.xlsx",
    keyword: str = "",
    template_path: str | Path = "template/陕西西安.xlsx",
    selected_ids: List[str] | None = None,
    use_llm: bool | None = None,
    llm_config_path: str | Path = "config/llm_config.yml",
) -> Dict[str, Any]:
    db_config = load_db_config(config_path)
    field_mapping = load_field_mapping(field_config_path)
    llm_config = load_llm_config(llm_config_path)
    try:
        db_records = read_records_by_ids(db_config, selected_ids) if selected_ids else read_records(db_config)
    except Exception as exc:
        raise RuntimeError(f"数据库查询失败: {exc}") from exc

    extracted: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    for db_record in db_records:
        try:
            records, log = extract_record(
                db_record,
                field_mapping.output_columns,
                keyword=keyword,
                use_llm=use_llm,
                llm_config=llm_config,
                llm_config_path=str(llm_config_path),
            )
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
                    "llm_used": False,
                    "llm_success": False,
                    "need_manual_review": True,
                    "review_reason": str(exc),
                }
            )

    cleaned = clean_records(extracted, field_mapping)
    output_file = write_excel(cleaned, logs, output_path, field_mapping.output_columns, template_path=template_path)
    return {
        "read_count": len(db_records),
        "selected_count": len(selected_ids or []),
        "success_count": sum(1 for log in logs if log.get("status") == "success"),
        "failed_count": sum(1 for log in logs if log.get("status") == "failed"),
        "skipped_count": sum(1 for log in logs if log.get("status") == "skipped_keyword"),
        "empty_count": sum(1 for log in logs if log.get("status") == "empty_content"),
        "manual_review_count": sum(1 for log in logs if log.get("need_manual_review")),
        "llm_success_count": sum(1 for log in logs if log.get("llm_success")),
        "llm_failed_count": sum(1 for log in logs if log.get("llm_used") and not log.get("llm_success")),
        "output_file": output_file,
        "records": cleaned,
        "logs": logs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从数据库读取文章内容并生成固定 26 列 Excel")
    parser.add_argument("--config", default="config/db_config.yml", help="数据库配置文件路径")
    parser.add_argument("--field-config", default="config/field_mapping.yml", help="字段配置文件路径")
    parser.add_argument("--output", default="outputs/result.xlsx", help="输出 Excel 路径")
    parser.add_argument("--keyword", default="", help="关键词/同义词扩展搜索词")
    parser.add_argument("--template", default="template/陕西西安.xlsx", help="Excel 模板路径")
    parser.add_argument("--llm-config", default="config/llm_config.yml", help="LLM 配置文件路径")
    llm_group = parser.add_mutually_exclusive_group()
    llm_group.add_argument("--use-llm", action="store_true", help="启用规则 + DeepSeek 大模型融合提取")
    llm_group.add_argument("--no-llm", action="store_true", help="强制禁用大模型，仅使用规则提取")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    force_llm = True if args.use_llm else False if args.no_llm else None
    if args.use_llm:
        available, reason = llm_available(load_llm_config(args.llm_config))
        if not available:
            print(f"DeepSeek 未启用：{reason}")
    summary = run_pipeline(
        args.config,
        args.field_config,
        args.output,
        keyword=args.keyword,
        template_path=args.template,
        use_llm=force_llm,
        llm_config_path=args.llm_config,
    )
    print(f"读取记录数: {summary['read_count']}")
    print(f"成功记录数: {summary['success_count']}")
    print(f"失败记录数: {summary['failed_count']}")
    print(f"需要人工复核数: {summary['manual_review_count']}")
    print(f"LLM 调用成功数: {summary['llm_success_count']}")
    print(f"LLM 调用失败数: {summary['llm_failed_count']}")
    print(f"输出文件路径: {summary['output_file']}")


if __name__ == "__main__":
    main()
