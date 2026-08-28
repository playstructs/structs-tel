#!/usr/bin/env python3
"""Seed OIDC client and verify discovery (crew helper)."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path

WEB_ENV = Path("/home/docker/structs-webapp/src/.env")
TEL_ENV = Path("/home/docker/structs-tel/.env")


def get(text: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip("'\"")


def main() -> None:
    web = WEB_ENV.read_text()
    tel = TEL_ENV.read_text()
    for key in (
        "OIDC_ENABLED",
        "OIDC_ISSUER",
        "OIDC_MAS_CLIENT_ID",
        "OIDC_MAS_REDIRECT_URI",
        "OIDC_JWT_KEY_ID",
    ):
        print(f"{key}={get(web, key)}")
    print("tel_provider", get(tel, "MAS_UPSTREAM_PROVIDER_ID"))
    print("secret_lens", len(get(web, "OIDC_MAS_CLIENT_SECRET")), len(get(tel, "OIDC_MAS_CLIENT_SECRET")))
    print("secrets_match", get(web, "OIDC_MAS_CLIENT_SECRET") == get(tel, "OIDC_MAS_CLIENT_SECRET"))
    print("enc_set", bool(get(web, "OIDC_ENCRYPTION_KEY")))

    callback = get(web, "OIDC_MAS_REDIRECT_URI")
    print("seeding", callback)
    r = subprocess.run(
        [
            "docker",
            "exec",
            "docker-structs-guild-structs-webapp-1",
            "php",
            "bin/console",
            "app:oidc:seed-client",
            f"--redirect-uri={callback}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    print(r.stdout)
    if r.stderr:
        print(r.stderr)
    print("seed_exit", r.returncode)
    if r.returncode != 0:
        raise SystemExit(r.returncode)

    disc_url = "https://crew.oh.energy/.well-known/openid-configuration"
    with urllib.request.urlopen(disc_url, timeout=15) as resp:
        disc = json.load(resp)
    print("issuer", disc.get("issuer"))
    print("jwks_uri", disc.get("jwks_uri"))
    print("authorization_endpoint", disc.get("authorization_endpoint"))
    with urllib.request.urlopen(disc["jwks_uri"], timeout=15) as resp:
        jwks = json.load(resp)
    print("jwks_keys", len(jwks.get("keys", [])))


if __name__ == "__main__":
    main()
