from pathlib import Path

import yaml


def write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def field_config(path: Path) -> Path:
    from columns import TARGET_COLUMNS

    return write_yaml(
        path,
        {
            "output_columns": TARGET_COLUMNS,
            "default_missing_value": "",
            "field_missing_values": {
                "审核状态0待审核1已审核": "0",
                "是否需要手动修改执行状态(1是0否)": "0",
            },
        },
    )


def test_pipeline_falls_back_to_rules_without_deepseek_key(tmp_path: Path, monkeypatch):
    from sqlalchemy import create_engine, text

    from main import run_pipeline

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    db_path = tmp_path / "pipeline.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE policy_article (article_id TEXT PRIMARY KEY, title TEXT, content TEXT, publish_time TEXT, region TEXT)"))
        conn.execute(
            text(
                "INSERT INTO policy_article (article_id, title, content, publish_time, region) "
                "VALUES ('A-1', '医保政策', '医保 类型：门诊 报销比例：70% 起付标准：200元', '2026-05-22', '西安市')"
            )
        )

    db_config = write_yaml(
        tmp_path / "db.yml",
        {
            "database": {"url": f"sqlite:///{db_path}"},
            "source": {
                "table": "policy_article",
                "id_column": "",
                "info_id_column": "article_id",
                "title_column": "title",
                "html_column": "",
                "text_column": "content",
                "article_time_column": "publish_time",
                "audit_time_column": "",
                "region_column": "region",
                "related_info_column": "",
            },
            "query": {"where": "", "limit": "", "order_by": "article_id ASC"},
        },
    )

    summary = run_pipeline(
        db_config,
        field_config(tmp_path / "fields.yml"),
        tmp_path / "result.xlsx",
        keyword="医保",
        use_llm=True,
        llm_config_path="config/llm_config.yml",
    )

    assert summary["success_count"] == 1
    assert summary["llm_success_count"] == 0
    assert summary["llm_failed_count"] == 0
    assert summary["logs"][0]["llm_used"] is False
    assert "DEEPSEEK_API_KEY" in summary["logs"][0]["message"]


def test_web_task_output_path_is_task_scoped(tmp_path: Path):
    from app import PipelineRequest, task_output_path

    request = PipelineRequest(output_file=str(tmp_path / "unsafe.xlsx"))
    path = task_output_path("task-123", request)

    assert str(path).replace("\\", "/").endswith("outputs/task-123/result.xlsx")
