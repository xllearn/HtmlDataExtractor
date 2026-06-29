from columns import TARGET_COLUMNS
from table_extractor import extract_text_tables


def test_text_catalog_table_generates_one_record_per_row():
    text = """
    序号 药品名称 剂型 类别
    1 药品A 注射剂 甲类
    2 药品B 口服常释剂型 乙类
    """
    records = extract_text_tables(text, {"info_id": "A-1"}, TARGET_COLUMNS).records

    assert len(records) == 2
    assert records[0]["病种名称"] == "药品A"
    assert records[0]["类型"] == "注射剂"
    assert records[0]["标化类型"] == "甲类"
    assert records[1]["病种名称"] == "药品B"
    assert records[1]["标化类型"] == "乙类"


def test_text_benefit_table_without_sequence_header_generates_rows():
    text = """
    “两病”门诊用药保障报销标准
    病种名称 支付限额 报销比例
    1 糖尿病 800元 70%
    2 高血压 400元 70%
    3 同时合并高血压糖尿病 1200元 70%
    """
    records = extract_text_tables(text, {"info_id": "LN-1"}, TARGET_COLUMNS).records

    assert len(records) == 3
    assert records[0]["病种名称"] == "糖尿病"
    assert records[0]["补助限额"] == "800元"
    assert records[0]["报销比例"] == "70%"
    assert records[2]["病种名称"] == "同时合并高血压糖尿病"
