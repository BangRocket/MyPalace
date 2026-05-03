# Plan: Standalone MyPalClara Memory Service (Palace)

## Overview

Extract mypalclara's **Palace** memory system into a fully independent, deployable microservice with a clean REST/gRPC API, enabling any application to leverage Clara's sophisticated layered memory architecture without pulling in the entire Discord-bot codebase.

---

## Current Architecture Analysis

### Palace Memory System (Existing)

```
mypalclara/core/memory/           # Memory subsystem
├── core/memory.py                # ClaraMemory class (main interface)
├── vector/                       # Qdrant/pgvector storage
├── graph/                        # FalkorDB relationship graphs
├── embeddings/                   # HuggingFace/OpenAI embedders
├── cache/                        # Redis caching layer
├── context/                      # Context assembly
├── dynamics/                     # FSRS spaced-repetition scoring
├── llm/                          # LLM-powered memory ops
├── episodes.py                   # Episodic memory extraction
├── ingestion.py                  # Smart ingest with dedup
├── intentions.py                 # User intention tracking
├── personality.py                # Personality-linked memory
├── reflection.py                 # Self-reflection on memories
├── retrieval.py                  # Layered retrieval engine
├── retrieval_layers.py           # Retrieval layer orchestration
├── session.py                    # Session management
├── vch.py                        # Verbatim conversation history
├── writer.py                     # Memory write operations
├── entity_resolver.py            # Entity resolution
└── config.py                     # Palace configuration

mypalclara/core/memory_manager.py # Central orchestrator facade
mypalclara/db/models.py           # SQLAlchemy models (Session, Message, etc.)
```

### Dependencies

| Component | Purpose | Required |
|-----------|---------|----------|
| **Qdrant** | Vector store for semantic search | Yes |
| **PostgreSQL** | Relational DB (sessions, messages, metadata) | Yes |
| **Redis** | Embedding cache, performance | No (optional) |
| **FalkorDB** | Knowledge graph / relationship tracking | No (optional) |
| **LLM Provider** | Memory extraction, reflection, summarization | Yes |
| **Embedding Provider** | Vector embeddings (HuggingFace/OpenAI) | Yes |

### Memory Types

1. **Episodic Memory** - Conversation episodes, events, experiences
2. **Semantic Memory** - Facts, preferences, knowledge about users
3. **Procedural Memory** - How-to knowledge, workflows
4. **Verbatim Conversation History (VCH)** - Exact conversation transcripts
5. **Graph Memory** - Relationship networks between entities (optional)

### Key Capabilities

- **Layered Retrieval** - Multi-tier memory search (key → semantic → episodic → graph)
- **Smart Ingestion** - Deduplication, contradiction detection, supersedence
- **FSRS Dynamics** - Spaced-repetition scoring for memory importance
- **Reflection** - LLM-driven periodic memory consolidation
- **Session Management** - Conversation threading with context snapshots
- **Entity Resolution** - Resolving aliases/references to canonical entities

---

## Stage 1: Foundation & Interface Design

**Skill**: `deep-research-swarm` for API design patterns, `vibecoding-general-swarm` for service skeleton

### 1.1 API Design (REST + gRPC)

```
GET    /health                        # Health check
GET    /ready                         # Readiness probe

# Memory Operations
POST   /v1/memories/search            # Semantic search
POST   /v1/memories                   # Store new memory
GET    /v1/memories/{id}              # Retrieve memory
PATCH  /v1/memories/{id}             # Update memory
DELETE /v1/memories/{id}             # Delete memory
POST   /v1/memories/batch            # Batch operations

# Session Management
POST   /v1/sessions                  # Create session
GET    /v1/sessions/{id}             # Get session
PATCH  /v1/sessions/{id}             # Update session
POST   /v1/sessions/{id}/messages    # Add message
GET    /v1/sessions/{id}/messages    # List messages
POST   /v1/sessions/{id}/summarize   # Generate summary

# Context Assembly (for LLM prompts)
POST   /v1/context/assemble          # Build context for LLM prompt
POST   /v1/context/compact           # Compact context window

# Episodic Memory
POST   /v1/episodes                  # Extract episode from messages
GET    /v1/episodes/search           # Search episodes
GET    /v1/episodes/recent           # Recent episodes

# Reflection & Maintenance
POST   /v1/reflection/trigger        # Trigger reflection
GET    /v1/reflection/status         # Reflection status
POST   /v1/maintenance/prune        # Prune old access logs
POST   /v1/maintenance/consolidate  # Consolidate memories

# User Memory Management
GET    /v1/users/{user_id}/memories  # List user memories
DELETE /v1/users/{user_id}/memories  # Clear user memories
GET    /v1/users/{user_id}/stats     # Memory stats per user

# Graph Memory (optional)
POST   /v1/graph/relations           # Add relationship
GET    /v1/graph/relations/{entity}  # Get entity relationships
POST   /v1/graph/query               # Graph query
```

