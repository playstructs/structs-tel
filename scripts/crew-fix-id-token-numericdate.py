#!/usr/bin/env python3
"""Strip fractional seconds from OIDC id_token iat/exp (MAS rejects floats)."""
from __future__ import annotations

from pathlib import Path

PATH = Path("/home/docker/structs-webapp/src/src/Oidc/IdTokenResponse.php")

OLD = """        $issuedAt = new DateTimeImmutable();
        $claims = $this->claimsManager->buildClaims($player, $scopes);

        $builder = $this->jwtConfiguration()->builder()
            ->issuedBy($this->config->getIssuer())
            ->permittedFor($accessToken->getClient()->getIdentifier())
            ->relatedTo($claims['sub'])
            ->issuedAt($issuedAt)
            ->expiresAt($accessToken->getExpiryDateTime())
            ->withHeader('kid', $this->config->getKeyId());
"""

NEW = """        // MAS / openidconnect-rs reject non-integer NumericDate claims
        // (lcobucci/jwt emits fractional seconds from DateTimeImmutable microseconds).
        $issuedAt = (new DateTimeImmutable())->setTimestamp(time());
        $expiresAt = DateTimeImmutable::createFromInterface($accessToken->getExpiryDateTime())
            ->setTimestamp($accessToken->getExpiryDateTime()->getTimestamp());
        $claims = $this->claimsManager->buildClaims($player, $scopes);

        $builder = $this->jwtConfiguration()->builder()
            ->issuedBy($this->config->getIssuer())
            ->permittedFor($accessToken->getClient()->getIdentifier())
            ->relatedTo($claims['sub'])
            ->issuedAt($issuedAt)
            ->expiresAt($expiresAt)
            ->withHeader('kid', $this->config->getKeyId());
"""


def main() -> None:
    text = PATH.read_text()
    if "non-integer NumericDate" in text:
        print("already patched")
        return
    if OLD not in text:
        raise SystemExit("expected IdTokenResponse.php snippet not found")
    PATH.write_text(text.replace(OLD, NEW, 1))
    print("patched", PATH)


if __name__ == "__main__":
    main()
