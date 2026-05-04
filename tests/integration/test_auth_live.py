"""Live integration tests for the auth slice — real Postgres, real bcrypt."""

from __future__ import annotations

import string
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio


def _make_key() -> str:
    """Create a structurally valid plaintext key for tests."""
    import secrets
    alphabet = string.ascii_letters + string.digits
    return "pk_live_" + "".join(secrets.choice(alphabet) for _ in range(32))


@pytest_asyncio.fixture
async def auth_enabled_app(palace_app):
    """Flip auth on for the duration of one test, then back off."""
    from palace.config import settings

    original = settings.auth_disabled
    settings.auth_disabled = False
    try:
        yield palace_app
    finally:
        settings.auth_disabled = original


@pytest_asyncio.fixture
async def auth_http_client(auth_enabled_app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=auth_enabled_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://palace.test",
    ) as client:
        yield client


pytestmark = pytest.mark.integration


async def test_health_works_without_key(auth_http_client):
    r = await auth_http_client.get("/health")
    assert r.status_code == 200


async def test_protected_endpoint_rejects_no_key(auth_http_client):
    r = await auth_http_client.post(
        "/v1/memories", json={"user_id": "u1", "content": "x"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


async def test_full_lifecycle_admin_then_write_key(auth_http_client):
    """Mint admin key via service, use it to issue a write key, exercise both."""
    from palace.auth.key_service import key_service

    # Bootstrap an admin key directly via the service (simulating env bootstrap)
    admin_plaintext = _make_key()
    await key_service.bootstrap_if_needed(admin_plaintext)

    # Admin key can list (read) ... wait, list_keys requires admin scope.
    # bootstrap_if_needed gives all three scopes.
    r = await auth_http_client.get(
        "/v1/admin/keys",
        headers={"X-Palace-Key": admin_plaintext},
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1

    # Admin issues a write-only key
    r = await auth_http_client.post(
        "/v1/admin/keys",
        headers={"X-Palace-Key": admin_plaintext},
        json={"label": "writer", "scopes": ["read", "write"]},
    )
    assert r.status_code == 200
    write_plaintext = r.json()["data"]["plaintext_key"]
    write_key_id = r.json()["data"]["key_id"]

    # Write key can create a memory
    r = await auth_http_client.post(
        "/v1/memories",
        headers={"X-Palace-Key": write_plaintext},
        json={"user_id": "u1", "content": "remembered"},
    )
    assert r.status_code == 200, r.text

    # Write key cannot list api keys (needs admin)
    r = await auth_http_client.get(
        "/v1/admin/keys",
        headers={"X-Palace-Key": write_plaintext},
    )
    assert r.status_code == 403

    # Admin revokes the write key
    r = await auth_http_client.delete(
        f"/v1/admin/keys/{write_key_id}",
        headers={"X-Palace-Key": admin_plaintext},
    )
    assert r.status_code == 200

    # Revoked key now rejected
    r = await auth_http_client.post(
        "/v1/memories",
        headers={"X-Palace-Key": write_plaintext},
        json={"user_id": "u1", "content": "x"},
    )
    assert r.status_code == 401


async def test_invalid_key_rejected(auth_http_client):
    r = await auth_http_client.get(
        "/v1/admin/keys",
        headers={"X-Palace-Key": "pk_live_doesnotexist0000000000000000aa"},
    )
    assert r.status_code == 401


async def test_malformed_key_rejected(auth_http_client):
    r = await auth_http_client.get(
        "/v1/admin/keys",
        headers={"X-Palace-Key": "garbage"},
    )
    assert r.status_code == 401


async def test_bootstrap_idempotent(palace_app):
    """Calling bootstrap_if_needed twice with admin existing is a no-op."""
    from palace.auth.key_service import key_service

    p1 = _make_key()
    inserted_first = await key_service.bootstrap_if_needed(p1)
    assert inserted_first is True

    p2 = _make_key()
    inserted_second = await key_service.bootstrap_if_needed(p2)
    assert inserted_second is False  # admin already exists


async def test_bootstrap_with_none_when_no_admin(palace_app, caplog):
    """No env var + no existing admin → warn and return False."""
    import logging

    from palace.auth.key_service import key_service

    with caplog.at_level(logging.WARNING):
        result = await key_service.bootstrap_if_needed(None)
    assert result is False