### 1.2 Service Structure

```
palace-service/                    # New standalone repository
├── palace/                        # Main Python package
│   ├── __init__.py
│   ├── api/                       # FastAPI app
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI application factory
│   │   ├── routes/               # API route handlers
│   │   │   ├── __init__.py
│   │   │   ├── memories.py
│   │   │   ├── sessions.py
│   │   │   ├── context.py
│   │   │   ├── episodes.py
│   │   │   ├── reflection.py
│   │   │   ├── users.py
│   │   │   └── graph.py
│   │   ├── middleware/           # Auth, logging, rate limiting
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── logging.py
│   │   │   └── rate_limit.py
│   │   ├── models/               # Pydantic request/response models
│   │   │   ├── __init__.py
│   │   │   ├── memory.py
│   │   │   ├── session.py
│   │   │   ├── context.py
│   │   │   └── common.py
│   │   └── dependencies.py       # FastAPI dependencies (DB, Palace)
│   ├── core/                     # Extracted from mypalclara/core/memory
│   │   ├── __init__.py
│   │   ├── memory.py             # ClaraMemory (extracted & cleaned)
│   │   ├── vector/               # Vector store adapters
│   │   ├── graph/                # Graph store adapters
│   │   ├── embeddings/           # Embedding providers
│   │   ├── cache/                # Caching layer
│   │   ├── retrieval/            # Retrieval engine (merged from retrieval*.py)
│   │   ├── ingestion.py          # Smart ingestion
│   │   ├── episodes.py           # Episodic memory
│   │   ├── reflection.py         # Memory reflection
│   │   ├── dynamics.py           # FSRS scoring
│   │   ├── session.py            # Session management
│   │   ├── writer.py             # Memory writes
│   │   ├── entity_resolver.py    # Entity resolution
│   │   ├── vch.py                # Verbatim conversation history
│   │   ├── intentions.py         # Intention tracking
│   │   └── personality.py        # Personality memory
│   ├── db/                       # Database layer
│   │   ├── __init__.py
│   │   ├── base.py               # SQLAlchemy base
│   │   ├── models.py             # Extracted from mypalclara/db/models.py
│   │   ├── connection.py         # DB connection management
│   │   └── migrations/           # Alembic migrations
│   │       ├── env.py
│   │       ├── alembic.ini
│   │       └── versions/
│   ├── config/                   # Configuration
│   │   ├── __init__.py
│   │   ├── settings.py           # Pydantic Settings (env vars)
│   │   └── logging.py            # Structured logging
│   ├── proto/                    # gRPC definitions
│   │   ├── palace.proto          # Service definition
│   │   └── generated/            # Generated Python code
│   ├── llm/                      # LLM client (minimal, extracted)
│   │   ├── __init__.py
│   │   ├── client.py             # Unified LLM client
│   │   └── providers.py          # Provider configurations
│   └── workers/                  # Background task processors
│       ├── __init__.py
│       ├── reflection_worker.py  # Periodic reflection
│       ├── ingestion_worker.py   # Async ingestion queue
│       └── maintenance_worker.py # Cleanup tasks
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── scripts/
│   ├── migrate_from_mypalclara.py  # Data migration from mypalclara
│   └── benchmark.py               # Performance benchmarking
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   └── entrypoint.sh
├── k8s/                          # Kubernetes manifests
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   └── ingress.yaml
├── docker-compose.yml            # Local development stack
├── docker-compose.prod.yml       # Production stack
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md               # Detailed architecture docs
├── CHANGELOG.md
├── Makefile                      # Common commands
└── .env.example
```

