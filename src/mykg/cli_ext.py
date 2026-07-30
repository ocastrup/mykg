"""Fork-local CLI subcommands.

This module owns the CLI commands the fork adds on top of upstream mykg:
``watch``, ``build-wiki``, and ``build-topics``. They live here — instead of
inline in ``cli.py`` — so upstream syncs stop colliding on that heavily-churned
file. ``cli.py`` wires them in with a single ``register(cli)`` call.

The commands are defined as standalone ``click`` commands and attached to the
main group by :func:`register`. Helpers that live in ``cli.py`` (e.g.
``_sessions_root``) are imported lazily inside the command bodies to avoid any
import-order coupling between the two modules.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

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


@click.command("build-wiki")
@click.argument("session")
@click.option("--rebuild", is_flag=True, help="Force-regenerate every page (ignore manifest)")
@click.option("--from-step", default=None, help="Resume from a wiki step (wiki_pages, ...)")
@click.option("--log-file", default=None, type=click.Path(path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
def build_wiki(session, rebuild, from_step, log_file, verbose):
    """Render a graph-grounded Obsidian prose vault from a finished session."""
    from mykg.cli import _sessions_root
    from mykg.llm.config import load_adapter
    from mykg.logging import setup
    from mykg.orchestrator import PipelineContext, run
    from mykg.wiki_pipeline import WIKI_STEPS, vault_dir

    session_root = _sessions_root() / session
    if not session_root.is_dir():
        raise click.ClickException(f"Session '{session}' not found at {session_root}.")
    if not (session_root / "output" / "nodes.jsonl").exists():
        raise click.ClickException(
            f"Session '{session}' has no output/nodes.jsonl — run extract-graph first."
        )

    wiki_state = session_root / "wiki"
    wiki_state.mkdir(parents=True, exist_ok=True)
    if log_file is None:
        log_file = session_root / "wiki.log"
    setup(log_file=log_file, verbose=verbose)
    logging.getLogger(__name__).info("Command: %s", " ".join(sys.argv))

    wiki_step_names = [s.name for s in WIKI_STEPS]
    if from_step:
        if from_step not in wiki_step_names:
            raise click.ClickException(
                f"--from-step must be one of {wiki_step_names}, got '{from_step}'."
            )
        start = wiki_step_names.index(from_step)
        for name in wiki_step_names[start:]:
            (wiki_state / f"{name}.done").unlink(missing_ok=True)
        if from_step == "wiki_load":
            (wiki_state / "wiki_graph.json").unlink(missing_ok=True)
    else:
        for name in wiki_step_names:
            (wiki_state / f"{name}.done").unlink(missing_ok=True)
        (wiki_state / "wiki_graph.json").unlink(missing_ok=True)

    adapter = load_adapter(intermediate_dir=wiki_state)
    ctx = PipelineContext(
        input_dir=session_root / "input",
        output_dir=session_root / "output",
        intermediate_dir=wiki_state,
        adapter=adapter,
    )
    if rebuild:
        (vault_dir(ctx) / ".wiki_manifest.json").unlink(missing_ok=True)

    run(WIKI_STEPS, ctx)
    click.echo(f"Wiki written to {vault_dir(ctx)}")


@click.command("build-topics")
@click.argument("session")
@click.option("--rebuild", is_flag=True, help="Force-regenerate every topic page (ignore manifest)")
@click.option("--from-step", default=None, help="Resume from a topics step (topics_cluster, ...)")
@click.option("--log-file", default=None, type=click.Path(path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
def build_topics(session, rebuild, from_step, log_file, verbose):
    """Cluster a finished session's graph and synthesize cross-entity topic pages."""
    from mykg.cli import _sessions_root
    from mykg.llm.config import load_adapter
    from mykg.logging import setup
    from mykg.orchestrator import PipelineContext, run
    from mykg.topics_pipeline import TOPIC_STEPS, vault_dir

    session_root = _sessions_root() / session
    if not session_root.is_dir():
        raise click.ClickException(f"Session '{session}' not found at {session_root}.")
    if not (session_root / "output" / "nodes.jsonl").exists():
        raise click.ClickException(
            f"Session '{session}' has no output/nodes.jsonl — run extract-graph first."
        )

    topics_state = session_root / "topics_state"
    topics_state.mkdir(parents=True, exist_ok=True)
    if log_file is None:
        log_file = session_root / "topics.log"
    setup(log_file=log_file, verbose=verbose)
    logging.getLogger(__name__).info("Command: %s", " ".join(sys.argv))

    step_names = [s.name for s in TOPIC_STEPS]
    if from_step and from_step not in step_names:
        raise click.ClickException(
            f"--from-step must be one of {step_names}, got '{from_step}'."
        )
    start = step_names.index(from_step) if from_step else 0
    for step in TOPIC_STEPS[start:]:
        for output in step.outputs:
            (topics_state / output).unlink(missing_ok=True)

    adapter = load_adapter(intermediate_dir=topics_state)
    ctx = PipelineContext(
        input_dir=session_root / "input",
        output_dir=session_root / "output",
        intermediate_dir=topics_state,
        adapter=adapter,
    )
    if rebuild:
        (vault_dir(ctx) / ".topics_manifest.json").unlink(missing_ok=True)

    run(TOPIC_STEPS, ctx)
    click.echo(f"Topics written to {vault_dir(ctx)}")


#: Fork-added commands, in registration order.
FORK_COMMANDS = (watch, build_wiki, build_topics)


def register(cli) -> None:
    """Attach every fork command to the main ``cli`` group."""
    for command in FORK_COMMANDS:
        cli.add_command(command)
