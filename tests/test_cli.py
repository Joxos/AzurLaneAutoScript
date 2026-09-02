"""CLI tests (P0): command wiring + argument precedence (flags > deploy.yaml > defaults)."""

import pytest
from typer.testing import CliRunner

from module.cli.app import app
from module.cli.args import DEFAULT_HOST, DEFAULT_PORT, resolve_web_args

runner = CliRunner()

HELP_TREE = [
    ["--help"],
    ["run", "--help"],
    ["run", "headless", "--help"],
    ["run", "web", "--help"],
    ["run", "desktop", "--help"],
    ["build", "--help"],
    ["doctor", "--help"],
]


@pytest.mark.parametrize("argv", HELP_TREE)
def test_help_tree(argv):
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output or "Alas" in result.output or "Run" in result.output


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_run_headless_rejects_multiple_names():
    result = runner.invoke(app, ["run", "headless", "--name", "a", "--name", "b"])
    assert result.exit_code != 0
    assert "单个" in result.output


def test_resolve_web_args_precedence_flags():
    args = resolve_web_args(
        host="1.2.3.4", port=9999, key="k", deploy_host="9.9.9.9", deploy_port=1, deploy_password="d"
    )
    assert (args.host, args.port, args.password) == ("1.2.3.4", 9999, "k")


def test_resolve_web_args_precedence_deploy():
    args = resolve_web_args(deploy_host="9.9.9.9", deploy_port=1, deploy_password="d")
    assert (args.host, args.port, args.password) == ("9.9.9.9", 1, "d")


def test_resolve_web_args_precedence_defaults():
    args = resolve_web_args()
    assert (args.host, args.port) == (DEFAULT_HOST, DEFAULT_PORT)
    assert args.password is None


def test_resolve_web_args_ssl_requires_both():
    assert resolve_web_args(ssl_key="k", ssl_cert="c").ssl is True
    assert resolve_web_args(ssl_key="k").ssl is False
    assert resolve_web_args(ssl_cert="c").ssl is False
