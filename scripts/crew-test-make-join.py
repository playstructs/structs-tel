#!/usr/bin/env python3
"""Reproduce federated make_join from crew → matrix.crab.la."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from signedjson.key import decode_signing_key_base64
from signedjson.sign import sign_json

ORIGIN = "matrix.crew.oh.energy"
DEST = "matrix.crab.la"
ROOM = "!CfNYPU-xGrUcrJoyCYT81ZqFVVOP1AZyZkW9-giLZF4"
USER = "@1-3076:matrix.crew.oh.energy"
SIGNING_KEY = "/data/signing.key"


def main() -> None:
    with open(SIGNING_KEY, encoding="utf-8") as handle:
        alg, key_id, secret = handle.read().strip().split()
    signing_key = decode_signing_key_base64(alg, key_id, secret)

    path = (
        "/_matrix/federation/v1/make_join/"
        f"{urllib.parse.quote(ROOM, safe='')}/"
        f"{urllib.parse.quote(USER, safe='')}"
    )
    query = urllib.parse.urlencode(
        [("ver", str(v)) for v in range(1, 13)],
        doseq=True,
    )
    uri = f"{path}?{query}"

    request_json = {
        "method": "GET",
        "uri": uri,
        "origin": ORIGIN,
        "destination": DEST,
    }
    signed = sign_json(request_json, ORIGIN, signing_key)
    sig = signed["signatures"][ORIGIN][f"{alg}:{key_id}"]
    auth = (
        f'X-Matrix origin={ORIGIN},destination={DEST},'
        f'key="{alg}:{key_id}",sig="{sig}"'
    )

    well_known = json.load(
        urllib.request.urlopen(f"https://{DEST}/.well-known/matrix/server", timeout=30)
    )
    server = well_known["m.server"]
    url = f"https://{server}{uri}"
    print("GET", url)
    print("Authorization:", auth[:160], "...")

    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print("status", resp.status)
            print(resp.read().decode()[:3000])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        print("status", exc.code)
        print(body[:3000])


if __name__ == "__main__":
    main()
