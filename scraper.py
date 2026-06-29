import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import pandas as pd
from bs4 import BeautifulSoup


TARGET_COLUMNS = [
    "文章时间",
    "审核日期",
    "info_id",
    "地区名称",
    "个人账户计入办法",
    "个人账户使用范围",
    "病种名称",
    "类型",
    "标化类型",
    "保险类型",
    "人员类型",
    "病种类型",
    "就诊地域",
    "医院类型",
    "就诊情况",
    "区间",
    "起付标准",
    "补助限额",
    "报销比例",
    "备注",
    "相关资讯",
    "审核状态0待审核1已审核",
    "执行状态",
    "开始执行时间",
    "结束时间",
    "是否需要手动修改执行状态(1是0否)",
]

DATE_COLUMNS = ["文章时间", "审核日期", "开始执行时间", "结束时间"]

HEADER_ALIASES = {
    "发布时间": "文章时间",
    "发文时间": "文章时间",
    "发布日期": "文章时间",
    "文章日期": "文章时间",
    "时间": "文章时间",
    "审核时间": "审核日期",
    "审核日期": "审核日期",
    "地区": "地区名称",
    "统筹地区": "地区名称",
    "城市": "地区名称",
    "个人账户计入": "个人账户计入办法",
    "个人账户计入办法": "个人账户计入办法",
    "账户计入办法": "个人账户计入办法",
    "个人账户使用": "个人账户使用范围",
    "个人账户使用范围": "个人账户使用范围",
    "使用范围": "个人账户使用范围",
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
    "参保人员": "人员类型",
    "病种类型": "病种类型",
    "就诊地": "就诊地域",
    "就诊地域": "就诊地域",
    "医疗机构级别": "医院类型",
    "医院级别": "医院类型",
    "医院类型": "医院类型",
    "就诊情况": "就诊情况",
    "住院次数": "就诊情况",
    "费用区间": "区间",
    "区间": "区间",
    "起付线": "起付标准",
    "起付标准": "起付标准",
    "起付": "起付标准",
    "封顶线": "补助限额",
    "支付限额": "补助限额",
    "年度限额": "补助限额",
    "补助限额": "补助限额",
    "报销比例": "报销比例",
    "支付比例": "报销比例",
    "比例": "报销比例",
    "备注": "备注",
    "说明": "备注",
    "相关资讯": "相关资讯",
    "审核状态": "审核状态0待审核1已审核",
    "执行状态": "执行状态",
    "开始执行时间": "开始执行时间",
    "结束时间": "结束时间",
    "结束执行时间": "结束时间",
    "是否需要手动修改执行状态": "是否需要手动修改执行状态(1是0否)",
}

SEMANTIC_GROUPS = {
    "医保": ["医保", "医疗保险", "基本医疗保险", "职工医保", "居民医保"],
    "报销": ["报销", "支付比例", "待遇", "补助", "起付", "限额"],
    "门诊": ["门诊", "门诊统筹", "慢特病", "门诊慢特病"],
    "住院": ["住院", "入院", "出院"],
    "个人账户": ["个人账户", "共济", "账户计入", "账户使用"],
    "西安": ["西安", "陕西省-西安市", "陕西西安"],
}


@dataclass
class PageDocument:
    source: str
    html: str
    text: str
    title: str


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def normalize_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"(20\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", text)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m}-{d}"
    return text


def normalize_header(header: Any) -> str:
    text = re.sub(r"\s+", "", clean_text(header).replace("（", "(").replace("）", ")"))
    if text in TARGET_COLUMNS:
        return text
    for alias, target in HEADER_ALIASES.items():
        if alias in text:
            return target
    return clean_text(header)


def blank_record() -> Dict[str, str]:
    return {column: "" for column in TARGET_COLUMNS}


