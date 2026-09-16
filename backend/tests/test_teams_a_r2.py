"""Teams A-R2 — multitenant signing-key issuer, GUID identity, required time claims."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.connectors.teams.constants import (
    CONSUMER_TENANT_ID,
    MICROSOFT_JWKS_URL,
    MICROSOFT_SIGNING_KEY_ISSUER_TEMPLATE,
)
from app.connectors.teams.errors import TeamsIdentityConflictError, TeamsOAuthError
from app.connectors.teams.id_token import (
    MicrosoftIdTokenValidator,
    MicrosoftOrganizationsJwksResolver,
)
from app.connectors.teams.oauth_service import TeamsOAuthService
from app.connectors.teams.oauth_state import hash_oauth_secret
from tests.test_teams_a import TEAMS_USER_ID, TENANT_ID, _connect_account, _store, _user
from tests.test_teams_a_r1 import _signed_id_token, _validator

OTHER_TENANT_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def teams_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> str:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_id", "client-id")
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        "app.core.config.settings.microsoft_redirect_uri",
        "http://localhost:18080/auth/teams/callback",
    )
    return credential_key


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def test_templated_signing_key_issuer_succeeds(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "nonce-template"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    identity = _validator(public_key, issuer=MICROSOFT_SIGNING_KEY_ISSUER_TEMPLATE).validate(
        token,
        audience="client-id",
        nonce_hash=hash_oauth_secret(nonce),
    )
    assert identity.tenant_id == TENANT_ID
    assert identity.oid == TEAMS_USER_ID


def test_signing_key_issuer_for_different_tenant_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    foreign_issuer = f"https://login.microsoftonline.com/{OTHER_TENANT_ID}/v2.0"
    with pytest.raises(TeamsOAuthError, match="signing key issuer"):
        _validator(public_key, issuer=foreign_issuer).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_token_iss_inconsistent_with_canonical_tid_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        extra={"iss": f"https://login.microsoftonline.com/{OTHER_TENANT_ID}/v2.0"},
    )
    with pytest.raises(TeamsOAuthError, match="issuer is invalid"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_malformed_tid_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid="not-a-guid",
        oid=TEAMS_USER_ID,
        nonce=nonce,
        extra={"iss": f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"},
    )
    with pytest.raises(TeamsOAuthError, match="tenant id"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_malformed_oid_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid="not-a-guid",
        nonce=nonce,
    )
    with pytest.raises(TeamsOAuthError, match="user id"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_equivalent_guid_forms_canonicalize_to_same_stored_identity(
    db_session, teams_settings, rsa_keys
) -> None:
    private_key, public_key = rsa_keys
    nonce = "nonce-guid"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID.upper(),
        oid="{" + TEAMS_USER_ID.upper() + "}",
        nonce=nonce,
        extra={"iss": f"https://login.microsoftonline.com/{TENANT_ID.upper()}/v2.0"},
    )

    class _Me:
        def get_me(self):
            return {
                "id": TEAMS_USER_ID.replace("-", ""),
                "displayName": "Ada",
                "userPrincipalName": "ada@contoso.com",
            }

        def close(self):
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-ok",
                "refresh_token": "refresh-ok",
                "id_token": token,
                "expires_in": 3600,
                "scope": "User.Read Chat.Read ChatMessage.Send",
            },
        )

    service = TeamsOAuthService(
        "client-id",
        "client-secret",
        "http://localhost/callback",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        id_token_validator=_validator(public_key),
        graph_transport_factory=lambda _access: _Me(),
    )
    login = service.complete_login("code", nonce_hash=hash_oauth_secret(nonce))
    assert login["tenant_id"] == TENANT_ID
    assert login["microsoft_user_id"] == TEAMS_USER_ID
    user = _user(db_session)
    account = _store(db_session, teams_settings).upsert_tokens(
        user.id,
        microsoft_user_id=TEAMS_USER_ID.upper(),
        tenant_id="{" + TENANT_ID.upper() + "}",
        upn=login["upn"],
        display_name=login["display_name"],
        scopes=login["scopes"],
        access_token=login["access_token"],
        refresh_token=login["refresh_token"],
        token_expiry=login["token_expiry"],
    )
    assert account.tenant_id == TENANT_ID
    assert account.microsoft_user_id == TEAMS_USER_ID
    found = _store(db_session, teams_settings).get_by_microsoft_identity(
        TENANT_ID.replace("-", ""),
        "{" + TEAMS_USER_ID + "}",
    )
    assert found is not None
    assert found.id == account.id


def test_missing_iat_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        omit={"iat"},
    )
    with pytest.raises(TeamsOAuthError, match="invalid"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_missing_nbf_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        omit={"nbf"},
    )
    with pytest.raises(TeamsOAuthError, match="invalid"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_expired_token_remains_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        exp=datetime.now(UTC) - timedelta(minutes=5),
    )
    with pytest.raises(TeamsOAuthError, match="expired"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_wrong_audience_remains_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="other-client",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    with pytest.raises(TeamsOAuthError, match="audience"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_wrong_nonce_remains_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce="expected",
    )
    with pytest.raises(TeamsOAuthError, match="nonce"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret("other")
        )


def test_consumer_tenant_remains_rejected(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=CONSUMER_TENANT_ID.upper(),
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    with pytest.raises(TeamsOAuthError, match="personal"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_me_id_comparison_uses_canonical_guid(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )

    class _Me:
        def get_me(self):
            return {"id": TEAMS_USER_ID.upper(), "displayName": "Ada"}

        def close(self):
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-ok",
                "refresh_token": "refresh-ok",
                "id_token": token,
                "expires_in": 3600,
                "scope": "User.Read Chat.Read ChatMessage.Send",
            },
        )

    service = TeamsOAuthService(
        "client-id",
        "client-secret",
        "http://localhost/callback",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        id_token_validator=_validator(public_key),
        graph_transport_factory=lambda _access: _Me(),
    )
    login = service.complete_login("code", nonce_hash=hash_oauth_secret(nonce))
    assert login["microsoft_user_id"] == TEAMS_USER_ID


def test_jwk_resolution_failure_is_safe_oauth_error(rsa_keys) -> None:
    private_key, _public_key = rsa_keys
    nonce = "nonce-resolution-failure"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        headers={"kid": "test-kid"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "eyJ" not in str(request.url)
        raise httpx.ConnectError("dns failed", request=request)

    resolver = MicrosoftOrganizationsJwksResolver(
        httpx.Client(transport=httpx.MockTransport(handler)),
        jwks_url=MICROSOFT_JWKS_URL,
    )
    validator = MicrosoftIdTokenValidator(resolver)
    with pytest.raises(TeamsOAuthError, match="signing keys could not be resolved") as exc:
        validator.validate(token, audience="client-id", nonce_hash=hash_oauth_secret(nonce))
    message = str(exc.value)
    assert token not in message
    assert "eyJ" not in message
    assert "client-secret" not in message
    assert nonce not in message


def test_jwks_key_issuer_metadata_is_used_for_trust(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    kid = "org-key-1"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        headers={"kid": kid},
    )
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk["issuer"] = MICROSOFT_SIGNING_KEY_ISSUER_TEMPLATE
    jwk["use"] = "sig"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == MICROSOFT_JWKS_URL
        return httpx.Response(200, json={"keys": [jwk]})

    resolver = MicrosoftOrganizationsJwksResolver(
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    identity = MicrosoftIdTokenValidator(resolver).validate(
        token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
    )
    assert identity.tenant_id == TENANT_ID
    assert identity.oid == TEAMS_USER_ID


def test_same_canonical_identity_cannot_bind_two_users(db_session, teams_settings) -> None:
    first = _user(db_session, "one")
    second = _user(db_session, "two")
    _connect_account(db_session, teams_settings, first.id)
    store = _store(db_session, teams_settings)
    with pytest.raises(TeamsIdentityConflictError):
        store.upsert_tokens(
            second.id,
            microsoft_user_id=TEAMS_USER_ID.upper(),
            tenant_id=TENANT_ID.upper(),
            upn="other@contoso.com",
            display_name="Other",
            scopes=["User.Read"],
            access_token="a",
            refresh_token="r",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
        )
