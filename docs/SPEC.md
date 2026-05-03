# Palace Memory Service — SPEC

A standalone, lightweight memory service extracted from mypalclara's Palace memory system.

## Goals
- Store, search, and retrieve memories via REST API
- Semantic search with vector embeddings
- Session + message persistence
- Context assembly for LLM prompts
- Simple, minimal, deployable

## Anti-Goals
- No graph memory (FalkorDB) for v1
- No FSRS spaced repetition for v1
- No reflection/workers for v1
- No gRPC for v1
- No multi-tenancy for v1

---

## Stack
- Python 3.12, FastAPI, uvicorn
- SQLAlchemy 2.0 (async) + asyncpg
- Qdrant (vector store)
- httpx (LLM calls)
- pytest + TestContainers

---

## Data Model

### Memory (PostgreSQL + Qdrant)
```python
class Memory(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    content: str                          # Human-readable memory text
    memory_type: str = "semantic"         # semantic | episodic | preference | fact
    source: str | None = None             # Where it came from
    importance: float = 1.0               # 0.0 - 10.0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    accessed_at: datetime | None = None
    access_count: int = 0
    metadata_json: str | None = None      # JSON string for flexibility
    # Vector is stored in Qdrant, not here
```

### Session (PostgreSQL)
```python
class Session(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    title: str | None = None
    summary: str | None = None
    context_snapshot: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

### Message (PostgreSQL)
```python
class Message(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    session_id: str = Field(foreign_key="session.id", index=True)
    user_id: str = Field(index=True)
    role: str                             # user | assistant | system
    content: str
    created_at: datetime = Field(default_factory=utcnow)
```

---

## API Endpoints

### Health
```
GET  /health
```

### Memories
```
POST /v1/memories              # Create memory
Body: { user_id, content, memory_type?, agent_id?, metadata?, importance? }

POST /v1/memories/search       # Semantic search
Body: { query, user_id?, agent_id?, memory_type?, limit?, min_score? }

GET  /v1/memories/{id}         # Get memory by ID
PATCH /v1/memories/{id}        # Update memory content/metadata
DELETE /v1/memories/{id}       # Delete memory

GET  /v1/users/{user_id}/memories  # List memories for user (recency order)
```

### Sessions
```
POST /v1/sessions              # Create session
Body: { user_id, title? }

GET  /v1/sessions/{id}         # Get session with messages
POST /v1/sessions/{id}/messages    # Add message
Body: { user_id, role, content }

PATCH /v1/sessions/{id}        # Update title/summary
DELETE /v1/sessions/{id}       # Delete session + messages
```

### Context
```
POST /v1/context               # Assemble context for LLM prompt
Body: { user_id, query, max_memories?, max_messages? }
Response: { memories: [...], recent_messages: [...], summary: str? }
```

---

## Architecture

```
palace/
├── __init__.py
├── main.py              # FastAPI app factory
├── config.py            # Pydantic settings (env vars)
├── models.py            # SQLModel tables
├── database.py          # Async engine + session
├── embeddings.py        # Embedding provider (HF or OpenAI)
├── vector.py            # Qdrant client wrapper
├── memory_service.py    # CRUD + search business logic
├── session_service.py   # Session + message logic
├── context_service.py   # Context assembly
├── llm.py               # Minimal LLM client
├── api/
│   ├── __init__.py
│   ├── memories.py      # Memory routes
│   ├── sessions.py      # Session routes
│   └── context.py       # Context routes
└── migrations/          # Alembic (optional for v1)

tests/
├── conftest.py
├── test_memories.py
├── test_sessions.py
└── test_context.py

docker-compose.yml
Dockerfile
pyproject.toml
.env.example
```

---

## Configuration (env vars)

| Var | Default | Description |
|-----|---------|-------------|
| PALACE_DATABASE_URL | postgresql+asyncpg://palace:palace@localhost/palace | Postgres |
| QDRANT_URL | http://localhost:6333 | Qdrant |
| QDRANT_COLLECTION | palace_memories | Collection name |
| EMBEDDING_PROVIDER | huggingface | huggingface or openai |
| EMBEDDING_MODEL | BAAI/bge-large-en-v1.5 | Model name |
| HF_TOKEN | None | HuggingFace token |
| OPENAI_API_KEY | None | OpenAI key (embeddings) |
| LLM_PROVIDER | openrouter | For any LLM ops |
| LLM_API_KEY | None | LLM API key |
| LLM_MODEL | openai/gpt-4o-mini | Default model |
| LOG_LEVEL | INFO | Logging level |

---

## Key Behaviors

### Creating a Memory
1. Generate embedding for `content`
2. Insert into PostgreSQL
3. Store vector in Qdrant with memory_id as point ID

### Searching Memories
1. Generate embedding for `query`
2. Search Qdrant (filtered by user_id / agent_id / memory_type if provided)
3. Fetch full memory records from PostgreSQL by IDs
4. Return ordered by similarity score

### Assembling Context
1. Search memories semantically for the query
2. Fetch recent messages from session (if provided)
3. Return combined context block

### Deleting a Memory
1. Delete from Qdrant by point ID
2. Delete from PostgreSQL

---

## Response Format

All responses wrap in a consistent envelope:
```json
{
  "data": { ... },
  "meta": { "count": 10, "took_ms": 45 }
}
```

Errors:
```json
{
  "error": { "code": "not_found", "message": "Memory not found" }
}
```
