"""Tests for the reembed admin route + worker handler (phase 6 slice 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestReembedRoute:
    def test_invalid_tenant_id_returns_400(self, client):
        r = client.post("/v1/admin/reembed", json={
            "tenant_id": "BAD-ID", "model": "x",
        })
        assert r.status_code == 400

    def test_unknown_provider_returns_400(self, client):
        r = client.post("/v1/admin/reembed", json={
            "tenant_id": "test", "provider": "cohere", "model": "x",
        })
        assert r.status_code == 400

    def test_missing_model_returns_422(self, client):
        r = client.post("/v1/admin/reembed", json={"tenant_id": "test"})
        assert r.status_code == 422

    def test_enqueues_reembed_job(self, client, monkeypatch):
        from mypalace.api import reembed as mod

        fake_job = MagicMock()
        fake_job.id = "job-reembed-1"

        with patch.object(mod, "enqueue_job",
                          new=AsyncMock(return_value=fake_job)) as mock_enq:
            r = client.post("/v1/admin/reembed", json={
                "tenant_id": "test",
                "provider": "huggingface",
                "model": "BAAI/bge-large-en-v1.5",
                "batch_size": 50,
            })
        assert r.status_code == 200
        assert r.json()["data"]["job_id"] == "job-reembed-1"

        kwargs = mock_enq.await_args.kwargs
        assert kwargs["kind"] == "reembed"
        assert kwargs["tenant_id"] == "test"
        assert kwargs["payload"]["provider"] == "huggingface"
        assert kwargs["payload"]["model"] == "BAAI/bge-large-en-v1.5"
        assert kwargs["payload"]["batch_size"] == 50

    def test_token_only_in_payload_when_provided(self, client, monkeypatch):
        from mypalace.api import reembed as mod
        fake_job = MagicMock()
        fake_job.id = "job-1"

        with patch.object(mod, "enqueue_job",
                          new=AsyncMock(return_value=fake_job)) as mock_enq:
            r = client.post("/v1/admin/reembed", json={
                "tenant_id": "test", "model": "any",
            })
        assert r.status_code == 200
        assert "token" not in mock_enq.await_args.kwargs["payload"]


class TestReembedHandler:
    def test_handler_registered(self):
        from mypalace.workers.handlers import HANDLER_REGISTRY
        assert "reembed" in HANDLER_REGISTRY

    @pytest.mark.asyncio
    async def test_empty_tenant_returns_zero(self, monkeypatch):
        from mypalace.workers.handlers import _reembed_handler

        fake_embedder = MagicMock()
        fake_embedder.embed = AsyncMock(return_value=[])
        fake_embedder.dim = 384

        # Stub make_embedder so we don't load a real model.
        monkeypatch.setattr(
            "mypalace.workers.handlers.make_embedder",
            lambda *a, **kw: fake_embedder,
        ) if False else None
        # The above contortion doesn't take because the import is local.
        # Instead, patch make_embedder where it's used inside the handler.
        import mypalace.embeddings as emb
        monkeypatch.setattr(emb, "HuggingFaceProvider",
                            lambda *a, **kw: fake_embedder)

        # Stub vector_store.ensure_collection
        from mypalace.vector import vector_store
        monkeypatch.setattr(
            vector_store, "ensure_collection", AsyncMock(),
        )

        # Stub async_session to return no rows ever.
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=empty)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "mypalace.workers.handlers.async_session", MagicMock(return_value=cm),
        ) if False else None
        # Patch where the handler imports it.
        import mypalace.database as dbmod
        monkeypatch.setattr(dbmod, "async_session", MagicMock(return_value=cm))

        result = await _reembed_handler(
            {"provider": "huggingface", "model": "tiny", "batch_size": 50},
            tenant_id="acme",
        )
        assert result["reembedded"] == 0
        assert result["failures"] == 0
        assert result["new_dim"] == 384


class TestMakeEmbedder:
    def test_unknown_provider_raises(self):
        from mypalace.embeddings import make_embedder
        with pytest.raises(ValueError, match="unknown embedding provider"):
            make_embedder("cohere", "x")

    def test_huggingface_dispatch(self, monkeypatch):
        from mypalace import embeddings as emb
        captured: dict = {}

        class FakeHF:
            def __init__(self, model, token=None):
                captured["model"] = model
                captured["token"] = token

        monkeypatch.setattr(emb, "HuggingFaceProvider", FakeHF)
        emb.make_embedder("huggingface", "BAAI/bge-large-en-v1.5", "tok")
        assert captured["model"] == "BAAI/bge-large-en-v1.5"
        assert captured["token"] == "tok"

    def test_openai_dispatch(self, monkeypatch):
        from mypalace import embeddings as emb
        captured: dict = {}

        class FakeOAI:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        monkeypatch.setattr(emb, "OpenAIProvider", FakeOAI)
        emb.make_embedder("openai", "text-embedding-3-small", "sk-...")
        assert captured["model"] == "text-embedding-3-small"
        assert captured["api_key"] == "sk-..."
