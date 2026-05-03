# Palace Memory Service

A standalone memory service for AI assistants, extracted from [mypalclara](https://github.com/BangRocket/mypalclara)'s Palace memory system.

## Quick Start

```bash
# 1. Start PostgreSQL + Qdrant
docker-compose up -d postgres qdrant

# 2. Install dependencies (Python 3.12+)
pip install -e ".[dev]"

# 3. Copy env vars
cp .env.example .env

# 4. Run the server
uvicorn palace.main:app --reload --port 8000
```

Or everything in Docker:

```bash
docker-compose up --build
```

## API

```
GET    /health

POST   /v1/memories              # Store a memory
POST   /v1/memories/search       # Semantic search
GET    /v1/memories/{id}         # Retrieve memory
PATCH  /v1/memories/{id}         # Update memory
DELETE /v1/memories/{id}         # Delete memory
GET    /v1/users/{user_id}/memories

POST   /v1/sessions              # Create session
GET    /v1/sessions/{id}         # Get session + messages
POST   /v1/sessions/{id}/messages
PATCH  /v1/sessions/{id}
DELETE /v1/sessions/{id}

POST   /v1/context               # Assemble context for LLM prompts
```

## Project Structure

```
palace/
  config.py          # Settings (env vars)
  models.py          # Memory, Session, Message tables
  database.py        # Async SQLAlchemy engine
  embeddings.py      # HuggingFace / OpenAI embedders
  vector.py          # Qdrant vector store
  llm.py             # Async LLM client
  memory_service.py  # CRUD + semantic search
  session_service.py # Session + message management
  context_service.py # Context assembly for prompts
  api/
    common.py        # Pydantic request/response models
    memories.py      # Memory routes
    sessions.py      # Session routes
    context.py       # Context routes
  main.py            # FastAPI app factory
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PALACE_DATABASE_URL` | `postgresql+asyncpg://palace:palace@localhost/palace` | Postgres connection |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant vector store |
| `EMBEDDING_PROVIDER` | `huggingface` | `huggingface` or `openai` |
| `EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | Embedding model |
| `LLM_PROVIDER` | `openrouter` | LLM provider for any LLM ops |
| `LLM_MODEL` | `openai/gpt-4o-mini` | Default LLM model |

## Tests

```bash
pytest
```

## License

PolyForm Noncommercial 1.0.0
