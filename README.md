# 数据库文章内容自动提取与 Excel 整理工具

本项目从数据库读取文章正文或 HTML 内容，抽取并整理为固定 26 列 Excel。项目后续不再以 URL、URL 列表、本地 HTML 文件或 HTML 文件夹采集作为核心流程。

## 输出字段

最终 Excel 只包含以下 26 列，字段名和顺序固定：

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

默认配置文件为 `config/db_config.yml`。该文件使用环境变量保存账号密码，避免把敏感信息写入仓库。

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

query:
  where: ""
  limit: 1000
  order_by: "AuditTime ASC"
```

字段不存在时可以把对应配置留空。`where`、`limit`、`order_by` 均可按需调整。

本地运行前设置环境变量：

```powershell
$env:HTMLDATAEXTRACTOR_DB_USER="你的用户名"
$env:HTMLDATAEXTRACTOR_DB_PASSWORD_URLENCODED="URL编码后的密码"
```

如果密码含有 `#`、`@`、`:`、`/` 等 URL 特殊字符，需要先 URL 编码。例如 `#` 写成 `%23`。

也可以创建 `config/db_config.local.yml` 存放真实连接信息；该文件已被 `.gitignore` 忽略。

## 字段缺失值配置

默认字段配置文件为 `config/field_mapping.yml`。

- `output_columns` 必须完整等于固定 26 列。
- `default_missing_value` 是全局默认缺失值。
- `field_missing_values` 可以为每个字段单独配置缺失值，优先级高于全局默认值。
- 空字符串、`None`、`nan`、`null` 都会被视为缺失值。

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

执行完成后会打印读取记录数、成功记录数、失败记录数和输出文件路径。

## 网页演示

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

浏览器打开：

```text
http://localhost:8000
```

页面支持：

- 设置数据库配置文件路径
- 设置字段配置文件路径
- 设置 Excel 模板路径
- 输入关键词/语义搜索词
- 启动数据库提取任务
- 加载模拟数据库记录示例
- 预览固定 26 列结果
- 查看采集日志
- 下载生成的 Excel

## 输出说明

输出 Excel 默认包含：

- `结果数据`：固定 26 列结果。
- `采集日志`：每条数据库记录的处理状态，包括 `success`、`failed`、`skipped_keyword`、`empty_content`。

如果 `template/陕西西安.xlsx` 存在，程序会基于模板写入；否则生成普通 Excel。
