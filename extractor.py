import re
from io import StringIO
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd
from bs4 import BeautifulSoup

from cleaner import clean_text, normalize_date, normalize_record
from columns import TARGET_COLUMNS


HEADER_ALIASES = {
    "发布时间": "文章时间",
    "发布日期": "文章时间",
    "文章时间": "文章时间",
    "审核时间": "审核日期",
    "审核日期": "审核日期",
    "地区": "地区名称",
    "地区名称": "地区名称",
    "城市": "地区名称",
    "个人账户计入": "个人账户计入办法",
    "个人账户计入办法": "个人账户计入办法",
    "个人账户使用": "个人账户使用范围",
    "个人账户使用范围": "个人账户使用范围",
    "病种": "病种名称",
    "疾病名称": "病种名称",
    "病种名称": "病种名称",
    "待遇类型": "类型",
    "类型": "类型",
    "标化类型": "标化类型",
    "保险": "保险类型",
    "险种": "保险类型",
    "保险类型": "保险类型",
    "人员类别": "人员类型",
    "人员类型": "人员类型",
    "病种类型": "病种类型",
    "就诊地域": "就诊地域",
    "医院类型": "医院类型",
    "医院级别": "医院类型",
    "就诊情况": "就诊情况",
    "区间": "区间",
    "起付标准": "起付标准",
    "起付线": "起付标准",
    "补助限额": "补助限额",
    "支付限额": "补助限额",
    "报销比例": "报销比例",
    "支付比例": "报销比例",
    "备注": "备注",
    "说明": "备注",
    "相关资讯": "相关资讯",
    "审核状态": "审核状态0待审核1已审核",
    "执行状态": "执行状态",
    "开始执行时间": "开始执行时间",
    "结束时间": "结束时间",
    "是否需要手动修改执行状态": "是否需要手动修改执行状态(1是0否)",
}

SEMANTIC_GROUPS = {
    "医保": ["医保", "医疗保险", "基本医疗保险", "职工医保", "居民医保"],
    "报销": ["报销", "支付比例", "待遇", "补助", "起付", "限额"],
    "门诊": ["门诊", "门诊统筹", "慢特病", "门诊慢特病"],
    "住院": ["住院", "入院", "出院"],
    "商业补充保险": ["商业补充保险", "补充保险", "商保"],
}


def normalize_header(value: Any) -> str:
    text = re.sub(r"\s+", "", clean_text(value).replace("：", "").replace(":", ""))
    if text in TARGET_COLUMNS:
        return text
    for alias, target in HEADER_ALIASES.items():
        if alias in text:
            return target
    return clean_text(value)


def blank_record(columns: Sequence[str]) -> Dict[str, str]:
    return {column: "" for column in columns}


def keyword_terms(keyword: str) -> List[str]:
    parts = [part for part in re.split(r"[\s,，、]+", keyword.strip()) if part]
    terms = set(parts)
    for part in parts:
        for key, synonyms in SEMANTIC_GROUPS.items():
            if part == key or part in synonyms:
                terms.update(synonyms)
    return list(terms)


def is_relevant(text: str, keyword: str) -> bool:
    if not keyword.strip():
        return True
    haystack = clean_text(text)
    return any(term in haystack for term in keyword_terms(keyword))


