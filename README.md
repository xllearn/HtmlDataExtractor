# 网页自动化采集与整理工具

本项目可以从 URL、本地 HTML 文件或 HTML 文件夹批量抽取医保政策字段，按 `陕西西安.xlsx` 的 26 个业务列导出 Excel。工具支持关键词/语义词过滤、规则抽取、可选大模型补全、去重、按文章时间升序排序，并提供命令行工具和演示网页。

## 架构设计

1. 数据获取层：`scraper.py` 支持本地 HTML、URL、URL 列表文件和目录批量读取。URL 默认使用 Playwright 渲染，适合 `index.html#/policy-info/detail?...` 这类前端路由页面；失败时回退普通 HTTP。
2. 数据抽取层：优先用 BeautifulSoup/Pandas 解析表格和键值段落，映射到目标字段；可选传入 `--api-key` 使用 OpenAI 对复杂页面做语义补全。
3. 数据治理层：统一清洗空值和日期格式，基于 `info_id + 病种/类型/人员/医院/比例` 等关键字段生成去重键，最后按 `文章时间` 从低到高排序。
4. 输出层：主表 `结果数据` 与模板保持相同 26 列；附加 `采集日志` 记录来源、状态和证据 HTML。
5. 可视化层：`app.py + static/index.html` 提供网页演示，支持输入关键词后现场运行脚本、预览结果、下载 Excel。

## 字段

输出列为：文章时间、审核日期、info_id、地区名称、个人账户计入办法、个人账户使用范围、病种名称、类型、标化类型、保险类型、人员类型、病种类型、就诊地域、医院类型、就诊情况、区间、起付标准、补助限额、报销比例、备注、相关资讯、审核状态0待审核1已审核、执行状态、开始执行时间、结束时间、是否需要手动修改执行状态(1是0否)。

## 安装

```powershell
cd C:\HtmlDataExtractor
pip install -r requirements.txt
playwright install chromium
```

如果你的机器上 `python` 命令不可用，请把下面命令中的 `python` 换成实际 Python 路径，例如 `C:\Python311\python.exe`。

## 命令行运行

采集指定 URL 并导出 Excel：

```powershell
python scraper.py --url "http://192.168.34.29:9011/index.html#/policy-info/detail?articleId=2560b609-200b-4b2d-8f01-907cab743158" --keyword "西安 医保 门诊 报销" --output "陕西西安_采集结果.xlsx"
```

批量采集多个 URL：

```powershell
python scraper.py --urls-file urls.txt --keyword "个人账户 报销" --output "批量采集结果.xlsx"
```

采集本地 HTML 文件夹：

```powershell
python scraper.py --input-dir ".\html_pages" --keyword "医保" --output "本地HTML采集结果.xlsx" --no-browser
```

生成并采集内置示例：

```powershell
python scraper.py --make-sample --output "示例结果.xlsx" --no-browser
```

使用大模型补全复杂页面：

```powershell
python scraper.py --url "目标URL" --keyword "慢特病 报销比例" --output "AI补全结果.xlsx" --api-key "sk-你的KEY"
```

## 演示网页运行

启动服务：

```powershell
cd C:\HtmlDataExtractor
uvicorn app:app --host 0.0.0.0 --port 8000
```

浏览器打开：

```text
http://localhost:8000
```

页面操作：

1. 点击“加载示例结果”查看初始化数据示例和对应抽取结果。
2. 输入目标 URL 或本地 HTML 路径，每行一个。
3. 输入关键词，例如 `西安 医保 门诊 报销`。
4. 如果页面是前端渲染页面，保持“使用浏览器渲染 URL”勾选。
5. 点击“开始采集”，完成后点击“下载 Excel”。

## 输出说明

默认会生成：

- `结果数据`：与 `陕西西安.xlsx` 对齐的 26 列业务数据。
- `采集日志`：每个输入来源的采集状态、抽取条数、证据 HTML 路径。
- `evidence/`：每次采集保存的 HTML 证据文件，便于复核。
