import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scraper import TARGET_COLUMNS, save_excel, scrape_and_extract, write_sample


app = FastAPI(title="网页自动化采集与整理工具")
app.mount("/static", StaticFiles(directory="static"), name="static")

tasks: Dict[str, Dict[str, Any]] = {}


class ScrapeRequest(BaseModel):
    url: str = ""
    keyword: str = ""
    api_key: str = ""
    output_file: str = "采集结果.xlsx"
    use_browser: bool = True
    make_sample: bool = False


class TaskStartResponse(BaseModel):
    task_id: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None
    output_file: Optional[str] = None


class ScrapeResponse(BaseModel):
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


def run_task(task_id: str, request: ScrapeRequest) -> None:
    tasks[task_id]["status"] = "running"
    try:
        sources: List[str] = []
        if request.make_sample:
            sources.append(write_sample())
        if request.url.strip():
            sources.extend([item.strip() for item in request.url.splitlines() if item.strip()])
        if not sources:
            raise ValueError("请提供 URL/本地 HTML 路径，或勾选生成示例")

        records, logs = scrape_and_extract(
            sources=sources,
            keyword=request.keyword,
            api_key=request.api_key,
            use_browser=request.use_browser,
        )
        save_excel(records, request.output_file, logs=logs, append=False)
        tasks[task_id].update(
            {
                "status": "completed",
                "message": f"完成，抽取 {len(records)} 条记录",
                "output_file": request.output_file,
                "data": read_result(request.output_file),
                "logs": logs,
            }
        )
    except Exception as exc:
        tasks[task_id].update({"status": "failed", "message": str(exc)})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.post("/api/task/start", response_model=TaskStartResponse)
async def start_task(request: ScrapeRequest, background_tasks: BackgroundTasks) -> TaskStartResponse:
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "message": "任务已提交",
        "output_file": request.output_file,
        "data": [],
        "logs": [],
    }
    background_tasks.add_task(run_task, task_id, request)
    return TaskStartResponse(task_id=task_id, message="任务已提交，正在后台采集")


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


@app.get("/api/task/result/{task_id}", response_model=ScrapeResponse)
async def task_result(task_id: str) -> ScrapeResponse:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"任务尚未完成，当前状态：{task['status']}")
    return ScrapeResponse(
        status="success",
        message=task.get("message") or "采集完成",
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
    sample_path = write_sample()
    records, logs = scrape_and_extract([sample_path], keyword="西安 医保 门诊 报销", use_browser=False)
    return {"sample_file": sample_path, "records": records, "logs": logs}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
