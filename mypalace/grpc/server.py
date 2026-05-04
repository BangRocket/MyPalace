"""gRPC server entrypoint.

Run standalone:
    python -m palace.grpc.server

Or wire into the FastAPI lifespan via PALACE_GRPC_PORT (see palace.main).
"""

from __future__ import annotations

import asyncio
import logging

import grpc

from mypalace.config import settings
from mypalace.grpc._generated import mypalace_pb2_grpc
from mypalace.grpc.arc_servicer import ArcServicer
from mypalace.grpc.auth_interceptor import AuthInterceptor
from mypalace.grpc.dynamics_servicer import DynamicsServicer
from mypalace.grpc.episode_servicer import EpisodeServicer
from mypalace.grpc.ingestion_servicer import IngestionServicer
from mypalace.grpc.intention_servicer import IntentionServicer
from mypalace.grpc.job_servicer import JobServicer
from mypalace.grpc.memory_servicer import MemoryServicer
from mypalace.grpc.retrieval_servicer import RetrievalServicer
from mypalace.grpc.session_servicer import SessionServicer

logger = logging.getLogger(__name__)


async def serve(port: int | None = None) -> grpc.aio.Server:
    """Start a gRPC server on ``port`` (or settings.grpc_port).

    Returns the running server so callers can `await server.wait_for_termination()`
    or trigger graceful shutdown.
    """
    port = port or settings.grpc_port
    if port is None:
        raise RuntimeError("gRPC port not configured (set PALACE_GRPC_PORT)")

    server = grpc.aio.server(interceptors=[AuthInterceptor()])
    mypalace_pb2_grpc.add_MemoryServiceServicer_to_server(MemoryServicer(), server)
    mypalace_pb2_grpc.add_SessionServiceServicer_to_server(SessionServicer(), server)
    mypalace_pb2_grpc.add_EpisodeServiceServicer_to_server(EpisodeServicer(), server)
    mypalace_pb2_grpc.add_ArcServiceServicer_to_server(ArcServicer(), server)
    mypalace_pb2_grpc.add_IntentionServiceServicer_to_server(IntentionServicer(), server)
    mypalace_pb2_grpc.add_DynamicsServiceServicer_to_server(DynamicsServicer(), server)
    mypalace_pb2_grpc.add_RetrievalServiceServicer_to_server(RetrievalServicer(), server)
    mypalace_pb2_grpc.add_IngestionServiceServicer_to_server(IngestionServicer(), server)
    mypalace_pb2_grpc.add_JobServiceServicer_to_server(JobServicer(), server)
    addr = f"{settings.grpc_host}:{port}"
    server.add_insecure_port(addr)
    await server.start()
    logger.info("Palace gRPC server listening on %s", addr)
    return server


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = await serve()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
