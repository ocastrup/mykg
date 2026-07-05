import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_mykg_config(tmp_path, monkeypatch):
    """Keep every test off the real filesystem.

    ``mykg.config`` loads the live ``mykg_config.yaml`` (searched upward from
    cwd) at import time, so an unpatched test inherits real user paths —
    ``SESSIONS_DIR`` creates session dirs in the repo, and an absolute
    ``OBSIDIAN_VAULT_DIR`` can make ``_delete_from_step`` rmtree a real vault.
    Redirect those values to safe defaults for all tests; tests that need
    specific values monkeypatch on top of this fixture.
    """
    from mykg import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "_mykg_sessions"))
    monkeypatch.setattr(cfg_mod, "OBSIDIAN_ENABLED", False)
    monkeypatch.setattr(cfg_mod, "OBSIDIAN_VAULT_DIR", "obsidian_vault")
    monkeypatch.setattr(cfg_mod, "NEO4J_CSV_ENABLED", False)
    monkeypatch.setattr(cfg_mod, "NEO4J_CSV_DIR", "neo4j_csv")
    # Behavioural knob the merge_run restart tests depend on: pin to the code
    # default so the suite passes regardless of the active profile's value.
    monkeypatch.setattr(cfg_mod, "MERGE_ORPHAN_SCHEMA_MAX_RESTARTS", 1)


def _load_key(env_var: str) -> str | None:
    key = os.environ.get(env_var, "").strip()
    if not key:
        env_file = Path(__file__).parent.parent / ".env.mykg"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(env_var + "="):
                    key = line.partition("=")[2].strip()
                    break
    return key or None


@pytest.fixture(scope="session")
def openrouter_api_key():
    key = _load_key("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set")
    return key


@pytest.fixture(scope="session")
def live_corpus(tmp_path_factory):
    d = tmp_path_factory.mktemp("corpus")
    (d / "people.md").write_text(
        "Alice is a software engineer at Acme Corp. "
        "Bob manages the infrastructure team at Acme Corp."
    )
    (d / "projects.md").write_text(
        "Acme Corp is building a distributed database called Prometheus. "
        "Alice leads the Prometheus project."
    )
    (d / "history.md").write_text(
        "Acme Corp was founded in 2010. Bob joined in 2015 and Alice in 2018."
    )
    return d
