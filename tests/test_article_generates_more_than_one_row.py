from pathlib import Path

import openpyxl
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


def test_one_database_article_can_generate_three_excel_rows(tmp_path: Path):
    from sqlalchemy import create_engine, text

    from excel_writer import RESULT_SHEET
    from main import run_pipeline

    db_path = tmp_path / "articles.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    content = """
    陇南市城乡居民高血压糖尿病门诊用药保障政策
    “两病”门诊用药保障报销标准
    <table>
      <tr><th>病种名称</th><th>补助限额</th><th>报销比例</th></tr>
      <tr><td>糖尿病</td><td>800元</td><td>70%</td></tr>
      <tr><td>高血压</td><td>400元</td><td>70%</td></tr>
      <tr><td>同时合并高血压糖尿病</td><td>1200元</td><td>70%</td></tr>
    </table>
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE policy_article (article_id TEXT PRIMARY KEY, title TEXT, content TEXT, audit_time TEXT, region TEXT, source TEXT)"))
        conn.execute(
            text("INSERT INTO policy_article VALUES ('LN-IMAGE-1', '陇南两病门诊用药政策', :content, '2026-06-29', '甘肃省-陇南市', '图片人工提取样例')"),
            {"content": content},
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
                "html_column": "content",
                "text_column": "content",
                "article_time_column": "audit_time",
                "audit_time_column": "audit_time",
                "region_column": "region",
                "related_info_column": "source",
            },
            "query": {"where": "", "limit": "", "order_by": "article_id ASC"},
        },
    )

    output = tmp_path / "result.xlsx"
    summary = run_pipeline(db_config, field_config(tmp_path / "fields.yml"), output, keyword="两病", use_llm=False)

    assert summary["read_count"] == 1
    assert len(summary["records"]) == 3
    assert summary["logs"][0]["records"] == 3
    wb = openpyxl.load_workbook(output)
    assert wb[RESULT_SHEET].max_row == 4
