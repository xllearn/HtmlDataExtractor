import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from cleaner import fill_missing_by_field, load_field_mapping
from columns import TARGET_COLUMNS
from db_reader import load_db_config, read_record_page
from extractor import extract_record
from main import SUMMARY_KEYS, run_pipeline, summary_defaults


app = FastAPI(title="数据库文章内容自动提取与 Excel 整理工具")
app.mount("/static", StaticFiles(directory="static"), name="static")

ALLOWED_CONFIGS: Dict[str, Dict[str, str]] = {
    "default": {
        "config_path": "config/db_config.yml",
        "field_config_path": "config/field_mapping.yml",
        "template_path": "template/陕西西安.xlsx",
        "llm_config_path": "config/llm_config.yml",
        "table_mapping_path": "config/table_mapping.yml",
    }
}

SYSTEM_CONFIG_DISPLAY = {
    "数据库配置": "config/db_config.yml",
    "字段配置": "config/field_mapping.yml",
    "表格映射": "config/table_mapping.yml",
    "Excel 模板": "template/陕西西安.xlsx",
    "LLM 配置": "config/llm_config.yml",
    "输出目录": "outputs/{task_id}/result.xlsx",
}

tasks: Dict[str, Dict[str, Any]] = {}


class PipelineRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keyword: str = ""
    use_llm: Optional[bool] = None
    config_key: str = "default"


class SelectedPipelineRequest(PipelineRequest):
    selected_ids: List[str] = Field(default_factory=list)


class TaskStartResponse(BaseModel):
    task_id: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None
    output_file: Optional[str] = None


class PipelineResponse(BaseModel):
    status: str
    message: str
    summary: Dict[str, Any]
    data: List[Dict[str, Any]]
    logs: List[Dict[str, Any]]
    field_evidence: List[Dict[str, Any]] = []
    conflict_evidence: List[Dict[str, Any]] = []


def allowed_config(config_key: str) -> Dict[str, str]:
    if config_key not in ALLOWED_CONFIGS:
        raise HTTPException(status_code=400, detail="config_key 不在允许的配置白名单中")
    return ALLOWED_CONFIGS[config_key]


def read_result(path: str) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    try:
        df = pd.read_excel(path, sheet_name="结果数据")
    except Exception:
        df = pd.read_excel(path, sheet_name=0)
    for column in TARGET_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[TARGET_COLUMNS].fillna("").to_dict("records")


