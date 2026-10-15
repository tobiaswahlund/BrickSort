"""Shared test setup. The data folder points at an empty temp folder, so no test reads or changes
your own data or downloads anything, and nothing here needs a GPU, torch or MuJoCo."""
import os
import tempfile

os.environ["BRICKSORT_DATA"] = tempfile.mkdtemp(prefix="bricksort_test_data_")

import pytest  # noqa: E402

from bricksort import catalog  # noqa: E402


@pytest.fixture
def no_downloads(monkeypatch):
    """Part relationships come from a Rebrickable download; tests use an empty table instead."""
    monkeypatch.setattr(catalog, "_bases", {})
