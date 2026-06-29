def test_summary_defaults_fill_missing_numeric_fields():
    from main import summary_defaults

    summary = summary_defaults({"read_count": 2, "output_file": "outputs/x/result.xlsx"})

    assert summary["read_count"] == 2
    assert summary["manual_review_count"] == 0
    assert summary["llm_success_count"] == 0
    assert summary["llm_failed_count"] == 0
    assert summary["output_file"] == "outputs/x/result.xlsx"


def test_app_summarize_fills_missing_numeric_fields():
    from app import summarize

    summary = summarize({"read_count": 1})

    assert summary["manual_review_count"] == 0
    assert summary["llm_success_count"] == 0
    assert summary["llm_failed_count"] == 0