### 1.3 Deliverables

- [ ] OpenAPI 3.0 specification (`docs/openapi.yaml`)
- [ ] Protocol Buffers definition (`palace/proto/palace.proto`)
- [ ] Project skeleton with working FastAPI app
- [ ] Docker Compose for local dev (Qdrant + PostgreSQL + Redis + Palace)
- [ ] Configuration system with Pydantic Settings

---

## Stage 2: Core Extraction & Refactoring

**Skill**: `vibecoding-general-swarm`

### 2.1 Extract Memory Core

Port from `mypalclara/core/memory/` → `palace/core/`

| Source File | Destination | Action |
|-------------|-------------|--------|
| `core/memory.py` | `palace/core/memory.py` | Extract ClaraMemory class, remove mypalclara imports |
| `vector/` | `palace/core/vector/` | Port Qdrant/pgvector adapters |
| `graph/` | `palace/core/graph/` | Port FalkorDB adapter |
| `embeddings/` | `palace/core/embeddings/` | Port HuggingFace/OpenAI embedders |
| `cache/` | `palace/core/cache/` | Port Redis cache |
| `retrieval.py` + `retrieval_layers.py` | `palace/core/retrieval/` | Merge into unified retrieval engine |
| `episodes.py` | `palace/core/episodes.py` | Port with cleaned interfaces |
| `ingestion.py` | `palace/core/ingestion.py` | Port smart ingestion |
| `reflection.py` | `palace/core/reflection.py` | Port reflection engine |
| `dynamics/` | `palace/core/dynamics.py` | Port FSRS dynamics |
| `session.py` | `palace/core/session.py` | Port session management |
| `writer.py` | `palace/core/writer.py` | Port memory writer |
| `vch.py` | `palace/core/vch.py` | Port verbatim history |
| `entity_resolver.py` | `palace/core/entity_resolver.py` | Port entity resolver |
| `config.py` | `palace/config/settings.py` | Convert to Pydantic Settings |

### 2.2 Extract Database Layer

Port from `mypalclara/db/` → `palace/db/`

| Source | Destination | Action |
|--------|-------------|--------|
| `db/base.py` | `palace/db/base.py` | SQLAlchemy Base |
| `db/models.py` | `palace/db/models.py` | Extract memory-relevant models only |
| `db/connection.py` | `palace/db/connection.py` | Async connection pool |

**Models to include**:
- `Project` - Project/workspace scoping
- `Session` - Conversation sessions
- `Message` - Individual messages
- `MemoryItem` - Memory entries (new - was in Palace vector store)
- `MemoryDynamics` - FSRS tracking
- `MemoryAccessLog` - Access tracking
- `Episode` - Episodic memory records
- `UserIdentity` - User profiles (minimal)

### 2.3 Extract Minimal LLM Client

Create a lightweight LLM client in `palace/llm/`:

```python
# palace/llm/client.py - Minimal async LLM interface
class LLMClient:
    async def complete(self, messages, model=None, **kwargs) -> str
    async def embed(self, texts, model=None) -> list[list[float]]
```

Support providers: OpenRouter, Anthropic, OpenAI, Custom OpenAI-compatible

### 2.4 Decouple from mypalclara

**Remove dependencies on**:
- `mypalclara.config.logging` → Use structlog or standard logging
- `mypalclara.core.llm.*` → Use `palace.llm.*`
- `mypalclara.db.*` → Use `palace.db.*`
- Discord-specific code → Remove or generalize
- Gateway-specific code → Replace with service API

### 2.5 Deliverables

- [ ] All core modules extracted and tests passing
- [ ] Zero imports from `mypalclara.*` namespace
- [ ] Async-first API (all DB operations use async SQLAlchemy)
- [ ] Type hints throughout
- [ ] Unit tests for each core module (≥80% coverage)

---

## Stage 3: API Implementation

**Skill**: `vibecoding-general-swarm`

### 3.1 REST API Routes

Implement all endpoints from Stage 1.1 using FastAPI:

