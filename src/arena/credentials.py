"""Safe API-credential resolution for arena adapters.

Keeps API keys out of code, logs, and Git. A key is read from an environment variable if
set, otherwise from a git-ignored file under ``secrets/``. Only the running process ever
reads it — the value never passes through a command line or gets printed, so an agent (human
or Claude) can launch a match without the key entering its view.
"""

import os
from pathlib import Path

_SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"


def resolve_credential(env_var: str, keyfile_name: str) -> str:
    """Return a credential from ``$<env_var>``, else from ``secrets/<keyfile_name>``.

    The environment variable wins. Otherwise the git-ignored key file is read and its first
    non-empty, non-``#`` line (stripped) is returned. Raises :class:`RuntimeError` naming both
    options if neither is present.
    """
    env_value = os.environ.get(env_var)
    if env_value and env_value.strip():
        return env_value.strip()

    keyfile = _SECRETS_DIR / keyfile_name
    if keyfile.exists():
        for raw in keyfile.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                return line

    raise RuntimeError(
        f"No credential found for {env_var}. Set the {env_var} environment variable, or put "
        f"the key in {keyfile} (git-ignored). See docs/AGENT_ARENA_LLM_SETUP.md."
    )
