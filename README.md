# 数据库文章内容自动提取与 Excel 整理工具

本项目只从给定数据库读取文章数据，不再从 URL、本地 HTML、URL 列表或文件夹采集。员工可以先在网页中浏览数据库文章列表，勾选 1 条或多条记录，再执行固定 26 列字段提取并下载 Excel。

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

字段合并优先级为：数据库标准字段、`direct_field_columns`、HTML/正文表格、正文键值对、推断字段、缺失值配置。

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
  --output outputs/result.xlsx
```

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
2. 输入或确认数据库配置文件路径。
3. 点击“加载数据库内容”。
4. 在数据库文章列表中勾选 1 条或多条记录。
5. 可翻页、关键词搜索、全选当前页或清空选择。
6. 点击“开始提取已选择数据”。
7. 进入结果页查看固定 26 列提取结果和采集日志。
8. 下载 Excel。

未选择记录时，页面会提示“请至少选择一条数据”。

## 输出说明

输出 Excel 默认包含：

- `结果数据`：固定 26 列结果。
- `采集日志`：每条数据库记录的处理状态，包括 `success`、`failed`、`skipped_keyword`、`empty_content`。

如果 `template/陕西西安.xlsx` 存在，程序会基于模板写入，保留结果 sheet 的表头、样式、列宽、冻结窗格等格式，并从第二行开始写入数据。模板不存在时会生成普通 Excel。
