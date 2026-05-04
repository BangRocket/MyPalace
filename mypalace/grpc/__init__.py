"""gRPC transport (phase 3 slice 5). MemoryService only this slice;
other surfaces ride HTTP for now and will land here in phase 4."""

from mypalace.grpc.server import serve

__all__ = ["serve"]
