"""Testler gerçek veri kökünü ASLA kullanmaz — her test kendi geçici DB'sini alır."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import config, db


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DB yolunu geçici dizine yönlendirir ve şemayı kurar."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    monkeypatch.setattr(config, "DB_DIR", db_dir)
    monkeypatch.setattr(config, "DB_PATH", db_dir / "test.sqlite3")
    db.init()
    return db_dir