def summarize(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    return summary_defaults(summary)


def task_dir(task_id: str) -> Path:
    return Path("outputs") / task_id


def task_output_path(task_id: str, request: PipelineRequest | None = None) -> Path:
    return task_dir(task_id) / "result.xlsx"


def task_status_path(task_id: str) -> Path:
    return task_dir(task_id) / "status.json"


def task_log_path(task_id: str) -> Path:
    return task_dir(task_id) / "task_log.json"


def normalize_task(task: Dict[str, Any], task_id: str | None = None) -> Dict[str, Any]:
    task = dict(task)
    task["summary"] = summarize(task.get("summary"))
    if not task.get("output_file") and task_id:
        task["output_file"] = str(task_output_path(task_id))
    task["summary"]["output_file"] = task.get("output_file") or task["summary"].get("output_file", "")
    task.setdefault("data", [])
    task.setdefault("logs", [])
    task.setdefault("field_evidence", [])
    task.setdefault("conflict_evidence", [])
    return task


def persist_task(task_id: str) -> None:
    task_dir(task_id).mkdir(parents=True, exist_ok=True)
    task = normalize_task(tasks[task_id], task_id)
    tasks[task_id] = task
    task_status_path(task_id).write_text(json.dumps(task, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    task_log_path(task_id).write_text(json.dumps(task.get("logs") or [], ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_persisted_task(task_id: str) -> Dict[str, Any] | None:
    path = task_status_path(task_id)
    if not path.exists():
        return None
    return normalize_task(json.loads(path.read_text(encoding="utf-8")), task_id)


def run_task(task_id: str, request: PipelineRequest, selected_ids: Optional[List[str]] = None) -> None:
    tasks[task_id]["status"] = "running"
    persist_task(task_id)
    try:
        cfg = allowed_config(request.config_key)
        output_file = task_output_path(task_id)
        summary = run_pipeline(
            cfg["config_path"],
            cfg["field_config_path"],
            output_file,
            keyword=request.keyword,
            template_path=cfg["template_path"],
            selected_ids=selected_ids,
            use_llm=request.use_llm,
            llm_config_path=cfg["llm_config_path"],
            table_mapping_path=cfg["table_mapping_path"],
        )
        task_summary = summarize(summary)
        tasks[task_id].update(
            {
                "status": "completed",
                "message": f"读取 {summary['read_count']} 条，成功 {summary['success_count']} 条，失败 {summary['failed_count']} 条",
                "summary": task_summary,
                "output_file": str(output_file),
                "data": summary["records"],
                "logs": summary["logs"],
                "field_evidence": summary.get("field_evidence", []),
                "conflict_evidence": summary.get("conflict_evidence", []),
            }
        )
    except Exception as exc:
        failed_summary = summarize(tasks[task_id].get("summary"))
        tasks[task_id].update({"status": "failed", "message": str(exc), "summary": failed_summary})
    persist_task(task_id)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/result")
async def result_page() -> FileResponse:
    return FileResponse("static/result.html")


@app.get("/api/config")
async def config_info(config_key: str = Query("default")) -> Dict[str, Any]:
    allowed_config(config_key)
    return {"status": "success", "config_key": config_key, "paths": SYSTEM_CONFIG_DISPLAY}


@app.get("/api/db/records")
async def db_records(
    config_key: str = Query("default"),
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        cfg = allowed_config(config_key)
        config = load_db_config(cfg["config_path"])
        result = read_record_page(config, keyword=keyword, page=page, page_size=page_size)
        return {"status": "success", "page": page, "page_size": page_size, "total": result["total"], "records": result["records"]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"数据库读取失败: {exc}") from exc


@app.post("/api/task/start", response_model=TaskStartResponse)
async def start_task(request: PipelineRequest, background_tasks: BackgroundTasks) -> TaskStartResponse:
    allowed_config(request.config_key)
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "message": "任务已提交",
        "summary": summarize({}),
        "output_file": str(task_output_path(task_id)),
        "data": [],
        "logs": [],
        "field_evidence": [],
        "conflict_evidence": [],
    }
    persist_task(task_id)
    background_tasks.add_task(run_task, task_id, request, None)
    return TaskStartResponse(task_id=task_id, message="任务已提交，正在后台提取")


@app.post("/api/task/start-selected", response_model=TaskStartResponse)
async def start_selected_task(request: SelectedPipelineRequest, background_tasks: BackgroundTasks) -> TaskStartResponse:
    allowed_config(request.config_key)
    selected_ids = [str(item).strip() for item in request.selected_ids if str(item).strip()]
    if not selected_ids:
        raise HTTPException(status_code=400, detail="请至少选择一条数据")
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "message": "任务已提交",
        "summary": summarize({"selected_count": len(selected_ids)}),
        "output_file": str(task_output_path(task_id)),
        "data": [],
        "logs": [],
        "field_evidence": [],
        "conflict_evidence": [],
    }
    persist_task(task_id)
    background_tasks.add_task(run_task, task_id, request, selected_ids)
    return TaskStartResponse(task_id=task_id, message="任务已提交，正在后台提取")


@app.get("/api/task/status/{task_id}", response_model=TaskStatusResponse)
async def task_status(task_id: str) -> TaskStatusResponse:
    task = tasks.get(task_id) or load_persisted_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatusResponse(task_id=task_id, status=task["status"], message=task.get("message"), output_file=task.get("output_file"))


@app.get("/api/task/result/{task_id}", response_model=PipelineResponse)
async def task_result(task_id: str) -> PipelineResponse:
    task = tasks.get(task_id) or load_persisted_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"任务尚未完成，当前状态：{task['status']}")
    task = normalize_task(task, task_id)
    return PipelineResponse(
        status="success",
        message=task.get("message") or "提取完成",
        summary=task.get("summary") or summarize({}),
        data=task.get("data") or [],
        logs=task.get("logs") or [],
        field_evidence=task.get("field_evidence") or [],
        conflict_evidence=task.get("conflict_evidence") or [],
    )


@app.get("/api/task/download/{task_id}")
async def task_download(task_id: str) -> FileResponse:
    task = tasks.get(task_id) or load_persisted_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")
    output_file = task.get("output_file")
    if not output_file or not Path(output_file).exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(output_file, filename=os.path.basename(output_file), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/sample")
async def sample() -> Dict[str, Any]:
    record_path = Path("examples/sample_db_record.json")
    result_path = Path("examples/sample_result.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mapping = load_field_mapping("config/field_mapping.yml")
    records, log = extract_record(record, mapping.output_columns, keyword="医保", use_llm=False)
    result = fill_missing_by_field(records[0], mapping) if records else {}
    expected = json.loads(result_path.read_text(encoding="utf-8"))
    diff_fields = [{"field": field, "expected": expected.get(field, ""), "actual": result.get(field, "")} for field in TARGET_COLUMNS if expected.get(field, "") != result.get(field, "")]
    return {"record": record, "result": result, "expected_result": expected, "sample_matched": not diff_fields, "diff_fields": diff_fields, "logs": [log]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
