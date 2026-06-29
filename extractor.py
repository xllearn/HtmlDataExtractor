import re
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

from bs4 import BeautifulSoup

from cleaner import clean_text, normalize_date, normalize_record
from columns import BASE_COLUMNS, TARGET_COLUMNS
from llm_extractor import LLMConfig, call_llm, evidence_rows, load_llm_config
from record_fusion import fuse_rule_and_llm_records
from table_extractor import combine_table_results, extract_html_tables, extract_text_tables


HEADER_ALIASES = {
    "发布时间": "文章时间",
    "发布日期": "文章时间",
    "发文时间": "文章时间",
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
    "药品名称": "病种名称",
    "项目名称": "病种名称",
    "待遇类型": "类型",
    "类型": "类型",
    "剂型": "类型",
    "标化类型": "标化类型",
    "类别": "标化类型",
    "保险": "保险类型",
    "险种": "保险类型",
    "保险类型": "保险类型",
    "人员类别": "人员类型",
    "人员类型": "人员类型",
    "病种类型": "病种类型",
    "就诊地域": "就诊地域",
    "医院类型": "医院类型",
    "医院级别": "医院类型",
    "医院等级": "医院类型",
    "就诊情况": "就诊情况",
    "区间": "区间",
    "费用区间": "区间",
    "起付标准": "起付标准",
    "起付线": "起付标准",
    "补助限额": "补助限额",
    "支付限额": "补助限额",
    "年度限额": "补助限额",
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
    "医疗保险": ["医保", "医疗保险", "基本医疗保险", "职工医保", "居民医保"],
    "门诊": ["门诊", "门诊统筹", "慢特病", "门诊慢特病", "两病"],
    "慢特病": ["慢特病", "门诊慢特病", "门诊"],
    "两病": ["两病", "高血压", "糖尿病", "门诊用药"],
    "住院": ["住院", "入院", "出院"],
    "报销": ["报销", "报销比例", "支付比例", "待遇"],
    "补助": ["补助", "补助限额", "限额"],
    "起付": ["起付", "起付标准", "起付线"],
    "限额": ["限额", "补助限额", "支付限额"],
}


def blank_record(columns: Sequence[str]) -> Dict[str, str]:
    return {column: "" for column in columns}


def keyword_terms(keyword: str) -> List[str]:
    parts = [part for part in re.split(r"[\s,，、;；]+", keyword.strip()) if part]
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
    return any(term and term in haystack for term in keyword_terms(keyword))


def html_to_text(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def db_base_fields(record: Dict[str, Any], columns: Sequence[str]) -> Dict[str, str]:
    base = blank_record(columns)
    base["source_id"] = clean_text(record.get("source_id"))
    base["info_id"] = clean_text(record.get("info_id"))
    base["文章时间"] = normalize_date(record.get("article_time"))
    base["审核日期"] = normalize_date(record.get("audit_time"))
    base["地区名称"] = clean_text(record.get("region"))
    base["相关资讯"] = clean_text(record.get("related_info"))
    for column, value in (record.get("direct_fields") or {}).items():
        if column in columns and not clean_text(base.get(column)):
            base[column] = clean_text(value)
    raw = record.get("raw") or {}
    if not clean_text(base.get("保险类型")) and clean_text(raw.get("insurancetypename")):
        base["保险类型"] = clean_text(raw.get("insurancetypename"))
    return base


def key_value_fields(text: str, columns: Sequence[str]) -> Dict[str, str]:
    found = blank_record(columns)
    compact = clean_text(text)
    candidates: List[Tuple[str, str]] = []
    for raw_key, target in HEADER_ALIASES.items():
        if target in columns:
            candidates.append((raw_key, target))
    for target in columns:
        candidates.append((target, target))
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    key_pattern = "|".join(re.escape(key) for key, _ in candidates)
    target_by_key = {key: target for key, target in candidates}
    matches = list(re.finditer(rf"(?P<key>{key_pattern})\s*[:：]", compact))
    for index, match in enumerate(matches):
        target = target_by_key.get(match.group("key"))
        if target not in columns:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compact)
        value = compact[start:end].strip(" \t\r\n,，;；")
        if value:
            found[target] = clean_text(value)
    return found


def infer_fields(text: str, columns: Sequence[str]) -> Dict[str, str]:
    record = blank_record(columns)
    if "城乡居民" in text or "居民医保" in text:
        record["保险类型"] = "城乡居民"
    elif "职工" in text:
        record["保险类型"] = "城镇职工"
    if "两病" in text:
        record["病种类型"] = "两病"
        record["就诊情况"] = record["就诊情况"] or "门诊"
    elif "门诊" in text:
        record["就诊情况"] = "门诊"
    elif "住院" in text:
        record["就诊情况"] = "住院"
    if "高血压" in text and not record["病种名称"]:
        record["病种名称"] = "高血压"
    date_match = re.search(r"(?:发布时间|发布日期|文章时间)\s*[:：]?\s*(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2}|20\d{6})", text)
    if date_match:
        record["文章时间"] = normalize_date(date_match.group(1))
    audit_match = re.search(r"(?:审核日期|审核时间)\s*[:：]?\s*(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2}|20\d{6})", text)
    if audit_match:
        record["审核日期"] = normalize_date(audit_match.group(1))
    return record


def merge_records(base: Dict[str, str], extracted: Dict[str, Any], columns: Sequence[str]) -> Dict[str, str]:
    merged = blank_record(columns)
    for column in columns:
        if column in BASE_COLUMNS and clean_text(base.get(column)):
            merged[column] = clean_text(base.get(column))
        else:
            merged[column] = clean_text(extracted.get(column)) or clean_text(base.get(column))
    return normalize_record(merged, columns)


