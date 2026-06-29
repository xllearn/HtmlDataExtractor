# Database Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework HtmlDataExtractor so the primary workflow reads article content from a configured database table and writes fixed 26-column Excel output.

**Architecture:** Add focused modules for database reading, extraction, cleaning, Excel writing, and orchestration. Keep credentials out of tracked files by expanding environment variables in YAML and using ignored local config for live validation.

**Tech Stack:** Python 3, SQLAlchemy, PyMySQL, PyYAML, BeautifulSoup, pandas/openpyxl, FastAPI.

---

### Task 1: Configuration And Database Reader

**Files:**
- Create: `db_reader.py`
- Create: `config/db_config.yml`
- Test: `test_db_pipeline.py`

- [ ] Write tests for YAML loading, environment-variable expansion, dynamic column selection, and standard record conversion.
- [ ] Implement `DatabaseConfig`, `load_db_config`, and `read_records`.
- [ ] Verify tests fail before implementation and pass after implementation.

### Task 2: Fixed Columns, Extraction, And Cleaning

**Files:**
- Create: `columns.py`
- Create: `cleaner.py`
- Create: `extractor.py`
- Create: `config/field_mapping.yml`
- Test: `test_db_pipeline.py`

- [ ] Write tests for fixed 26-column ordering, field-level missing values, keyword skipping, DB field precedence, deduplication, and article-time sorting.
- [ ] Implement extraction from HTML tables, key-value text, and paragraph text.
- [ ] Implement cleaning, missing-value filling, dedupe, and sorting.

### Task 3: Excel Writer And Pipeline

**Files:**
- Create: `excel_writer.py`
- Create: `main.py`
- Create: `examples/sample_db_record.json`
- Create: `examples/sample_result.json`
- Test: `test_db_pipeline.py`

- [ ] Write tests for workbook sheets, exact output columns, log sheet, and sample pipeline.
- [ ] Implement `write_excel` and `run_pipeline`.
- [ ] Ensure one bad record is logged and does not stop the whole run.

### Task 4: Web Demo And Documentation

**Files:**
- Modify: `app.py`
- Replace: `static/index.html`
- Modify: `requirements.txt`
- Modify: `README.md`
- Test: `test_db_pipeline.py`

- [ ] Write API tests for sample loading and database-task request shape.
- [ ] Update the UI to database extraction mode.
- [ ] Remove Playwright from dependencies and document database-only usage.

### Task 5: Verification

- [ ] Run `py -3 -m pytest -q`.
- [ ] Run `py -3 -m py_compile app.py main.py db_reader.py extractor.py cleaner.py excel_writer.py columns.py`.
- [ ] Run a live database smoke test with ignored local config and no credentials in tracked files.
