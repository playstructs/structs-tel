#!/usr/bin/env python3
"""Enable webapp OIDC using values from structs-tel/.env (crew helper)."""
from __future__ import annotations

import re
from pathlib import Path

TEL_ENV = Path("/home/docker/structs-tel/.env")
WEB_ENV = Path("/home/docker/structs-webapp/src/.env")


def get(text: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip("'\"")


def main() -> None:
    tel = TEL_ENV.read_text()
    web_text = WEB_ENV.read_text()

    provider = get(tel, "MAS_UPSTREAM_PROVIDER_ID")
    mas_base = get(tel, "MAS_PUBLIC_BASE").rstrip("/")
    tel_secret = get(tel, "OIDC_MAS_CLIENT_SECRET")
    if not provider or not tel_secret or not mas_base:
        raise SystemExit("structs-tel .env missing MAS_UPSTREAM_PROVIDER_ID / MAS_PUBLIC_BASE / OIDC_MAS_CLIENT_SECRET")

    callback = f"{mas_base}/upstream/callback/{provider}"
    print("provider", provider)
    print("callback", callback)
    print("secrets_match", get(web_text, "OIDC_MAS_CLIENT_SECRET") == tel_secret)

    updates = {
        "OIDC_ENABLED": "true",
        "OIDC_ISSUER": "https://crew.oh.energy",
        "OIDC_MAS_CLIENT_ID": "matrix-auth-service",
        "OIDC_MAS_CLIENT_SECRET": tel_secret,
        "OIDC_MAS_REDIRECT_URI": callback,
    }

    keys_seen: set[str] = set()
    out: list[str] = []
    for line in web_text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}='{updates[k]}'")
                keys_seen.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in keys_seen:
            out.append(f"{k}='{v}'")

    WEB_ENV.write_text("\n".join(out) + "\n")
    print("updated", WEB_ENV)
    for line in WEB_ENV.read_text().splitlines():
        if line.startswith("OIDC_") and not any(
            x in line for x in ("SECRET", "ENCRYPTION", "PRIVATE")
        ):
            print(line)


if __name__ == "__main__":
    main()
