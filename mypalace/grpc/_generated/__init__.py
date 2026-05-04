"""Generated gRPC stubs. Regenerate via:
    python -m grpc_tools.protoc -I=proto \\
        --python_out=palace/grpc/_generated \\
        --grpc_python_out=palace/grpc/_generated proto/palace.proto

Then re-apply the local import fix in mypalace_pb2_grpc.py:
    s/^import mypalace_pb2/from mypalace.grpc._generated import mypalace_pb2/
"""