def parse_info_id(source: str, text: str = "") -> str:
    parsed = urlparse(source)
    query = parse_qs(parsed.query)
    if "articleId" in query and query["articleId"]:
        return query["articleId"][0]
    match = re.search(r"articleId=([0-9a-fA-F-]{16,})", source)
    if match:
        return match.group(1)
    match = re.search(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", text)
    return match.group(0) if match else ""


def infer_region(text: str) -> str:
    candidates = [
        ("陕西省-西安市", ["陕西", "西安"]),
        ("陕西省", ["陕西"]),
        ("西安市", ["西安"]),
    ]
    for region, terms in candidates:
        if all(term in text for term in terms):
            return region
    match = re.search(r"([\u4e00-\u9fa5]{2,9}省)?([\u4e00-\u9fa5]{2,9}市)", text)
    if match:
        province = match.group(1) or ""
        city = match.group(2)
        return f"{province}-{city}" if province else city
    return ""


def extract_first_date(text: str) -> str:
    patterns = [
        r"(?:发布时间|发布日期|发文时间|文章时间)[:：]?\s*(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2})",
        r"(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2})",
        r"(20\d{6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_date(match.group(1))
    return ""


def extract_audit_date(text: str) -> str:
    match = re.search(r"(?:审核日期|审核时间)[:：]?\s*(20\d{2}[年/\-.]\d{1,2}[月/\-.]\d{1,2}|20\d{6})", text)
    return normalize_date(match.group(1)) if match else ""


def extract_section(text: str, starts: Sequence[str], stops: Sequence[str], limit: int = 520) -> str:
    start_positions = [text.find(start) for start in starts if text.find(start) >= 0]
    if not start_positions:
        return ""
    start = min(start_positions)
    end = len(text)
    for stop in stops:
        pos = text.find(stop, start + 5)
        if pos >= 0:
            end = min(end, pos)
    section = text[start:end]
    section = re.sub(r"\s+", " ", section).strip(" ：:;；")
    return section[:limit]


def page_level_fields(document: PageDocument) -> Dict[str, str]:
    text = document.text
    record = blank_record()
    record["文章时间"] = extract_first_date(text)
    record["审核日期"] = extract_audit_date(text)
    record["info_id"] = parse_info_id(document.source, text)
    record["地区名称"] = infer_region(text)
    record["个人账户计入办法"] = extract_section(
        text,
        ["个人账户计入办法", "个人账户由", "在职职工个人账户", "退休人员个人账户"],
        ["个人账户使用范围", "个人账户主要用于", "门诊", "住院", "病种", "待遇"],
    )
    record["个人账户使用范围"] = extract_section(
        text,
        ["个人账户使用范围", "个人账户主要用于", "个人账户不得用于"],
        ["病种", "门诊", "住院", "起付", "报销"],
    )
    if "职工" in text:
        record["保险类型"] = "城镇职工"
    elif "居民" in text:
        record["保险类型"] = "城乡居民"
    if "已审核" in text:
        record["审核状态0待审核1已审核"] = "1"
    elif "待审核" in text:
        record["审核状态0待审核1已审核"] = "0"
    if "执行中" in text:
        record["执行状态"] = "执行中"
    record["是否需要手动修改执行状态(1是0否)"] = "0"
    return record


def keyword_terms(keyword: str) -> List[str]:
    parts = [part for part in re.split(r"[\s,，;；]+", keyword.strip()) if part]
    terms = set(parts)
    for part in parts:
        for key, synonyms in SEMANTIC_GROUPS.items():
            if part in key or key in part or part in synonyms:
                terms.update(synonyms)
    return sorted(terms, key=len, reverse=True)


def is_relevant(text: str, keyword: str) -> bool:
    if not keyword.strip():
        return True
    terms = keyword_terms(keyword)
    return any(term and term in text for term in terms)


def table_records(html: str, base: Dict[str, str]) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    try:
        tables = pd.read_html(html)
    except Exception:
        return records

    for table in tables:
        if table.empty:
            continue
        table = table.copy()
        table.columns = [normalize_header(column) for column in table.columns]
        valid_columns = [column for column in table.columns if column in TARGET_COLUMNS]

        if len(valid_columns) >= 2:
            for _, row in table.iterrows():
                record = dict(base)
                for column in valid_columns:
                    record[column] = clean_text(row[column])
                if has_business_value(record):
                    records.append(record)
            continue

        if table.shape[1] >= 2:
            record = dict(base)
            for _, row in table.iterrows():
                key = normalize_header(row.iloc[0])
                if key in TARGET_COLUMNS:
                    record[key] = clean_text(row.iloc[1])
            if has_business_value(record):
                records.append(record)

    return records


def key_value_records(soup: BeautifulSoup, base: Dict[str, str]) -> List[Dict[str, str]]:
    record = dict(base)
    text_blocks = []
    for element in soup.select("p, li, div, span"):
        text = clean_text(element.get_text(" ", strip=True))
        if 3 <= len(text) <= 800:
            text_blocks.append(text)
    for block in text_blocks:
        for raw_key, target in HEADER_ALIASES.items():
            if raw_key in block and target in TARGET_COLUMNS:
                pattern = rf"{re.escape(raw_key)}\s*[:：]\s*(.+)"
                match = re.search(pattern, block)
                if match and not record[target]:
                    record[target] = clean_text(match.group(1))[:500]
    return [record] if has_business_value(record) else []


def has_business_value(record: Dict[str, str]) -> bool:
    business_columns = [c for c in TARGET_COLUMNS if c not in {"info_id", "审核状态0待审核1已审核", "是否需要手动修改执行状态(1是0否)"}]
    return any(clean_text(record.get(column)) for column in business_columns)


def html_to_document(source: str, html: str) -> PageDocument:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    text = clean_text(soup.get_text(" ", strip=True))
    return PageDocument(source=source, html=html, text=text, title=title)


def extract_from_html(source: str, html: str, keyword: str = "") -> List[Dict[str, str]]:
    document = html_to_document(source, html)
    if not is_relevant(document.text, keyword):
        return []
    soup = BeautifulSoup(html, "html.parser")
    base = page_level_fields(document)
    records = table_records(html, base)
    records.extend(key_value_records(soup, base))
    if not records and has_business_value(base):
        records = [base]
    return [normalize_record(record) for record in records]


def normalize_record(record: Dict[str, Any]) -> Dict[str, str]:
    normalized = blank_record()
    for column in TARGET_COLUMNS:
        normalized[column] = clean_text(record.get(column, ""))
    for column in DATE_COLUMNS:
        normalized[column] = normalize_date(normalized[column])
    if not normalized["审核状态0待审核1已审核"]:
        normalized["审核状态0待审核1已审核"] = "1"
    if not normalized["是否需要手动修改执行状态(1是0否)"]:
        normalized["是否需要手动修改执行状态(1是0否)"] = "0"
    return normalized


def fetch_with_playwright(url: str, timeout_ms: int = 45000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(1200)
        html = page.content()
        browser.close()
        return html


def fetch_with_urllib(url: str, timeout: int = 25) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 HtmlDataExtractor/1.0"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def read_source(source: str, use_browser: bool = True) -> Tuple[str, str]:
    path = Path(source)
    if path.exists():
        return source, path.read_text(encoding="utf-8", errors="replace")
    if source.startswith("file://"):
        file_path = Path(urlparse(source).path)
        return source, file_path.read_text(encoding="utf-8", errors="replace")
    if source.startswith(("http://", "https://")):
        if use_browser:
            try:
                return source, fetch_with_playwright(source)
            except Exception as exc:
                print(f"[WARN] Playwright 获取失败，改用普通 HTTP: {exc}")
        return source, fetch_with_urllib(source)
    raise FileNotFoundError(f"无法识别输入来源: {source}")


def save_evidence(source: str, html: str, evidence_dir: str = "evidence") -> str:
    Path(evidence_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    digest = hashlib.md5(source.encode("utf-8")).hexdigest()[:10]
    path = Path(evidence_dir) / f"{stamp}_{digest}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def record_key(record: Dict[str, str]) -> str:
    important = [
        "info_id",
        "地区名称",
        "病种名称",
        "类型",
        "保险类型",
        "人员类型",
        "医院类型",
        "就诊情况",
        "区间",
        "起付标准",
        "补助限额",
        "报销比例",
    ]
    raw = "|".join(clean_text(record.get(column)) for column in important)
    if raw.strip("|"):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    all_values = "|".join(clean_text(record.get(column)) for column in TARGET_COLUMNS)
    return hashlib.sha256(all_values.encode("utf-8")).hexdigest()


def clean_deduplicate_sort(records: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    normalized = [normalize_record(record) for record in records]
    seen: Dict[str, Dict[str, str]] = {}
    for record in normalized:
        if has_business_value(record):
            seen[record_key(record)] = record
    df = pd.DataFrame(list(seen.values()), columns=TARGET_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=TARGET_COLUMNS)
    for column in DATE_COLUMNS:
        df[column] = df[column].map(normalize_date)
    df["_sort_time"] = pd.to_datetime(df["文章时间"], errors="coerce")
    df = df.sort_values("_sort_time", ascending=True, na_position="first").drop(columns=["_sort_time"])
    return df[TARGET_COLUMNS]


def load_existing_excel(path: str) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=TARGET_COLUMNS)
    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception:
        return pd.DataFrame(columns=TARGET_COLUMNS)
    for column in TARGET_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[TARGET_COLUMNS]


def save_excel(records: Iterable[Dict[str, Any]], output: str, logs: Optional[List[Dict[str, Any]]] = None, append: bool = True) -> str:
    new_df = clean_deduplicate_sort(records)
    if append:
        old_df = load_existing_excel(output)
        combined = clean_deduplicate_sort(pd.concat([old_df, new_df], ignore_index=True).to_dict("records"))
    else:
        combined = new_df

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="结果数据", index=False)
        if logs is not None:
            pd.DataFrame(logs).to_excel(writer, sheet_name="采集日志", index=False)
    return output


def extract_with_llm(html: str, keyword: str, api_key: str, model: str = "gpt-4o-mini") -> List[Dict[str, str]]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = {
        "role": "user",
        "content": (
            "请从以下医保政策网页 HTML 中抽取结构化数据。"
            "只返回 JSON 数组，数组元素的键必须完全使用这些中文列名："
            f"{TARGET_COLUMNS}。未提及字段填空字符串。"
            f"语义检索关键词：{keyword}\n\nHTML:\n{html[:60000]}"
        ),
    }
    response = client.chat.completions.create(
        model=model,
        messages=[prompt],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    if isinstance(data, dict):
        data = data.get("data") or data.get("records") or data.get("result") or []
    if not isinstance(data, list):
        return []
    return [normalize_record(item) for item in data if isinstance(item, dict)]


def collect_sources(urls: Sequence[str], input_file: str = "", input_dir: str = "", urls_file: str = "") -> List[str]:
    sources = list(urls)
    if input_file:
        sources.append(input_file)
    if input_dir:
        for path in sorted(Path(input_dir).glob("*.html")):
            sources.append(str(path))
    if urls_file:
        for line in Path(urls_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                sources.append(line)
    deduped = []
    seen = set()
    for source in sources:
        if source not in seen:
            deduped.append(source)
            seen.add(source)
    return deduped


def scrape_and_extract(
    sources: Sequence[str],
    keyword: str = "",
    api_key: str = "",
    llm_model: str = "gpt-4o-mini",
    use_browser: bool = True,
    evidence_dir: str = "evidence",
) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    all_records: List[Dict[str, str]] = []
    logs: List[Dict[str, Any]] = []
    for source in sources:
        started = datetime.now().isoformat(timespec="seconds")
        try:
            resolved_source, html = read_source(source, use_browser=use_browser)
            evidence_path = save_evidence(resolved_source, html, evidence_dir=evidence_dir)
            records = extract_from_html(resolved_source, html, keyword=keyword)
            if api_key:
                try:
                    llm_records = extract_with_llm(html, keyword, api_key, model=llm_model)
                    if llm_records:
                        records = llm_records
                except Exception as exc:
                    logs.append({"source": source, "status": "llm_failed", "message": str(exc), "time": started})
            all_records.extend(records)
            logs.append(
                {
                    "source": source,
                    "status": "success",
                    "records": len(records),
                    "evidence": evidence_path,
                    "time": started,
                }
            )
        except Exception as exc:
            logs.append({"source": source, "status": "failed", "message": str(exc), "time": started})
    return all_records, logs


def build_sample_html() -> str:
    return """
    <html><head><title>西安市医保政策示例</title></head><body>
    <h1>西安市职工医保门诊统筹待遇政策</h1>
    <p>发布时间：2026-05-22 审核日期：20260522 地区：陕西省-西安市</p>
    <p>个人账户计入办法：在职职工个人账户由个人缴纳的基本医疗保险费计入，计入标准为本人参保缴费基数的2%。退休人员由统筹基金按100元/月定额划入。</p>
    <p>个人账户使用范围：用于支付参保人员在定点医疗机构或定点零售药店发生的政策范围内自付费用。</p>
    <table>
      <tr><th>类型</th><th>标化类型</th><th>保险类型</th><th>人员类型</th><th>医院类型</th><th>起付标准</th><th>补助限额</th><th>报销比例</th><th>执行状态</th></tr>
      <tr><td>门诊统筹</td><td>门统</td><td>城镇职工</td><td>在职职工</td><td>一级及以下医院</td><td>200元</td><td>2000元</td><td>70%</td><td>执行中</td></tr>
      <tr><td>门诊统筹</td><td>门统</td><td>城镇职工</td><td>退休人员</td><td>一级及以下医院</td><td>200元</td><td>2500元</td><td>75%</td><td>执行中</td></tr>
    </table>
    </body></html>
    """


def write_sample(path: str = "sample_policy.html") -> str:
    Path(path).write_text(build_sample_html(), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="网页自动化采集与 Excel 整理工具")
    parser.add_argument("--url", action="append", default=[], help="目标页面 URL，可重复传入")
    parser.add_argument("--urls-file", default="", help="包含多个 URL/文件路径的文本文件，每行一个")
    parser.add_argument("--input-file", default="", help="本地 HTML 文件路径")
    parser.add_argument("--input-dir", default="", help="本地 HTML 文件夹，批量读取 *.html")
    parser.add_argument("--keyword", default="", help="关键词/语义检索词")
    parser.add_argument("--output", default="output.xlsx", help="输出 Excel 路径")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""), help="可选 OpenAI API Key，用于语义补全")
    parser.add_argument("--llm-model", default="gpt-4o-mini", help="可选大模型名称")
    parser.add_argument("--no-browser", action="store_true", help="不用 Playwright，直接按 HTTP 或本地文件读取")
    parser.add_argument("--no-append", action="store_true", help="不合并旧 Excel，直接覆盖输出")
    parser.add_argument("--make-sample", action="store_true", help="生成示例 HTML 后采集")
    args = parser.parse_args()

    sources = collect_sources(args.url, args.input_file, args.input_dir, args.urls_file)
    if args.make_sample:
        sources.append(write_sample())
        if not args.keyword:
            args.keyword = "西安 医保 门诊 报销"
    if not sources:
        parser.error("请通过 --url、--input-file、--input-dir、--urls-file 或 --make-sample 提供输入")

    started = time.time()
    records, logs = scrape_and_extract(
        sources,
        keyword=args.keyword,
        api_key=args.api_key,
        llm_model=args.llm_model,
        use_browser=not args.no_browser,
    )
    save_excel(records, args.output, logs=logs, append=not args.no_append)
    print(f"[OK] 采集完成：{len(records)} 条原始记录，输出文件：{args.output}，耗时 {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
