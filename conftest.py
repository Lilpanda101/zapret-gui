import pytest

import healer


@pytest.fixture(autouse=True)
def isolated_healer_log(tmp_path, monkeypatch):
    """Не даём юнит-тестам писать в боевой /tmp/zapret-healer.log."""
    monkeypatch.setattr(healer, "HEALER_LOG", str(tmp_path / "healer.log"))