```python
# palace/api/main.py
from fastapi import FastAPI
from palace.api.routes import memories, sessions, context, episodes, users, graph

app = FastAPI(title="Palace Memory Service", version="1.0.0")
app.include_router(memories.router, prefix="/v1/memories")
app.include_router(sessions.router, prefix="/v1/sessions")
# ... etc
```

### 3.2 Authentication & Authorization

```python
# palace/api/middleware/auth.py

# Strategy: API Key + optional JWT
# - X-API-Key header for service-to-service auth
# - Optional Bearer JWT for user-scoped requests
# - Rate limiting per API key
```

### 3.3 Background Workers

```python
# palace/workers/reflection_worker.py
# Periodic memory reflection (configurable interval)

# palace/workers/ingestion_worker.py  
# Async memory ingestion queue (Celery or arq)

# palace/workers/maintenance_worker.py
# Access log pruning, old memory cleanup
```

### 3.4 gRPC Service (Optional Phase 2)

```protobuf
// palace/proto/palace.proto
service Palace {
  rpc SearchMemories(SearchRequest) returns (SearchResponse);
  rpc StoreMemory(StoreRequest) returns (Memory);
  rpc GetContext(ContextRequest) returns (ContextResponse);
  rpc StreamMemoryUpdates(StreamRequest) returns (stream MemoryUpdate);
}
```

### 3.5 Deliverables

- [ ] Full REST API implemented with FastAPI
- [ ] OpenAPI docs auto-generated at `/docs`
- [ ] Authentication middleware (API key + JWT)
- [ ] Rate limiting
- [ ] Request/response validation with Pydantic
- [ ] Structured logging (JSON)
- [ ] Prometheus metrics endpoint (`/metrics`)
- [ ] Health/readiness probes

---

## Stage 4: Data Migration & Backwards Compatibility

### 4.1 Migration Script

```python
# scripts/migrate_from_mypalclara.py
"""One-way migration from mypalclara to standalone Palace."""

# 1. Read from mypalclara PostgreSQL
# 2. Transform to Palace schema
# 3. Write to Palace PostgreSQL + Qdrant
# 4. Verify consistency
```

### 4.2 mypalclara Adapter

Create a compatibility adapter so mypalclara can use the standalone Palace service:

```python
# In mypalclara repo: mypalclara/core/memory/client.py
class PalaceMemoryClient:
    """Drop-in replacement for ClaraMemory that calls Palace service."""
    
    def __init__(self, base_url: str, api_key: str):
        self.client = httpx.AsyncClient(base_url=base_url, headers={"X-API-Key": api_key})
    
    async def search(self, query: str, user_id: str, **kwargs) -> list[Memory]:
        resp = await self.client.post("/v1/memories/search", json={"query": query, "user_id": user_id, **kwargs})
        return [Memory(**m) for m in resp.json()["memories"]]
    
    async def add(self, messages: list[Message], user_id: str, **kwargs):
        await self.client.post("/v1/memories", json={"messages": [...], "user_id": user_id, **kwargs})
    
    # ... implement all ClaraMemory methods as HTTP calls
```

### 4.3 Deliverables

- [ ] Migration script with dry-run mode
- [ ] Data validation/verification post-migration
- [ ] mypalclara PalaceClient adapter
- [ ] Migration guide documentation

---

## Stage 5: Infrastructure & Deployment

**Skill**: `vibecoding-general-swarm`

### 5.1 Docker Images

```dockerfile
# Multi-stage build
FROM python:3.12-slim as builder
# Install dependencies

FROM python:3.12-slim as runtime
# Copy built artifacts
# Run with uvicorn

EXPOSE 8000
CMD ["uvicorn", "palace.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 5.2 Kubernetes Manifests

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: palace-memory
spec:
  replicas: 2  # Horizontally scalable (stateless)
  template:
    spec:
      containers:
      - name: palace
        image: palace-memory:latest
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: palace-secrets
              key: database-url
        - name: QDRANT_URL
          valueFrom:
            configMapKeyRef:
              name: palace-config
              key: qdrant-url
```

### 5.3 Helm Chart (Optional)

```
helm/palace-memory/
├── Chart.yaml
├── values.yaml
├── values-production.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── configmap.yaml
    ├── secret.yaml
    ├── hpa.yaml          # HorizontalPodAutoscaler
    └── pdb.yaml          # PodDisruptionBudget
```

