"""Phase 5 slice 2 — verify the gRPC RPC_SCOPE map covers every method
exposed by every registered servicer, and that scope assignments mirror
the HTTP scope rules (read for list/get/search/check/format/context;
write for everything mutating)."""

from __future__ import annotations

import pytest

from mypalace.grpc._generated import mypalace_pb2_grpc
from mypalace.grpc.auth_interceptor import RPC_SCOPE

SERVICES = [
    ("MemoryService", mypalace_pb2_grpc.MemoryServiceServicer),
    ("SessionService", mypalace_pb2_grpc.SessionServiceServicer),
    ("EpisodeService", mypalace_pb2_grpc.EpisodeServiceServicer),
    ("ArcService", mypalace_pb2_grpc.ArcServiceServicer),
    ("IntentionService", mypalace_pb2_grpc.IntentionServiceServicer),
    ("DynamicsService", mypalace_pb2_grpc.DynamicsServiceServicer),
    ("RetrievalService", mypalace_pb2_grpc.RetrievalServiceServicer),
    ("IngestionService", mypalace_pb2_grpc.IngestionServiceServicer),
    ("JobService", mypalace_pb2_grpc.JobServiceServicer),
]


def _service_methods(servicer_class) -> list[str]:
    """Return public method names declared on a Servicer base class."""
    return [
        name for name in vars(servicer_class)
        if not name.startswith("_") and callable(vars(servicer_class)[name])
    ]


@pytest.mark.parametrize("svc_name,svc_cls", SERVICES)
def test_every_rpc_has_scope_entry(svc_name, svc_cls):
    """Every RPC declared on a registered servicer must have an entry in
    RPC_SCOPE — otherwise the interceptor falls back to "write" silently."""
    for method in _service_methods(svc_cls):
        full = f"/palace.v1.{svc_name}/{method}"
        assert full in RPC_SCOPE, (
            f"{full} is missing from RPC_SCOPE — add it to "
            "palace/grpc/auth_interceptor.py"
        )
        assert RPC_SCOPE[full] in ("read", "write", "admin")


def test_read_methods_are_read_scope():
    """Smoke check: search/list/get/check/format/recent/active are read."""
    read_substrings = (
        "Search", "List", "Get", "Check", "Format", "Recent", "Active",
        "AssembleLayered",
    )
    for full, scope in RPC_SCOPE.items():
        method = full.rsplit("/", 1)[-1]
        if any(s in method for s in read_substrings):
            assert scope == "read", f"{full} should be 'read' (got {scope})"


def test_mutating_methods_are_write_scope():
    """Create/Delete/Update/Add/Set/Promote/Demote/Score/Supersede/Reflect/
    Synthesize are write."""
    write_prefixes = (
        "Create", "Delete", "Update", "Add", "Set",
        "Promote", "Demote", "ScoreMemory",
        "SupersedeMemory", "ReflectSession", "SynthesizeNarratives",
    )
    for full, scope in RPC_SCOPE.items():
        method = full.rsplit("/", 1)[-1]
        if any(method.startswith(p) for p in write_prefixes):
            assert scope == "write", f"{full} should be 'write' (got {scope})"
