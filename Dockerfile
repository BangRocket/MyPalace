# Phase 13: multi-stage build — Node stage builds the admin UI; Python
# stage runs the server and serves the built UI from /app/static/admin.

FROM node:24-alpine AS ui-build
WORKDIR /ui
# Cache npm install layer separately from source for fast iterations.
COPY apps/admin-ui/package.json apps/admin-ui/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY apps/admin-ui/ ./
RUN npm run build


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

# Admin UI: built bundle from the ui-build stage. Lives at the path
# mypalace.main._mount_admin_ui() looks for first.
COPY --from=ui-build /ui/dist /app/static/admin

RUN pip install --upgrade pip && pip install .

EXPOSE 8000 50051

# Default: HTTP only on :8000.
# Set PALACE_GRPC_PORT=50051 to also start the gRPC server alongside.
CMD ["uvicorn", "mypalace.main:app", "--host", "0.0.0.0", "--port", "8000"]