### 5.4 Terraform (Optional)

```hcl
# terraform/main.tf
# Deploy to AWS/GCP/Azure with managed:
# - PostgreSQL (RDS/Cloud SQL)
# - Redis (ElastiCache/Memorystore)
# - Qdrant (EKS/GKE or managed vector DB)
```

### 5.5 Deliverables

- [ ] Production Dockerfile (multi-stage, minimal)
- [ ] docker-compose.yml for local development
- [ ] docker-compose.prod.yml for production
- [ ] Kubernetes manifests (deployment, service, ingress, HPA)
- [ ] Helm chart
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Terraform modules (optional)

---

## Stage 6: Testing & Hardening

### 6.1 Test Suite

```
tests/
├── unit/                          # Isolated unit tests
│   ├── core/
│   │   ├── test_memory.py
│   │   ├── test_retrieval.py
│   │   ├── test_ingestion.py
│   │   ├── test_reflection.py
│   │   ├── test_session.py
│   │   └── test_dynamics.py
│   ├── api/
│   │   ├── test_memories_routes.py
│   │   ├── test_sessions_routes.py
│   │   └── test_auth.py
│   └── db/
│       └── test_models.py
├── integration/                   # Integration tests
│   ├── test_memory_lifecycle.py   # Full CRUD flow
│   ├── test_context_assembly.py   # Context building
│   ├── test_migration.py          # Data migration
│   └── test_concurrent_access.py  # Race conditions
├── load/                          # Performance tests
│   └── locustfile.py              # Locust load tests
├── e2e/                           # End-to-end tests
│   └── test_full_workflow.py
└── conftest.py                    # Shared fixtures (test DB, etc.)
```

### 6.2 Performance Targets

| Metric | Target |
|--------|--------|
| Memory search (p99) | < 200ms |
| Memory store (p99) | < 300ms |
| Context assembly | < 500ms |
| Concurrent users | 1000+ |
| Memories stored | 10M+ |

### 6.3 Deliverables

- [ ] ≥85% unit test coverage
- [ ] Integration tests for all API endpoints
- [ ] Load tests with Locust
- [ ] Chaos engineering tests (kill DB, network partitions)
- [ ] Security audit (OWASP Top 10)
- [ ] Benchmark report

---

## Stage 7: Documentation & SDK

**Skill**: `report-writing`

### 7.1 Documentation

```
docs/
├── README.md                      # Quick start
├── getting-started.md             # Tutorial
├── api-reference.md               # Auto-generated from OpenAPI
├── architecture.md                # System design
├── configuration.md               # Env vars & tuning
├── deployment.md                  # Deploy options
├── migration.md                   # From mypalclara
├── sdk/
│   ├── python.md                  # Python SDK
│   ├── javascript.md              # JS/TS SDK
│   └── go.md                      # Go SDK
└── contributing.md                # Contributor guide
```

### 7.2 SDKs

```python
# Python SDK: pip install palace-memory
from palace import PalaceClient

client = PalaceClient(api_key="pk_...", base_url="https://palace.example.com")

# Store a memory
memory = await client.memories.store(
    content="User prefers dark mode",
    user_id="user-123",
    memory_type="preference",
    metadata={"category": "ui", "confidence": 0.95}
)

# Search memories
results = await client.memories.search(
    query="user interface preferences",
    user_id="user-123",
    limit=10
)

# Build context for LLM
context = await client.context.assemble(
    user_id="user-123",
    query="What does the user like?",
    max_tokens=4000
)
```

```typescript
// JS/TS SDK: npm install @palace/memory
import { PalaceClient } from '@palace/memory';

const client = new PalaceClient({ apiKey: 'pk_...', baseUrl: 'https://palace.example.com' });

const memories = await client.memories.search({
  query: 'project requirements',
  userId: 'user-123',
  limit: 10
});
```

### 7.3 Deliverables

- [ ] Complete API documentation
- [ ] Python SDK (`palace-memory` on PyPI)
- [ ] TypeScript/JavaScript SDK (`@palace/memory` on npm)
- [ ] Interactive API playground
- [ ] Architecture decision records (ADRs)

