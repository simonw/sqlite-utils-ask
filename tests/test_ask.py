import sqlite_utils
from sqlite_utils.cli import cli
from click.testing import CliRunner
import os
import pytest

API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY") or "fake-api"


@pytest.fixture(scope="module")
def vcr_config():
    return {"filter_headers": ["authorization"]}


@pytest.mark.vcr
def test_ask(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", API_KEY)
    with CliRunner().isolated_filesystem():
        db = sqlite_utils.Database("test.db")
        db["dogs"].insert_all(
            [
                {"name": "Cleo"},
                {"name": "Pancakes"},
                {"name": "Jasper"},
            ]
        )
        result = CliRunner().invoke(cli, ["ask", "test.db", "count the dogs"])
        assert result.exit_code == 0
        assert "3" in result.output
        assert "count(*)" in result.output.lower()
