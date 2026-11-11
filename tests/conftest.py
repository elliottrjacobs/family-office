import pytest


@pytest.fixture(autouse=True)
def credentials_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FO_CREDENTIALS_HOME", str(tmp_path / "credentials"))