---

## Stage 8: mypalclara Integration

### 8.1 Adapter Implementation

In the mypalclara repo, create a Palace service adapter:

```python
# mypalclara/core/memory/palace_client.py
"""Palace Memory Service client - drop-in replacement for embedded ClaraMemory."""

from mypalclara.core.memory import PALACE  # Existing embedded

class PalaceServiceClient:
    """Client for standalone Palace memory service."""
    
    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=30.0
        )
    
    # Implement ClaraMemory interface
    async def search(self, query, user_id=None, agent_id=None, **kwargs):
        ...
    
    async def add(self, messages, user_id=None, agent_id=None, **kwargs):
        ...
    
    async def get_context(self, user_id, query, **kwargs):
        ...

# Configuration toggle
USE_PALACE_SERVICE = os.getenv("USE_PALACE_SERVICE", "false").lower() == "true"
PALACE_SERVICE_URL = os.getenv("PALACE_SERVICE_URL", "http://localhost:8000")
PALACE_API_KEY = os.getenv("PALACE_API_KEY", "")

def get_memory_client():
    if USE_PALACE_SERVICE:
        return PalaceServiceClient(PALACE_SERVICE_URL, PALACE_API_KEY)
    return PALACE  # Embedded fallback
```

### 8.2 Configuration

Add to mypalclara's `.env`:

```bash
# Palace Memory Service (standalone)
USE_PALACE_SERVICE=false           # Toggle embedded vs standalone
PALACE_SERVICE_URL=http://palace:8000
PALACE_API_KEY=pk_your_key_here
```

### 8.3 Deliverables

- [ ] `PalaceServiceClient` in mypalclara
- [ ] Feature parity with embedded Palace
- [ ] Graceful fallback (embedded → service → degraded)
- [ ] Updated docker-compose with Palace service

---

## Stage 9: Advanced Features (Future)

### 9.1 Multi-Tenancy

- Namespace isolation per tenant
- Per-tenant resource quotas
- Tenant-specific embedding models

### 9.2 Federated Memory

- Cross-instance memory sharing
- Memory federation protocol
- Privacy-preserving shared knowledge

### 9.3 Memory Marketplace

- Pre-built memory packs (domain knowledge)
- Memory import/export standard format
- Community sharing

### 9.4 Real-time Sync

- WebSocket subscriptions for memory updates
- Server-sent events for live context
- Multi-device synchronization

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| API Framework | FastAPI (async) |
| Database | PostgreSQL 16 + asyncpg |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Vector DB | Qdrant |
| Cache | Redis (optional) |
| Graph DB | FalkorDB (optional) |
| Message Queue | Celery + Redis or arq |
| LLM Client | httpx + provider-specific SDKs |
| Embeddings | sentence-transformers / OpenAI |
| Auth | API Key + JWT (optional) |
| Metrics | Prometheus + `prometheus-client` |
| Logging | structlog |
| Testing | pytest + httpx + TestContainers |
| Load Testing | Locust |
| Docs | MkDocs + Material |
| CI/CD | GitHub Actions |
| Packaging | uv / poetry |

---

## Execution Timeline

| Stage | Duration | Dependencies |
|-------|----------|--------------|
| 1. Foundation & API Design | 3-4 days | - |
| 2. Core Extraction & Refactoring | 7-10 days | Stage 1 |
| 3. API Implementation | 5-7 days | Stage 2 |
| 4. Data Migration & Compatibility | 3-4 days | Stage 3 |
| 5. Infrastructure & Deployment | 3-4 days | Stage 3 |
| 6. Testing & Hardening | 5-7 days | Stage 5 |
| 7. Documentation & SDK | 4-5 days | Stage 3 |
| 8. mypalclara Integration | 3-4 days | Stage 3 |
| **Total** | **33-45 days** | |

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Tight coupling in mypalclara | High | Careful extraction, adapter pattern |
| Data migration complexity | Medium | Migration script with dry-run, validation |
| Performance regression | High | Benchmark suite, load testing |
| Schema divergence | Medium | Versioned API, migration scripts |
| LLM provider changes | Low | Unified LLM client abstraction |
