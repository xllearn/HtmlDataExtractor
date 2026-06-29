import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cleaner import load_field_mapping, fill_missing_by_field
from columns import TARGET_COLUMNS
from extractor import extract_record
from main import run_pipeline


app = FastAPI(title="数据库文章内容自动提取与 Excel 整理工具")
app.mount("/static", StaticFiles(directory="static"), name="static")

tasks: Dict[str, Dict[str, Any]] = {}


class PipelineRequest(BaseModel):
    config_path: str = "config/db_config.yml"
    field_config_path: str = "config/field_mapping.yml"
    template_path: str = "template/陕西西安.xlsx"
    keyword: str = ""
    output_file: str = "outputs/result.xlsx"


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
    data: List[Dict[str, Any]]
    logs: List[Dict[str, Any]]


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


def run_task(task_id: str, request: PipelineRequest) -> None:
    tasks[task_id]["status"] = "running"
    try:
        summary = run_pipeline(
            request.config_path,
            request.field_config_path,
            request.output_file,
            keyword=request.keyword,
            template_path=request.template_path,
        )
        tasks[task_id].update(
            {
                "status": "completed",
                "message": (
                    f"读取 {summary['read_count']} 条，成功 {summary['success_count']} 条，"
                    f"失败 {summary['failed_count']} 条"
                ),
                "output_file": summary["output_file"],
                "data": summary["records"],
                "logs": summary["logs"],
            }
        )
    except Exception as exc:
        tasks[task_id].update({"status": "failed", "message": str(exc)})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.post("/api/task/start", response_model=TaskStartResponse)
async def start_task(request: PipelineRequest, background_tasks: BackgroundTasks) -> TaskStartResponse:
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "message": "任务已提交",
        "output_file": request.output_file,
        "data": [],
        "logs": [],
    }
    background_tasks.add_task(run_task, task_id, request)
    return TaskStartResponse(task_id=task_id, message="任务已提交，正在后台提取")


@app.get("/api/task/status/{task_id}", response_model=TaskStatusResponse)
async def task_status(task_id: str) -> TaskStatusResponse:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        message=task.get("message"),
        output_file=task.get("output_file"),
    )


@app.get("/api/task/result/{task_id}", response_model=PipelineResponse)
async def task_result(task_id: str) -> PipelineResponse:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"任务尚未完成，当前状态：{task['status']}")
    return PipelineResponse(
        status="success",
        message=task.get("message") or "提取完成",
        data=task.get("data") or [],
        logs=task.get("logs") or [],
    )


@app.get("/api/task/download/{task_id}")
async def task_download(task_id: str) -> FileResponse:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")
    output_file = task.get("output_file")
    if not output_file or not Path(output_file).exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(
        output_file,
        filename=os.path.basename(output_file),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/sample")
async def sample() -> Dict[str, Any]:
    record_path = Path("examples/sample_db_record.json")
    result_path = Path("examples/sample_result.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mapping = load_field_mapping("config/field_mapping.yml")
    records, logs = extract_record(record, mapping.output_columns, keyword="医保")
    result = fill_missing_by_field(records[0], mapping) if records else {}
    expected = json.loads(result_path.read_text(encoding="utf-8"))
    return {"record": record, "result": result, "expected_result": expected, "logs": [logs]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