def html_to_text(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def db_base_fields(record: Dict[str, Any], columns: Sequence[str]) -> Dict[str, str]:
    base = blank_record(columns)
    base["info_id"] = clean_text(record.get("info_id"))
    base["文章时间"] = normalize_date(record.get("article_time"))
    base["审核日期"] = normalize_date(record.get("audit_time"))
    base["地区名称"] = clean_text(record.get("region"))
    base["相关资讯"] = clean_text(record.get("related_info"))
    if clean_text(record.get("raw", {}).get("insurancetypename")):
        base["保险类型"] = clean_text(record.get("raw", {}).get("insurancetypename"))
    return base


def table_records(html: str, base: Dict[str, str], columns: Sequence[str]) -> List[Dict[str, str]]:
    if not html.strip():
        return []
    records: List[Dict[str, str]] = []
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        tables = []
    for table in tables:
        table.columns = [normalize_header(column) for column in table.columns]
        mapped_columns = [column for column in table.columns if column in columns]
        if not mapped_columns:
            continue
        for _, row in table.iterrows():
            item = dict(base)
            for column in mapped_columns:
                value = clean_text(row.get(column))
                if value:
                    item[column] = value
            records.append(normalize_record(item, columns))
    return records


def key_value_fields(text: str, columns: Sequence[str]) -> Dict[str, str]:
    found = blank_record(columns)
    compact = clean_text(text)
    for raw_key, target in HEADER_ALIASES.items():
        if target not in columns:
            continue
        pattern = rf"{re.escape(raw_key)}\s*[:：]\s*([^:：；;，,\n\r]+)"
        match = re.search(pattern, compact)
        if match:
            found[target] = clean_text(match.group(1))
    for target in columns:
        pattern = rf"{re.escape(target)}\s*[:：]\s*([^:：；;，,\n\r]+)"
        match = re.search(pattern, compact)
        if match:
            found[target] = clean_text(match.group(1))
    return found


def infer_fields(text: str, columns: Sequence[str]) -> Dict[str, str]:
    record = blank_record(columns)
    if "职工" in text:
        record["保险类型"] = "职工医保"
    elif "居民" in text:
        record["保险类型"] = "居民医保"
    if "门诊" in text:
        record["类型"] = record["类型"] or "门诊"
    elif "住院" in text:
        record["类型"] = record["类型"] or "住院"
    date_match = re.search(r"(?:发布时间|发布日期|文章时间)\s*[:：]?\s*(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2})", text)
    if date_match:
        record["文章时间"] = normalize_date(date_match.group(1))
    audit_match = re.search(r"(?:审核日期|审核时间)\s*[:：]?\s*(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2})", text)
    if audit_match:
        record["审核日期"] = normalize_date(audit_match.group(1))
    return record


def has_business_value(record: Dict[str, str]) -> bool:
    ignored = {"文章时间", "审核日期", "info_id", "地区名称", "相关资讯", "审核状态0待审核1已审核", "是否需要手动修改执行状态(1是0否)"}
    return any(clean_text(value) for key, value in record.items() if key not in ignored)


def merge_records(base: Dict[str, str], extracted: Dict[str, str], columns: Sequence[str]) -> Dict[str, str]:
    merged = blank_record(columns)
    for column in columns:
        merged[column] = clean_text(base.get(column)) or clean_text(extracted.get(column))
    return normalize_record(merged, columns)


def extract_record(record: Dict[str, Any], columns: Sequence[str] | None = None, keyword: str = "") -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    columns = list(columns or TARGET_COLUMNS)
    html = clean_text(record.get("html"))
    text = clean_text(record.get("text"))
    content = html_to_text(html) if html else text
    combined_text = " ".join([clean_text(record.get("title")), content, text])
    log = {
        "source_id": clean_text(record.get("source_id")),
        "info_id": clean_text(record.get("info_id")),
        "title": clean_text(record.get("title")),
        "status": "success",
        "message": "",
        "records": 0,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not combined_text.strip():
        log.update({"status": "empty_content", "message": "html and text are empty"})
        return [], log
    if not is_relevant(combined_text, keyword):
        log.update({"status": "skipped_keyword", "message": "keyword not matched"})
        return [], log

    base = db_base_fields(record, columns)
    extracted_records = table_records(html, base, columns)
    if not extracted_records:
        extracted = key_value_fields(combined_text, columns)
        inferred = infer_fields(combined_text, columns)
        extracted_records = [merge_records(base, {**inferred, **{k: v for k, v in extracted.items() if v}}, columns)]

    final_records = [merge_records(base, item, columns) for item in extracted_records]
    final_records = [item for item in final_records if has_business_value(item)]
    if not final_records:
        final_records = [normalize_record(base, columns)]
    log["records"] = len(final_records)
    return final_records, log
