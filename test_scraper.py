from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app import app, tasks
from scraper import (
    TARGET_COLUMNS,
    build_sample_html,
    clean_deduplicate_sort,
    extract_from_html,
    save_excel,
)


client = TestClient(app)


def test_extract_from_sample_html():
    records = extract_from_html("sample.html", build_sample_html(), keyword="西安 医保 门诊")
    assert len(records) == 2
    assert records[0]["地区名称"] == "陕西省-西安市"
    assert records[0]["类型"] == "门诊统筹"
    assert records[0]["报销比例"] == "70%"
    assert list(records[0].keys()) == TARGET_COLUMNS


def test_keyword_filter():
    records = extract_from_html("sample.html", build_sample_html(), keyword="完全不相关")
    assert records == []


def test_clean_deduplicate_sort():
    rows = [
        {"文章时间": "2026-05-22", "info_id": "2", "类型": "门诊", "报销比例": "70%"},
        {"文章时间": "2026-01-01", "info_id": "1", "类型": "住院", "报销比例": "80%"},
        {"文章时间": "2026-05-22", "info_id": "2", "类型": "门诊", "报销比例": "70%"},
    ]
    df = clean_deduplicate_sort(rows)
    assert len(df) == 2
    assert df.iloc[0]["info_id"] == "1"
    assert list(df.columns) == TARGET_COLUMNS


def test_save_excel(tmp_path: Path):
    output = tmp_path / "result.xlsx"
    rows = extract_from_html("sample.html", build_sample_html(), keyword="医保")
    save_excel(rows, str(output), logs=[{"source": "sample.html", "status": "success"}], append=False)
    df = pd.read_excel(output, sheet_name="结果数据")
    assert list(df.columns) == TARGET_COLUMNS
    assert len(df) == 2


def test_api_sample():
    response = client.get("/api/sample")
    assert response.status_code == 200
    data = response.json()
    assert data["records"]
    assert data["logs"][0]["status"] == "success"


def test_api_task_lifecycle(tmp_path: Path):
    tasks.clear()
    output = tmp_path / "web_result.xlsx"
    response = client.post(
        "/api/task/start",
        json={
            "url": "",
            "keyword": "西安 医保 门诊",
            "api_key": "",
            "output_file": str(output),
            "use_browser": False,
            "make_sample": True,
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    status = client.get(f"/api/task/status/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"

    result = client.get(f"/api/task/result/{task_id}")
    assert result.status_code == 200
    assert result.json()["data"]

    download = client.get(f"/api/task/download/{task_id}")
    assert download.status_code == 200
