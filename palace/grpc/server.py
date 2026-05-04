"""gRPC server entrypoint.

Run standalone:
    python -m palace.grpc.server

Or wire into the FastAPI lifespan via PALACE_GRPC_PORT (see palace.main).
"""

from __future__ import annotations

import asyncio
import logging

import grpc

from palace.config import settings
from palace.grpc._generated import palace_pb2_grpc
from palace.grpc.auth_interceptor import AuthInterceptor
from palace.grpc.memory_servicer import MemoryServicer

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
    palace_pb2_grpc.add_MemoryServiceServicer_to_server(MemoryServicer(), server)
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
