"""Test-wide safety: point the app at a throwaway SQLite file, so no test ever writes backend/app.db.

Tests that need their own database still override HOLIDAY_DB_PATH per test with monkeypatch.
"""

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_database(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setenv("HOLIDAY_DB_PATH", str(tmp_path_factory.mktemp("db") / "session.db"))
    yield
    patch.undo()
