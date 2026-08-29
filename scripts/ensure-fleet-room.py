#!/usr/bin/env python3
"""
Idempotently ensure a public fleet room created by @guild-bot.

Alias scheme: #fleet-{fleetId}:{server}  e.g. #fleet-9-42:matrix.crew.oh.energy
Fleet id is 9-{playerIndex}; player Matrix localpart is player id (1-{playerIndex}).

Usage:
  export MATRIX_SERVER_NAME=matrix.crew.oh.energy
  export SYNAPSE_CLIENT_URL=http://127.0.0.1:8008   # optional
  export GUILD_BOT_TOKEN=mct_...                    # or config/secrets/guild-bot.compatibility-token

  ./scripts/ensure-fleet-room.py --player-id 1-42
  ./scripts/ensure-fleet-room.py --fleet-id 9-42
  ./scripts/ensure-fleet-room.py --player-id 1-42 --display-name "Alice"

Requires: Python 3.10+, guild-bot compatibility token with permission to create rooms.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOKEN_PATH = ROOT / "config/secrets/guild-bot.compatibility-token"


def fleet_id_from_player(player_id: str) -> str:
    parts = player_id.split("-", 1)
    if len(parts) != 2 or parts[0] != "1" or not parts[1].isdigit():
        raise SystemExit(f"player id must look like 1-42, got {player_id!r}")
    return f"9-{parts[1]}"


def player_id_from_fleet(fleet_id: str) -> str:
    parts = fleet_id.split("-", 1)
    if len(parts) != 2 or parts[0] != "9" or not parts[1].isdigit():
        raise SystemExit(f"fleet id must look like 9-42, got {fleet_id!r}")
    return f"1-{parts[1]}"


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


def ensure_joined(base: str, token: str, room_id: str, user_id: str) -> None:
    room_enc = urllib.parse.quote(room_id, safe="")
    # Invite then ignore if already in room
    try:
        req(
            base,
            "POST",
            f"/_matrix/client/v3/rooms/{room_enc}/invite",
            token,
            {"user_id": user_id},
        )
        print(f"invited {user_id}")
    except SystemExit as exc:
        msg = str(exc)
        if "M_FORBIDDEN" in msg or "already" in msg.lower() or " -> 403:" in msg:
            print(f"invite skipped ({user_id}): already member or forbidden")
        else:
            # 403 "already in the room" variants
            print(f"invite note: {exc}")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-id", help="Player id e.g. 1-42")
    parser.add_argument("--fleet-id", help="Fleet id e.g. 9-42")
    parser.add_argument("--display-name", help="Optional room name override")
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

    if args.fleet_id and args.player_id:
        fleet_id = args.fleet_id
        player_id = args.player_id
        if fleet_id_from_player(player_id) != fleet_id:
            raise SystemExit("player-id and fleet-id do not match (1-N ↔ 9-N)")
    elif args.fleet_id:
        fleet_id = args.fleet_id
        player_id = player_id_from_fleet(fleet_id)
    elif args.player_id:
        player_id = args.player_id
        fleet_id = fleet_id_from_player(player_id)
    else:
        raise SystemExit("Pass --player-id and/or --fleet-id")

    server = args.server_name
    base = args.base_url.rstrip("/")
    token = load_token(args.token_file)
    alias_local = f"fleet-{fleet_id}"
    alias = f"#{alias_local}:{server}"
    owner_mxid = f"@{player_id}:{server}"
    room_name = args.display_name or f"Fleet {fleet_id}"
    topic = f"Public fleet chat for {fleet_id} (owner {player_id})"

    existing = resolve_alias(base, token, alias)
    if existing:
        room_id = existing
        print(f"exists {alias} -> {room_id}")
    else:
        created = req(
            base,
            "POST",
            "/_matrix/client/v3/createRoom",
            token,
            {
                "name": room_name,
                "topic": topic,
                "room_alias_name": alias_local,
                "preset": "public_chat",
                "visibility": "public",
                "power_level_content_override": {
                    "events_default": 0,
                    "users_default": 0,
                    "users": {owner_mxid: 100},
                },
            },
        )
        room_id = created["room_id"]
        print(f"created {alias} -> {room_id}")

    # Ensure canonical alias + directory (createRoom usually sets these)
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

    set_power_level_owner(base, token, room_id, owner_mxid)

    if not args.no_invite:
        ensure_joined(base, token, room_id, owner_mxid)

    print()
    print("Fleet room ready:")
    print(f"  fleet_id:  {fleet_id}")
    print(f"  player:    {owner_mxid}")
    print(f"  room_id:   {room_id}")
    print(f"  alias:     {alias}")
    print(f"  creator:   @guild-bot:{server}")


if __name__ == "__main__":
    main()
