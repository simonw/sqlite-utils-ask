import sqlite_utils
from sqlite_utils.cli import cli
from click.testing import CliRunner
import pytest


@pytest.fixture(scope="module")
def vcr_config():
    return {"filter_headers": ["authorization"]}


@pytest.mark.vcr
def test_ask():
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
