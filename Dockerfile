FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for asyncpg, grpc, bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY mypalace ./mypalace
COPY proto ./proto

RUN pip install --upgrade pip && pip install .

EXPOSE 8000 50051

# Default: HTTP only on :8000.
# Set PALACE_GRPC_PORT=50051 to also start the gRPC server alongside.
CMD ["uvicorn", "mypalace.main:app", "--host", "0.0.0.0", "--port", "8000"]
