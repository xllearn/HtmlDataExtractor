# 数据库文章内容自动提取与 Excel 整理工具

本项目只从给定数据库读取文章数据，不再从 URL、本地 HTML、URL 列表或文件夹采集。员工可以先在网页中浏览数据库文章列表，按关键词/同义词扩展搜索并勾选 1 条或多条记录，再执行固定 26 列字段提取并下载 Excel。

URL 只会作为数据库字段中的 `SourceURL` / `info_id` 检索条件或普通文本处理，系统不会直接请求外部网页。

## 固定输出字段

最终 Excel 只包含以下 26 列，字段名和顺序不能改变：

1. 文章时间
2. 审核日期
3. info_id
4. 地区名称
5. 个人账户计入办法
6. 个人账户使用范围
7. 病种名称
8. 类型
9. 标化类型
10. 保险类型
11. 人员类型
12. 病种类型
13. 就诊地域
14. 医院类型
15. 就诊情况
16. 区间
17. 起付标准
18. 补助限额
19. 报销比例
20. 备注
21. 相关资讯
22. 审核状态0待审核1已审核
23. 执行状态
24. 开始执行时间
25. 结束时间
26. 是否需要手动修改执行状态(1是0否)

## 安装

```powershell
cd C:\HtmlDataExtractor
pip install -r requirements.txt
```

## 数据库配置

默认配置文件为 `config/db_config.yml`。仓库中的配置使用环境变量保存账号密码，不提交真实密码。

```yaml
database:
  url: "mysql+pymysql://${HTMLDATAEXTRACTOR_DB_USER}:${HTMLDATAEXTRACTOR_DB_PASSWORD_URLENCODED}@192.168.36.36:3306/wangfanqi_test?charset=utf8mb4"

source:
  table: "temp_商业补充保险_20250523"
  id_column: ""
  info_id_column: "SourceURL"
  title_column: "Title"
  html_column: ""
  text_column: "Content"
  article_time_column: "AuditTime"
  audit_time_column: "AuditTime"
  region_column: "areaname"
  related_info_column: "Source"
```

`selected_ids` 稳定性说明：

- 推荐配置真实唯一主键 `id_column`，用于前端勾选、翻页后保持选择，以及后端按选中记录精确读取。
- 如果 `id_column` 为空，则 `info_id_column` 必须唯一；此时系统会用 `info_id_column` 作为 `source_id`。
- 前端 `selected_ids` 不能使用分页行号，因为分页、搜索或排序变化后行号不稳定。

运行前设置环境变量。密码中的 `#`、`@`、`:`、`/` 等 URL 特殊字符需要 URL 编码，例如 `#` 写成 `%23`。

```powershell
$env:HTMLDATAEXTRACTOR_DB_USER="你的用户名"
$env:HTMLDATAEXTRACTOR_DB_PASSWORD_URLENCODED="URL编码后的密码"
```

也可以创建 `config/db_config.local.yml` 存放真实连接信息；该文件已被 `.gitignore` 忽略。

## 字段配置

默认字段配置文件为 `config/field_mapping.yml`。

- `output_columns` 必须完整等于固定 26 列。
- `default_missing_value` 是全局默认缺失值。
- `field_missing_values` 支持每个字段单独配置缺失值，优先级高于全局默认值。
- 空字符串、`None`、`nan`、`null` 都会被视为缺失值。

`config/db_config.yml` 还支持 `direct_field_columns`，可以把数据库结构化字段直接映射到固定 26 列。例如：

```yaml
direct_field_columns:
  保险类型: "insurancetypename"
```

字段合并优先级为：数据库标准字段、`direct_field_columns`、DeepSeek LLM 结果、HTML/正文表格、正文键值对、推断字段、缺失值配置。

## DeepSeek 大模型配置

系统支持在原有规则抽取后增加 DeepSeek 大模型提取节点，模型输出会经过严格 JSON 解析、固定 26 列字段校验、类型校验和多余字段删除，不会直接裸写 Excel。未配置 API KEY 时会自动使用原有规则提取，不会中断任务。

API KEY 不写入代码或 YAML，只从环境变量读取：

Windows PowerShell:

```powershell
$env:DEEPSEEK_API_KEY="你的key"
```

Linux/macOS:

```bash
export DEEPSEEK_API_KEY="你的key"
```

默认 LLM 配置文件为 `config/llm_config.yml`：

```yaml
llm:
  enabled: true
  provider: deepseek
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
```

如需切换为更强模型，可把 `model` 改为 `deepseek-v4-pro`。提示词位于：

- `prompts/extraction_system_prompt.txt`
- `prompts/extraction_user_prompt.txt`

配置 API KEY 后，流程为“规则提取 + DeepSeek 提取 + 字段校验 + 融合”。数据库标准字段（`info_id`、文章时间、审核日期、地区名称、相关资讯）优先级最高，`direct_field_columns` 高于 LLM，LLM 高于简单推断。规则和 LLM 冲突时会标记 `need_manual_review` 并在日志/证据中保留可追溯信息。

## 命令行运行

```powershell
python main.py --config config/db_config.yml --output outputs/result.xlsx
```

可选参数：

```powershell
python main.py `
  --config config/db_config.yml `
  --field-config config/field_mapping.yml `
  --template template/陕西西安.xlsx `
  --keyword "医保 报销" `
  --output outputs/result.xlsx `
  --use-llm `
  --llm-config config/llm_config.yml
```

LLM 参数：

- `--use-llm`：启用规则 + DeepSeek 大模型融合提取。如果没有 `DEEPSEEK_API_KEY`，会打印提示并自动使用规则提取。
- `--no-llm`：强制禁用大模型，仅使用规则提取。
- `--llm-config config/llm_config.yml`：指定 LLM 配置文件。

命令行默认读取配置范围内的全部记录。网页模式支持员工手动选择要提取的数据库记录。

## 网页演示

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

浏览器打开：

```text
http://localhost:8000
```

网页使用流程：

1. 打开首页。
2. 输入关键词，必要时展开“高级配置”确认配置文件路径。
3. 选择是否启用大模型提取；未配置 `DEEPSEEK_API_KEY` 时会自动使用规则提取。
4. 点击“加载数据库内容”。
5. 在数据库文章列表中勾选 1 条或多条记录。
6. 可翻页、关键词搜索、全选当前页或清空选择。
7. 点击“开始提取已选择数据”。
8. 进入结果页查看固定 26 列提取结果、采集日志、人工复核数和 LLM 调用统计。
9. 下载 Excel。

未选择记录时，页面会提示“请至少选择一条数据”。

Web 任务输出路径固定为 `outputs/{task_id}/result.xlsx`，前端不能指定任意服务器路径。每个任务会写入：

- `outputs/{task_id}/result.xlsx`
- `outputs/{task_id}/task_log.json`
- `outputs/{task_id}/status.json`

## 输出说明

输出 Excel 默认包含：

- `结果数据`：固定 26 列结果。
- `采集日志`：每条数据库记录的处理状态，包括 `success`、`failed`、`skipped_keyword`、`empty_content`，以及 `llm_used`、`llm_success`、`need_manual_review`、`review_reason`。
- `字段证据`：LLM 或规则产生的字段证据，包括 `source_id`、`info_id`、`field`、`value`、`evidence`、`confidence`、`source`、`rule_name`。

如果 `template/陕西西安.xlsx` 存在，程序会基于模板写入，保留结果 sheet 的表头、样式、列宽、冻结窗格等格式，并从第二行开始写入数据。模板不存在时会生成普通 Excel。
