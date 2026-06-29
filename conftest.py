from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_project_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HTMLDATAEXTRACTOR_ENV_FILE", str(tmp_path / "missing.env.local"))
