#!/usr/bin/env python3
"""Render config templates without envsubst."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAS_SECRETS = ROOT / "config/secrets/mas-secrets.yaml"
# Exact standalone line only (must not appear inside comments).
MARKER = "MAS_SECRETS_BLOCK_GOES_HERE"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip("'").strip('"')
    return env


def inject_mas_secrets(text: str) -> str:
    line_marker = MARKER + "\n"
    # Accept final line without trailing newline
    if line_marker not in text and not text.rstrip("\n").endswith(MARKER):
        if MARKER in text:
            raise SystemExit(
                f"Marker {MARKER!r} must be alone on its own line "
                "(and must not appear in comments)"
            )
        return text
    if not MAS_SECRETS.is_file():
        raise SystemExit(
            f"Missing {MAS_SECRETS}; run ./scripts/generate-secrets.sh first"
        )
    secrets = MAS_SECRETS.read_text().rstrip() + "\n"
    if not secrets.lstrip().startswith("secrets:"):
        raise SystemExit(f"{MAS_SECRETS} must start with a top-level secrets: block")
    if text.count(MARKER) != 1:
        raise SystemExit(f"Expected exactly one {MARKER!r} in MAS template")
    return text.replace(MARKER, secrets.rstrip("\n"), 1)


def render(template: Path, dest: Path, env: dict[str, str]) -> None:
    text = template.read_text()

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in env:
            raise SystemExit(f"Missing env var for template {template.name}: {key}")
        return env[key]

    out = re.sub(r"\$\{([A-Z][A-Z0-9_]*)\}", repl, text)
    out = inject_mas_secrets(out)
    dest.write_text(out)
    print(f"Wrote {dest}")


def warn_oidc_secret(secret: str) -> None:
    """MAS RFC-encodes Basic auth; league/oauth2-server does not urldecode."""
    bad = [c for c in "+/=" if c in secret]
    if not bad:
        return
    shown = ", ".join(repr(c) for c in bad)
    print(
        f"WARNING: OIDC_MAS_CLIENT_SECRET contains {shown}. "
        "MAS client_secret_basic percent-encodes those before HTTP Basic; "
        "the webapp does not decode them, so /oauth/token returns 401 "
        "invalid_client and Element/MAS login 500s. Rotate to "
        "`openssl rand -hex 32`, re-seed app:oidc:seed-client, re-render, "
        "recreate mas. See docs/TROUBLESHOOTING.md.",
        file=sys.stderr,
    )


def main() -> None:
    env = {**os.environ, **load_env(ROOT / ".env")}
    env.setdefault("STRUCTS_PG_HOST", "structs-pg")
    env.setdefault("STRUCTS_PG_PORT", "5432")
    env.setdefault("SYNAPSE_DB_NAME", "synapse")
    env.setdefault("SYNAPSE_DB_USER", "synapse")
    env.setdefault("MAS_DB_NAME", "mas")
    env.setdefault("MAS_DB_USER", "mas")
    warn_oidc_secret(env.get("OIDC_MAS_CLIENT_SECRET", ""))

    render(
        ROOT / "config/synapse/homeserver.yaml.template",
        ROOT / "config/synapse/homeserver.yaml",
        env,
    )
    render(
        ROOT / "config/mas/config.yaml.template",
        ROOT / "config/mas/config.yaml",
        env,
    )


if __name__ == "__main__":
    main()
