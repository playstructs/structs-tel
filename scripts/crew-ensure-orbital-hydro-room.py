#!/usr/bin/env python3
"""Ensure Orbital Hydro public room alias and print join info."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path("/home/docker/structs-tel")
TOKEN_PATH = ROOT / "config/secrets/guild-bot.compatibility-token"
ROOM_ID = "!eTPyzkdiTuhOTg7UE61WNc4OM_0KcumkL5mULKJACb4"
ALIAS_LOCAL = "orbital-hydro"
SERVER = "matrix.crew.oh.energy"
BASE = "http://127.0.0.1:8008"


def req(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"{method} {path} -> {exc.code}: {detail}") from exc


def main() -> None:
    token = TOKEN_PATH.read_text().strip()
    room_enc = urllib.parse.quote(ROOM_ID, safe="")
    alias_enc = urllib.parse.quote(f"#{ALIAS_LOCAL}:{SERVER}", safe="")

    for event in (
        "m.room.name",
        "m.room.topic",
        "m.room.join_rules",
        "m.room.history_visibility",
        "m.room.canonical_alias",
    ):
        try:
            state = req("GET", f"/_matrix/client/v3/rooms/{room_enc}/state/{event}", token)
            print(f"{event}: {json.dumps(state)}")
        except SystemExit as exc:
            print(f"{event}: {exc}")

    try:
        directory = req("GET", f"/_matrix/client/v3/directory/room/{alias_enc}", token)
        print("directory:", json.dumps(directory))
    except SystemExit:
        print("alias missing; creating #orbital-hydro:matrix.crew.oh.energy")
        req(
            "PUT",
            f"/_matrix/client/v3/directory/room/{alias_enc}",
            token,
            {"room_id": ROOM_ID},
        )
        req(
            "PUT",
            f"/_matrix/client/v3/rooms/{room_enc}/state/m.room.canonical_alias",
            token,
            {"alias": f"#{ALIAS_LOCAL}:{SERVER}"},
        )
        directory = req("GET", f"/_matrix/client/v3/directory/room/{alias_enc}", token)
        print("directory:", json.dumps(directory))

    print()
    print("Room ready:")
    print(f"  room_id: {ROOM_ID}")
    print(f"  alias:   #{ALIAS_LOCAL}:{SERVER}")
    print(f"  creator: @guild-bot:{SERVER}")


if __name__ == "__main__":
    main()
