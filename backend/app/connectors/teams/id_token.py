from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from app.connectors.teams.constants import (
    CONSUMER_TENANT_ID,
    ID_TOKEN_LEEWAY_SECONDS,
    MICROSOFT_ISSUER_PREFIX,
    MICROSOFT_ISSUER_SUFFIX,
    MICROSOFT_JWKS_URL,
)
from app.connectors.teams.errors import TeamsOAuthError
from app.connectors.teams.oauth_state import hash_oauth_secret

_TENANT_PLACEHOLDER = re.compile(r"\{tenantid\}", re.IGNORECASE)
_SIGNING_KEY_RESOLUTION_ERROR = "Microsoft signing keys could not be resolved"


@dataclass(frozen=True)
class ResolvedSigningKey:
    key: Any
    issuer: str


class TeamsSigningKeyResolver(Protocol):
    def resolve_signing_key(self, token: str) -> ResolvedSigningKey:
        ...


@dataclass(frozen=True)
class ValidatedMicrosoftIdentity:
    tenant_id: str
    oid: str


def canonicalize_microsoft_guid(value: object, *, claim: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TeamsOAuthError(f"Microsoft identity is missing {claim}")
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise TeamsOAuthError(f"Microsoft {claim} is invalid") from exc


def try_canonical_microsoft_guid(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(UUID(text))
    except ValueError:
        return text


def microsoft_issuer_for_tenant(tenant_id: str) -> str:
    return f"{MICROSOFT_ISSUER_PREFIX}{tenant_id}{MICROSOFT_ISSUER_SUFFIX}"


def _microsoft_v2_tenant_from_issuer(issuer: str, *, claim: str) -> str:
    if not issuer.startswith(MICROSOFT_ISSUER_PREFIX) or not issuer.endswith(MICROSOFT_ISSUER_SUFFIX):
        raise TeamsOAuthError(f"Microsoft {claim} is invalid")
    tenant_part = issuer[len(MICROSOFT_ISSUER_PREFIX) : -len(MICROSOFT_ISSUER_SUFFIX)]
    return canonicalize_microsoft_guid(tenant_part, claim="tenant id")


def _resolved_signing_key_issuer(key_issuer: str, canonical_tid: str) -> str:
    stripped = key_issuer.strip()
    if not stripped:
        raise TeamsOAuthError("Microsoft signing key issuer is invalid")
    if _TENANT_PLACEHOLDER.search(stripped):
        return _TENANT_PLACEHOLDER.sub(canonical_tid, stripped)
    return stripped


class MicrosoftOrganizationsJwksResolver:
    def __init__(
        self,
        http_client: httpx.Client | None = None,
        *,
        jwks_url: str = MICROSOFT_JWKS_URL,
    ) -> None:
        self._http = http_client
        self._jwks_url = jwks_url

    def resolve_signing_key(self, token: str) -> ResolvedSigningKey:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise TeamsOAuthError("Microsoft id_token is invalid") from exc
        if header.get("alg") != "RS256":
            raise TeamsOAuthError("Microsoft id_token is invalid")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise TeamsOAuthError("Microsoft id_token is invalid")
        jwk = self._jwk_for_kid(kid.strip())
        issuer = jwk.get("issuer")
        if not isinstance(issuer, str) or not issuer.strip():
            raise TeamsOAuthError("Microsoft signing key issuer is invalid")
        try:
            key = RSAAlgorithm.from_jwk(json.dumps(jwk))
        except (ValueError, TypeError, jwt.InvalidKeyError) as exc:
            raise TeamsOAuthError(_SIGNING_KEY_RESOLUTION_ERROR) from exc
        return ResolvedSigningKey(key=key, issuer=issuer.strip())

    def _jwk_for_kid(self, kid: str) -> dict[str, Any]:
        try:
            payload = self._fetch_jwks()
        except TeamsOAuthError:
            raise
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            raise TeamsOAuthError(_SIGNING_KEY_RESOLUTION_ERROR) from exc
        keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(keys, list):
            raise TeamsOAuthError(_SIGNING_KEY_RESOLUTION_ERROR)
        for item in keys:
            if isinstance(item, dict) and item.get("kid") == kid:
                return item
        raise TeamsOAuthError(_SIGNING_KEY_RESOLUTION_ERROR)

    def _fetch_jwks(self) -> dict[str, Any]:
        if self._http is not None:
            response = self._http.get(self._jwks_url)
            response.raise_for_status()
            payload = response.json()
        else:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self._jwks_url)
                response.raise_for_status()
                payload = response.json()
        if not isinstance(payload, dict):
            raise TeamsOAuthError(_SIGNING_KEY_RESOLUTION_ERROR)
        return payload


class MicrosoftIdTokenValidator:
    def __init__(self, signing_key_resolver: TeamsSigningKeyResolver | None = None) -> None:
        self._resolver = signing_key_resolver or MicrosoftOrganizationsJwksResolver()

    def validate(
        self,
        id_token: str,
        *,
        audience: str,
        nonce_hash: str,
    ) -> ValidatedMicrosoftIdentity:
        token = id_token.strip()
        audience = audience.strip()
        nonce_hash = nonce_hash.strip()
        if not token or not audience or not nonce_hash:
            raise TeamsOAuthError("invalid Microsoft id_token")
        try:
            resolved = self._resolver.resolve_signing_key(token)
            claims = jwt.decode(
                token,
                resolved.key,
                algorithms=["RS256"],
                audience=audience,
                options={
                    "require": ["exp", "nbf", "iat", "aud", "iss"],
                    "verify_iss": False,
                    "verify_aud": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                },
                leeway=ID_TOKEN_LEEWAY_SECONDS,
            )
        except TeamsOAuthError:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise TeamsOAuthError("Microsoft id_token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise TeamsOAuthError("Microsoft id_token audience is invalid") from exc
        except jwt.InvalidTokenError as exc:
            raise TeamsOAuthError("Microsoft id_token is invalid") from exc
        if not isinstance(claims, dict):
            raise TeamsOAuthError("Microsoft id_token is invalid")
        tenant_id = canonicalize_microsoft_guid(claims.get("tid"), claim="tenant id")
        oid = canonicalize_microsoft_guid(claims.get("oid"), claim="user id")
        issuer = str(claims.get("iss") or "").strip()
        nonce = str(claims.get("nonce") or "").strip()
        if tenant_id == CONSUMER_TENANT_ID:
            raise TeamsOAuthError("personal Microsoft accounts are not supported")
        try:
            iss_tid = _microsoft_v2_tenant_from_issuer(issuer, claim="id_token issuer")
        except TeamsOAuthError as exc:
            raise TeamsOAuthError("Microsoft id_token issuer is invalid") from exc
        if iss_tid != tenant_id:
            raise TeamsOAuthError("Microsoft id_token issuer is invalid")
        token_iss = microsoft_issuer_for_tenant(tenant_id)
        try:
            resolved_key_issuer = _resolved_signing_key_issuer(resolved.issuer, tenant_id)
            key_tid = _microsoft_v2_tenant_from_issuer(
                resolved_key_issuer, claim="signing key issuer"
            )
        except TeamsOAuthError as exc:
            raise TeamsOAuthError("Microsoft signing key issuer is invalid") from exc
        if microsoft_issuer_for_tenant(key_tid) != token_iss:
            raise TeamsOAuthError("Microsoft signing key issuer is invalid")
        if not nonce or hash_oauth_secret(nonce) != nonce_hash:
            raise TeamsOAuthError("Microsoft id_token nonce is invalid")
        return ValidatedMicrosoftIdentity(tenant_id=tenant_id, oid=oid)
