#!/usr/bin/env python3
"""
Idempotently ensure a public, directory-published room created by @guild-bot.

Use for guild channels and per-object rooms (planets, etc.). Fleet rooms have
a dedicated helper: ensure-fleet-room.py (#fleet-9-N ↔ player 1-N).

Alias is always on THIS homeserver (Matrix cannot mint #planet-…:their.server
from our client). Create the room on the owner guild's structs-tel.

Usage:
  export MATRIX_SERVER_NAME=matrix.crew.oh.energy
  export SYNAPSE_CLIENT_URL=http://127.0.0.1:8008   # optional
  export GUILD_BOT_TOKEN=mct_...                    # or config/secrets/guild-bot.compatibility-token

  ./scripts/ensure-published-room.py --alias-local orbital-hydro --name "Orbital Hydro"
  ./scripts/ensure-published-room.py --alias-local planet-2-15361 --name "Planet 2-15361" \
      --owner-player-id 1-42

Requires: Python 3.10+, guild-bot compatibility token.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOKEN_PATH = ROOT / "config/secrets/guild-bot.compatibility-token"


def load_token(path: Path | None) -> str:
    env = os.environ.get("GUILD_BOT_TOKEN", "").strip()
    if env:
        return env
    token_path = path or DEFAULT_TOKEN_PATH
    if not token_path.is_file():
        raise SystemExit(
            f"Missing guild-bot token ({token_path}); set GUILD_BOT_TOKEN or "
            "run: docker compose exec mas mas-cli manage issue-compatibility-token guild-bot"
        )
    return token_path.read_text().strip()


def req(
    base: str,
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"{method} {path} -> {exc.code}: {detail}") from exc


def resolve_alias(base: str, token: str, alias: str) -> str | None:
    enc = urllib.parse.quote(alias, safe="")
    try:
        data = req(base, "GET", f"/_matrix/client/v3/directory/room/{enc}", token)
        return data.get("room_id")
    except SystemExit as exc:
        if " -> 404:" in str(exc):
            return None
        raise


def set_power_level_owner(base: str, token: str, room_id: str, owner_mxid: str) -> None:
    room_enc = urllib.parse.quote(room_id, safe="")
    try:
        pl = req(base, "GET", f"/_matrix/client/v3/rooms/{room_enc}/state/m.room.power_levels", token)
    except SystemExit:
        pl = {}
    users = dict(pl.get("users") or {})
    if users.get(owner_mxid) == 100:
        return
    users[owner_mxid] = 100
    pl["users"] = users
    pl.setdefault("events_default", 0)
    pl.setdefault("users_default", 0)
    req(base, "PUT", f"/_matrix/client/v3/rooms/{room_enc}/state/m.room.power_levels", token, pl)
    print(f"power_levels: {owner_mxid} -> 100")


def publish_directory(base: str, token: str, room_id: str) -> None:
    room_enc = urllib.parse.quote(room_id, safe="")
    try:
        req(
            base,
            "PUT",
            f"/_matrix/client/v3/directory/list/room/{room_enc}",
            token,
            {"visibility": "public"},
        )
        print("directory visibility: public")
    except SystemExit as exc:
        print(f"directory publish note: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alias-local",
        required=True,
        help="Localpart only, e.g. planet-2-15361 or orbital-hydro (no # or :server)",
    )
    parser.add_argument("--name", required=True, help="Room display name")
    parser.add_argument("--topic", default="", help="Optional topic")
    parser.add_argument(
        "--owner-player-id",
        help="Optional player id (e.g. 1-42) granted PL 100 on this server",
    )
    parser.add_argument(
        "--server-name",
        default=os.environ.get("MATRIX_SERVER_NAME", ""),
        help="Homeserver name (or MATRIX_SERVER_NAME)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SYNAPSE_CLIENT_URL", "http://127.0.0.1:8008"),
        help="Synapse client API base",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help="Path to guild-bot compatibility token file",
    )
    parser.add_argument(
        "--no-invite",
        action="store_true",
        help="Do not invite the owner player into the room",
    )
    args = parser.parse_args()

    if not args.server_name:
        raise SystemExit("Set --server-name or MATRIX_SERVER_NAME")

    local = args.alias_local.lstrip("#").split(":", 1)[0]
    if not local or "/" in local or "#" in local:
        raise SystemExit(f"bad --alias-local {args.alias_local!r}")

    server = args.server_name
    base = args.base_url.rstrip("/")
    token = load_token(args.token_file)
    alias = f"#{local}:{server}"

    existing = resolve_alias(base, token, alias)
    if existing:
        room_id = existing
        print(f"exists {alias} -> {room_id}")
    else:
        body: dict = {
            "name": args.name,
            "room_alias_name": local,
            "preset": "public_chat",
            "visibility": "public",
            "power_level_content_override": {
                "events_default": 0,
                "users_default": 0,
            },
        }
        if args.topic:
            body["topic"] = args.topic
        if args.owner_player_id:
            owner_mxid = f"@{args.owner_player_id}:{server}"
            body["power_level_content_override"]["users"] = {owner_mxid: 100}
        created = req(base, "POST", "/_matrix/client/v3/createRoom", token, body)
        room_id = created["room_id"]
        print(f"created {alias} -> {room_id}")

    room_enc = urllib.parse.quote(room_id, safe="")
    alias_enc = urllib.parse.quote(alias, safe="")
    if resolve_alias(base, token, alias) is None:
        req(base, "PUT", f"/_matrix/client/v3/directory/room/{alias_enc}", token, {"room_id": room_id})
    try:
        req(
            base,
            "PUT",
            f"/_matrix/client/v3/rooms/{room_enc}/state/m.room.canonical_alias",
            token,
            {"alias": alias},
        )
    except SystemExit as exc:
        print(f"canonical_alias note: {exc}")

    publish_directory(base, token, room_id)

    if args.owner_player_id:
        owner_mxid = f"@{args.owner_player_id}:{server}"
        set_power_level_owner(base, token, room_id, owner_mxid)
        if not args.no_invite:
            try:
                req(
                    base,
                    "POST",
                    f"/_matrix/client/v3/rooms/{room_enc}/invite",
                    token,
                    {"user_id": owner_mxid},
                )
                print(f"invited {owner_mxid}")
            except SystemExit as exc:
                print(f"invite note: {exc}")

    print()
    print("Published room ready:")
    print(f"  room_id:  {room_id}")
    print(f"  alias:    {alias}")
    print(f"  creator:  @guild-bot:{server}")


if __name__ == "__main__":
    main()
