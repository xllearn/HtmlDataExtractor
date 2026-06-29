from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, text


def seed_database(output: Path, record_path: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    engine = create_engine(f"sqlite:///{output}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS policy_article (
                    article_id TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    audit_time TEXT,
                    region TEXT,
                    source TEXT,
                    insurancetypename TEXT
                )
                """
            )
        )
        conn.execute(text("DELETE FROM policy_article WHERE article_id = :article_id"), {"article_id": record["info_id"]})
        conn.execute(
            text(
                """
                INSERT INTO policy_article
                (article_id, title, content, audit_time, region, source, insurancetypename)
                VALUES
                (:article_id, :title, :content, :audit_time, :region, :source, :insurance)
                """
            ),
            {
                "article_id": record["info_id"],
                "title": record["title"],
                "content": record["text"],
                "audit_time": record["audit_time"],
                "region": record["region"],
                "source": record["related_info"],
                "insurance": record["direct_fields"].get("保险类型", ""),
            },
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="写入陇南两病政策图片人工提取样例到 SQLite 测试库")
    parser.add_argument("--output", default="outputs/longnan_image_policy.sqlite", help="SQLite 输出路径")
    parser.add_argument("--record", default="examples/longnan_image_policy_record.json", help="人工提取样例 JSON")
    args = parser.parse_args()
    path = seed_database(Path(args.output), Path(args.record))
    print(path)


if __name__ == "__main__":
    main()
