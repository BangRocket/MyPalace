"""Generated gRPC stubs. Regenerate via:
    python -m grpc_tools.protoc -I=proto \\
        --python_out=palace/grpc/_generated \\
        --grpc_python_out=palace/grpc/_generated proto/palace.proto

Then re-apply the local import fix in palace_pb2_grpc.py:
    s/^import palace_pb2/from palace.grpc._generated import palace_pb2/
"""
