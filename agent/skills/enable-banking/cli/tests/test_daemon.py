"""The finance daemon subcommand delegates to the shared runner, declaring the watcher's
screen session name, which is not the skill name."""

from finance_cli import cli


def test_daemon_lifecycle_args_declare_the_watcher_session():
    args = cli.daemon_lifecycle_args("start")

    assert args[1] == "start"
    assert args[args.index("--session") + 1] == "finance"
    assert "--port-mode" not in args
    assert args[args.index("--") + 1 :] == ["finance-watcher"]
