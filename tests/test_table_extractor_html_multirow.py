from columns import TARGET_COLUMNS
from table_extractor import extract_html_tables


def test_html_catalog_table_generates_one_record_per_row():
    html = """
    <table>
      <tr><th>序号</th><th>药品名称</th><th>剂型</th><th>类别</th></tr>
      <tr><td>1</td><td>药品A</td><td>注射剂</td><td>甲类</td></tr>
      <tr><td>2</td><td>药品B</td><td>口服常释剂型</td><td>乙类</td></tr>
    </table>
    """
    records = extract_html_tables(html, {"info_id": "A-1"}, TARGET_COLUMNS).records

    assert len(records) == 2
    assert records[0]["病种名称"] == "药品A"
    assert records[0]["类型"] == "注射剂"
    assert records[0]["标化类型"] == "甲类"
    assert records[1]["病种名称"] == "药品B"
    assert records[1]["标化类型"] == "乙类"
