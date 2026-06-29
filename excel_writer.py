from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from openpyxl import Workbook, load_workbook

from columns import TARGET_COLUMNS

RESULT_SHEET = "结果数据"
LOG_SHEET = "采集日志"
LOG_COLUMNS = ["source_id", "info_id", "title", "status", "message", "records", "time"]


def ensure_sheet(workbook, name: str):
    if name in workbook.sheetnames:
        return workbook[name]
    return workbook.create_sheet(name)


def clear_sheet(sheet) -> None:
    if sheet.max_row:
        sheet.delete_rows(1, sheet.max_row)


def write_rows(sheet, headers: Sequence[str], rows: Iterable[Dict[str, Any]]) -> None:
    clear_sheet(sheet)
    sheet.append(list(headers))
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])


def write_excel(
    records: Iterable[Dict[str, Any]],
    logs: Iterable[Dict[str, Any]],
    output: str | Path,
    columns: Sequence[str] | None = None,
    template_path: str | Path = "",
) -> str:
    columns = list(columns or TARGET_COLUMNS)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = Path(template_path) if template_path else None
    if template and template.exists():
        workbook = load_workbook(template)
    else:
        workbook = Workbook()
        workbook.remove(workbook.active)
    result_sheet = ensure_sheet(workbook, RESULT_SHEET)
    log_sheet = ensure_sheet(workbook, LOG_SHEET)
    write_rows(result_sheet, columns, records)
    prepared_logs = []
    for log in logs:
        item = dict(log)
        item.setdefault("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        prepared_logs.append(item)
    write_rows(log_sheet, LOG_COLUMNS, prepared_logs)
    workbook.save(output_path)
    return str(output_path)
