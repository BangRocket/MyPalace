"""Live tenant-isolation tests against real Postgres + Qdrant."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_default_tenant_is_created_on_startup(palace_app):
    from sqlalchemy import select

    from palace.config import settings
    from palace.database import async_session
    from palace.models import Tenant

    async with async_session() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.id == settings.default_tenant_id),
        )
        row = result.scalar_one_or_none()
    assert row is not None
    assert row.label == "Default Tenant"


async def test_memory_create_persists_tenant_id(palace_app):
    """Auth is disabled in palace_settings → AuthContext.all_scopes uses
    settings.default_tenant_id ("test"). Memory rows should have tenant_id="test"."""
    from sqlalchemy import select

    from palace.database import async_session
    from palace.memory_service import memory_service
    from palace.models import Memory

    mem = await memory_service.create(
        user_id="u1", content="hello", tenant_id="test",
    )
    async with async_session() as db:
        result = await db.execute(select(Memory).where(Memory.id == mem.id))
        row = result.scalar_one()
    assert row.tenant_id == "test"


async def test_search_isolates_by_tenant(palace_app):
    """A memory created under tenant=A is not visible to tenant=B searches."""
    from palace.memory_service import memory_service

    await memory_service.create(
        user_id="u1", content="alpha tenant secret", tenant_id="alpha",
    )
    await memory_service.create(
        user_id="u1", content="beta tenant secret", tenant_id="beta",
    )

    alpha_results = await memory_service.search(
        query="secret", limit=10, tenant_id="alpha",
    )
    beta_results = await memory_service.search(
        query="secret", limit=10, tenant_id="beta",
    )
    test_results = await memory_service.search(
        query="secret", limit=10, tenant_id="test",
    )

    alpha_contents = {m.content for m, _ in alpha_results}
    beta_contents = {m.content for m, _ in beta_results}
    test_contents = {m.content for m, _ in test_results}

    assert "alpha tenant secret" in alpha_contents
    assert "beta tenant secret" not in alpha_contents
    assert "beta tenant secret" in beta_contents
    assert "alpha tenant secret" not in beta_contents
    assert "alpha tenant secret" not in test_contents
    assert "beta tenant secret" not in test_contents


async def test_list_isolates_by_tenant(palace_app):
    from palace.memory_service import memory_service

    await memory_service.create(
        user_id="user_x", content="alpha A", tenant_id="alpha",
    )
    await memory_service.create(
        user_id="user_x", content="beta A", tenant_id="beta",
    )
    alpha_list = await memory_service.list_filtered(
        user_id="user_x", tenant_id="alpha",
    )
    beta_list = await memory_service.list_filtered(
        user_id="user_x", tenant_id="beta",
    )
    assert {m.content for m in alpha_list} == {"alpha A"}
    assert {m.content for m in beta_list} == {"beta A"}


async def test_per_tenant_qdrant_collection_exists(palace_app):
    """After a write to a tenant, its Qdrant collection should exist."""
    from palace.memory_service import memory_service
    from palace.vector import vector_store

    await memory_service.create(
        user_id="u1", content="qdrant tenant test", tenant_id="qdrant_test",
    )
    collections = await vector_store.client.get_collections()
    names = {c.name for c in collections.collections}
    assert any("qdrant_test" in n for n in names)


async def test_delete_for_user_scoped_to_tenant(palace_app):
    from palace.memory_service import memory_service

    await memory_service.create(user_id="u_del", content="alpha", tenant_id="alpha")
    await memory_service.create(user_id="u_del", content="beta", tenant_id="beta")

    deleted = await memory_service.delete_for_user(
        user_id="u_del", tenant_id="alpha",
    )
    assert deleted == 1

    alpha_remaining = await memory_service.list_filtered(
        user_id="u_del", tenant_id="alpha",
    )
    beta_remaining = await memory_service.list_filtered(
        user_id="u_del", tenant_id="beta",
    )
    assert len(alpha_remaining) == 0
    assert len(beta_remaining) == 1
