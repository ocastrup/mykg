"""Fork-local CLI subcommands.

This module owns the CLI commands the fork adds on top of upstream mykg:
``watch``. It lives here — instead of inline in ``cli.py`` — so upstream syncs
stop colliding on that heavily-churned file. ``cli.py`` wires it in with a
single ``register(cli)`` call.

The command is defined as a standalone ``click`` command and attached to the
main group by :func:`register`.
"""

from __future__ import annotations

import click


@click.command("watch")
@click.option(
    "--once",
    is_flag=True,
    help="Run a single scan/enqueue cycle and exit (skips debounce; good for cron/tests).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG-level logging")
def watch(once, verbose):
    """Watch configured folders and enqueue extract-graph --append requests."""
    from mykg.logging import setup
    from mykg.watcher import run_daemon

    setup(verbose=verbose)
    run_daemon(once=once)


#: Fork-added commands, in registration order.
FORK_COMMANDS = (watch,)


def register(cli) -> None:
    """Attach every fork command to the main ``cli`` group."""
    for command in FORK_COMMANDS:
        cli.add_command(command)

