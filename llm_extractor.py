import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

import yaml
from bs4 import BeautifulSoup

from cleaner import clean_text, normalize_record
from columns import TARGET_COLUMNS


DEFAULT_SYSTEM_PROMPT = "你是医保、商保、政策待遇文本结构化抽取助手。请严格输出 JSON。"
DEFAULT_USER_PROMPT = "请从下面这条数据库文章记录中抽取固定 26 列 Excel 数据。请严格返回 JSON。"
EVIDENCE_FIELDS = {"报销比例", "起付标准", "补助限额", "区间", "人员类型", "医院类型", "就诊地域", "就诊情况"}
DB_PRIORITY_FIELDS = {"info_id", "文章时间", "审核日期", "地区名称", "相关资讯"}


def html_to_text(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = True
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout_seconds: int = 60
    max_retries: int = 2
    temperature: float = 0
    max_input_chars: int = 20000
    fallback_to_rules_on_error: bool = True
    write_evidence_sheet: bool = True
    system_prompt_path: str = "prompts/extraction_system_prompt.txt"
    user_prompt_path: str = "prompts/extraction_user_prompt.txt"


@dataclass
class LLMParseResult:
    success: bool
    records: List[Dict[str, str]] = field(default_factory=list)
    evidence: Dict[str, str] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    need_manual_review: bool = False
    review_reason: str = ""
    raw: str = ""
    error: str = ""


@dataclass
class LLMCallResult(LLMParseResult):
    used: bool = False
    model: str = ""
    input_chars: int = 0


def load_llm_config(path: str | Path = "config/llm_config.yml") -> LLMConfig:
    config_path = Path(path)
    data: Dict[str, Any] = {}
    if config_path.exists():
        data = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("llm") or {}
    return LLMConfig(
        enabled=bool(data.get("enabled", True)),
        provider=str(data.get("provider", "deepseek")),
        base_url=str(data.get("base_url", "https://api.deepseek.com")),
        model=str(data.get("model", "deepseek-v4-flash")),
        timeout_seconds=int(data.get("timeout_seconds", 60)),
        max_retries=int(data.get("max_retries", 2)),
        temperature=float(data.get("temperature", 0)),
        max_input_chars=int(data.get("max_input_chars", 20000)),
        fallback_to_rules_on_error=bool(data.get("fallback_to_rules_on_error", True)),
        write_evidence_sheet=bool(data.get("write_evidence_sheet", True)),
        system_prompt_path=str(data.get("system_prompt_path", "prompts/extraction_system_prompt.txt")),
        user_prompt_path=str(data.get("user_prompt_path", "prompts/extraction_user_prompt.txt")),
    )


def deepseek_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def llm_available(config: LLMConfig) -> tuple[bool, str]:
    if not config.enabled:
        return False, "llm.enabled=false"
    if not deepseek_api_key():
        return False, "DEEPSEEK_API_KEY is not configured; using rule extraction"
    return True, ""


def read_prompt(path: str, default: str) -> str:
    prompt_path = Path(path)
    return prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else default


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    else:
        return json.dumps(value, ensure_ascii=False)
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return text


def parse_llm_response(value: Any, columns: Sequence[str] | None = None) -> LLMParseResult:
    columns = list(columns or TARGET_COLUMNS)
    raw = _json_text(value)
    try:
        data = json.loads(raw)
    except Exception as exc:
        return LLMParseResult(success=False, raw=raw, error=f"Invalid JSON response: {exc}")
    if not isinstance(data, dict):
        return LLMParseResult(success=False, raw=raw, error="Invalid JSON response: root must be object")

    raw_records = data.get("records", [])
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        return LLMParseResult(success=False, raw=raw, error="Invalid JSON response: records must be list")

    records = []
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        records.append(normalize_record({column: item.get(column, "") for column in columns}, columns))

    evidence = {
        str(field): clean_text(text)
        for field, text in (data.get("evidence") or {}).items()
        if field in columns and clean_text(text)
    }
    confidence: Dict[str, float] = {}
    for field, score in (data.get("confidence") or {}).items():
        if field not in columns:
            continue
        try:
            confidence[field] = max(0.0, min(float(score), 1.0))
        except (TypeError, ValueError):
            continue
    return LLMParseResult(
        success=True,
        records=records,
        evidence=evidence,
        confidence=confidence,
        need_manual_review=bool(data.get("need_manual_review", False)),
        review_reason=clean_text(data.get("review_reason")),
        raw=raw,
    )


def output_schema(columns: Sequence[str] | None = None) -> Dict[str, Any]:
    columns = list(columns or TARGET_COLUMNS)
    return {
        "records": [{column: "0" if column in {"审核状态0待审核1已审核", "是否需要手动修改执行状态(1是0否)"} else "" for column in columns}],
        "evidence": {field: "原文证据片段" for field in sorted(EVIDENCE_FIELDS)},
        "confidence": {field: 0.0 for field in sorted(EVIDENCE_FIELDS)},
        "need_manual_review": False,
        "review_reason": "",
    }


def compact_text(record: Dict[str, Any], max_chars: int) -> str:
    title = clean_text(record.get("title"))
    text = clean_text(record.get("text"))
    html_text = html_to_text(clean_text(record.get("html")))
    combined = "\n".join(part for part in [title, text, html_text] if part)
    if len(combined) <= max_chars:
        return combined
    keywords = ["报销", "起付", "限额", "门诊", "住院", "个人账户", "病种", "医院", "待遇", "补助"]
    paragraphs = re.split(r"[\r\n。；;]+", combined)
    selected = [title] if title else []
    selected.extend(paragraph for paragraph in paragraphs if any(keyword in paragraph for keyword in keywords))
    compact = "\n".join(dict.fromkeys(clean_text(item) for item in selected if clean_text(item)))
    if len(compact) < max_chars // 3:
        compact = combined[:max_chars]
    return compact[:max_chars]


def record_payload(record: Dict[str, Any], config: LLMConfig) -> Dict[str, Any]:
    return {
        "source_id": clean_text(record.get("source_id")),
        "info_id": clean_text(record.get("info_id")),
        "title": clean_text(record.get("title")),
        "article_time": clean_text(record.get("article_time")),
        "audit_time": clean_text(record.get("audit_time")),
        "region": clean_text(record.get("region")),
        "related_info": clean_text(record.get("related_info")),
        "direct_fields": record.get("direct_fields") or {},
        "text": compact_text(record, config.max_input_chars),
        "html_text": html_to_text(clean_text(record.get("html")))[: config.max_input_chars],
    }


def render_user_prompt(template: str, record: Dict[str, Any], columns: Sequence[str], config: LLMConfig) -> tuple[str, int]:
    payload = record_payload(record, config)
    record_json = json.dumps(payload, ensure_ascii=False, indent=2)
    columns_json = json.dumps(list(columns), ensure_ascii=False, indent=2)
    schema_json = json.dumps(output_schema(columns), ensure_ascii=False, indent=2)
    prompt = (
        template.replace("{{record_json}}", record_json)
        .replace("{{target_columns_json}}", columns_json)
        .replace("{{schema_json}}", schema_json)
    )
    return prompt, len(record_json)


def call_llm(record: Dict[str, Any], columns: Sequence[str], config: LLMConfig) -> LLMCallResult:
    available, reason = llm_available(config)
    if not available:
        return LLMCallResult(success=False, used=False, model=config.model, error=reason)
    system_prompt = read_prompt(config.system_prompt_path, DEFAULT_SYSTEM_PROMPT)
    user_template = read_prompt(config.user_prompt_path, DEFAULT_USER_PROMPT)
    user_prompt, input_chars = render_user_prompt(user_template, record, columns, config)
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=deepseek_api_key(),
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=config.temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        parsed = parse_llm_response(content, columns)
        return LLMCallResult(
            **parsed.__dict__,
            used=True,
            model=config.model,
            input_chars=input_chars,
        )
    except Exception as exc:
        return LLMCallResult(
            success=False,
            used=True,
            model=config.model,
            input_chars=input_chars,
            error=f"LLM request failed: {exc}",
        )


def evidence_rows(
    source_id: str,
    info_id: str,
    records: Sequence[Dict[str, str]],
    evidence: Dict[str, str],
    confidence: Dict[str, float],
    source: str,
    rule_name: str,
) -> List[Dict[str, Any]]:
    rows = []
    for field_name, evidence_text in evidence.items():
        for record in records or [{}]:
            rows.append(
                {
                    "source_id": source_id,
                    "info_id": info_id,
                    "field": field_name,
                    "value": record.get(field_name, ""),
                    "evidence": evidence_text,
                    "confidence": confidence.get(field_name, ""),
                    "source": source,
                    "rule_name": rule_name,
                }
            )
    return rows