def has_business_value(record: Dict[str, Any]) -> bool:
    ignored = {"文章时间", "审核日期", "info_id", "地区名称", "相关资讯", "审核状态0待审核1已审核", "是否需要手动修改执行状态(1是0否)"}
    return any(clean_text(value) for key, value in record.items() if key not in ignored and key in TARGET_COLUMNS)


def image_only_review_needed(html: str, text: str) -> bool:
    if clean_text(text):
        return False
    soup = BeautifulSoup(html or "", "lxml")
    return bool(soup.find("img")) and not clean_text(soup.get_text(" ", strip=True))


def extract_record(
    record: Dict[str, Any],
    columns: Sequence[str] | None = None,
    keyword: str = "",
    use_llm: bool | None = None,
    llm_config: LLMConfig | None = None,
    llm_config_path: str = "config/llm_config.yml",
    table_mapping_path: str = "config/table_mapping.yml",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    columns = list(columns or TARGET_COLUMNS)
    html = clean_text(record.get("html"))
    raw_text = "" if record.get("text") is None else str(record.get("text"))
    text = clean_text(raw_text)
    html_text = html_to_text(html) if html else ""
    content = html_text or text
    combined_text = " ".join([clean_text(record.get("title")), content, text])
    source_id = clean_text(record.get("source_id"))
    log: Dict[str, Any] = {
        "source_id": source_id,
        "info_id": clean_text(record.get("info_id")),
        "title": clean_text(record.get("title")),
        "status": "success",
        "message": "",
        "records": 0,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "llm_used": False,
        "llm_model": "",
        "llm_input_chars": 0,
        "llm_success": False,
        "llm_error": "",
        "need_manual_review": False,
        "review_reason": "",
        "table_count": 0,
        "table_row_count": 0,
        "extraction_mode": "",
        "field_evidence": [],
        "conflict_evidence": [],
    }
    if not combined_text.strip() and not html.strip():
        log.update({"status": "empty_content", "message": "html and text are empty", "extraction_mode": "empty_content"})
        return [], log
    if image_only_review_needed(html, text):
        log.update(
            {
                "status": "empty_content",
                "message": "image-only content",
                "need_manual_review": True,
                "review_reason": "疑似图片表格，数据库正文缺少可解析文本，需 OCR 或人工复核",
                "extraction_mode": "empty_content",
            }
        )
        return [], log
    if not is_relevant(combined_text, keyword):
        log.update({"status": "skipped_keyword", "message": "keyword not matched", "extraction_mode": "skipped_keyword"})
        return [], log

    base = db_base_fields(record, columns)
    html_tables = extract_html_tables(html, base, columns, table_mapping_path, source_id)
    text_tables = extract_text_tables(raw_text or html_text, base, columns, table_mapping_path, source_id)
    table_result = combine_table_results(html_tables, text_tables)
    log["table_count"] = table_result.table_count
    log["table_row_count"] = table_result.table_row_count
    log["field_evidence"] = list(table_result.field_evidence)

    if table_result.records:
        rule_records = [merge_records(base, item, columns) for item in table_result.records]
        extraction_mode = table_result.extraction_mode or "table_html"
    else:
        extracted = key_value_fields(combined_text, columns)
        inferred = infer_fields(combined_text, columns)
        merged = merge_records(base, {**inferred, **{k: v for k, v in extracted.items() if v}}, columns)
        rule_records = [merged] if has_business_value(merged) else []
        extraction_mode = "key_value" if rule_records else "empty_content"

    final_records: List[Dict[str, Any]] = [item for item in rule_records if has_business_value(item)]
    should_call_llm = use_llm is not False
    if should_call_llm and len(combined_text) >= 20:
        config = llm_config or load_llm_config(llm_config_path)
        llm_result = call_llm(record, columns, config)
        log["llm_used"] = llm_result.used
        log["llm_model"] = llm_result.model
        log["llm_input_chars"] = llm_result.input_chars
        log["llm_success"] = llm_result.success and llm_result.used
        log["llm_error"] = llm_result.error
        if llm_result.error and not llm_result.used:
            log["message"] = llm_result.error
        if llm_result.success:
            llm_records = [merge_records(base, item, columns) for item in llm_result.records]
            final_records, conflicts = fuse_rule_and_llm_records(base, final_records, llm_records, columns)
            if llm_records:
                extraction_mode = "rule_llm_fusion" if rule_records else "llm_only"
                log["field_evidence"].extend(
                    evidence_rows(source_id, clean_text(record.get("info_id")), final_records, llm_result.evidence, llm_result.confidence, "llm", llm_result.model)
                )
            if conflicts:
                log["conflict_evidence"].extend(conflicts)
            if llm_result.need_manual_review:
                log["need_manual_review"] = True
                log["review_reason"] = llm_result.review_reason
        elif llm_result.used:
            log["need_manual_review"] = True
            log["review_reason"] = llm_result.error or "LLM 调用失败，已回退规则结果"
            if not log["message"]:
                log["message"] = log["review_reason"]
    elif should_call_llm:
        log["message"] = "content too short for LLM; using rule extraction"

    for item in final_records:
        if item.get("need_manual_review"):
            log["need_manual_review"] = True
            reason = clean_text(item.get("review_reason"))
            if reason:
                log["review_reason"] = "；".join(part for part in [clean_text(log.get("review_reason")), reason] if part)
    final_records = [normalize_record(item, columns) for item in final_records if has_business_value(item)]
    if not final_records:
        log["status"] = "empty_content"
        log["message"] = log["message"] or "no extractable business data"
        extraction_mode = "empty_content"
    log["records"] = len(final_records)
    log["extraction_mode"] = extraction_mode
    return final_records, log
