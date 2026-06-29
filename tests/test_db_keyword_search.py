from pathlib import Path

import yaml


def write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_db_keyword_search_supports_multi_terms_and_synonyms(tmp_path: Path):
    from sqlalchemy import create_engine, text

    from db_reader import load_db_config, read_record_page

    db_path = tmp_path / "articles.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE policy_article (article_id TEXT PRIMARY KEY, title TEXT, content TEXT, region TEXT, related_info TEXT)"))
        conn.execute(text("INSERT INTO policy_article VALUES ('A-1', '医疗保险门诊待遇', '报销比例70%', '西安市', '来源A')"))
        conn.execute(text("INSERT INTO policy_article VALUES ('A-2', '住院待遇', '补助限额10万', '西安市', '来源B')"))
        conn.execute(text("INSERT INTO policy_article VALUES ('A-3', '普通通知', '无待遇', '西安市', '来源C')"))

    config_path = write_yaml(
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
                "article_time_column": "",
                "audit_time_column": "",
                "region_column": "region",
                "related_info_column": "related_info",
            },
            "query": {"where": "", "limit": "", "order_by": "article_id ASC", "keyword_mode": "and"},
        },
    )

    page = read_record_page(load_db_config(config_path), keyword="医保 门诊", page=1, page_size=20)

    assert page["total"] == 1
    assert page["records"][0]["source_id"] == "A-1"
