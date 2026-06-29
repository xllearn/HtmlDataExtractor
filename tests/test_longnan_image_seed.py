import json
from pathlib import Path

import yaml


def write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def field_config(path: Path) -> Path:
    from columns import TARGET_COLUMNS

    return write_yaml(path, {"output_columns": TARGET_COLUMNS, "default_missing_value": "", "field_missing_values": {}})


def test_longnan_image_manual_data_seed_generates_multiple_rows(tmp_path: Path):
    from main import run_pipeline
    from scripts.seed_longnan_image_policy import seed_database

    db_path = tmp_path / "longnan.sqlite"
    seed_database(db_path, Path("examples/longnan_image_policy_record.json"))
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
                "article_time_column": "audit_time",
                "audit_time_column": "audit_time",
                "region_column": "region",
                "related_info_column": "source",
            },
            "direct_field_columns": {"保险类型": "insurancetypename"},
            "query": {"where": "", "limit": "", "order_by": "article_id ASC"},
        },
    )

    summary = run_pipeline(db_config, field_config(tmp_path / "fields.yml"), tmp_path / "result.xlsx", keyword="", use_llm=False, template_path="")

    names = [row["病种名称"] for row in summary["records"]]
    assert len(summary["records"]) == 18
    assert "糖尿病" in names
    assert "高血压" in names
    assert "利血平" in names
    assert "厄贝沙坦" in names
    assert summary["logs"][0]["records"] == 18
