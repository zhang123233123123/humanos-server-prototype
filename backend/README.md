# HumanOS Backend MVP

This backend supports the current HumanOS prototype with:

- user profile persistence;
- task persistence;
- runtime state check-ins;
- context dumps;
- re-entry prompts;
- schedule decisions;
- local embedding-based personalization memory.
- LangGraph multi-agent orchestration for schedule decisions.
- optional DeepSeek refinement for schedule explanations.

It is dependency-free and uses Python standard library + SQLite. The local
embedding model is a deterministic hash embedding (`humanos-local-hash-embedding-v1`)
so the MVP can run without API keys. It can later be replaced with FastAPI and
pgvector/Chroma.

`backend/humanos_graph.py` uses LangGraph's `StateGraph` when `langgraph` is
installed. If the package is not installed, it runs the same Profile -> State ->
Memory -> Scheduler -> Explanation -> Confirmation nodes sequentially so the
prototype remains runnable.

## Run

```bash
backend/.venv/bin/python backend/humanos_server.py
```

Optional LangGraph install:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Optional DeepSeek configuration:

```bash
export DEEPSEEK_API_KEY="..."
export DEEPSEEK_MODEL="deepseek-chat"
```

Do not commit API keys. When `DEEPSEEK_API_KEY` is missing or the provider is
unavailable, the backend keeps using local scheduling rules.

Backend URL:

```text
http://127.0.0.1:8787
```

Frontend prototype:

```text
http://127.0.0.1:8766/prototype/humanos-motion-prototype/index.html
```

When the backend is running, the frontend shows saved/sync status in the
preferences panel and syncs profile/tasks/context dumps to SQLite.

## Data

SQLite database:

```text
backend/data/humanos.db
```

Tables:

```text
profiles
tasks
runtime_states
context_dumps
memories
events
```

The `memories` table stores embedding vectors for profile answers, tasks,
context dumps, and later reflections/user feedback.

## Key APIs

```text
GET  /api/health
POST /api/auth/register
POST /api/auth/login
GET  /api/profile?user_id=demo
PUT  /api/profile?user_id=demo
GET  /api/tasks?user_id=demo
POST /api/tasks?user_id=demo
PATCH /api/tasks/{task_id}
POST /api/state-checkins
POST /api/context-dumps
POST /api/schedules/decide
POST /api/reentry
GET  /api/memories/search?user_id=demo&q=...
```

Authentication is MVP-grade. Register/login returns a `user.id`; the frontend
stores it in localStorage and sends it as `user_id` for profile, task, context,
memory, and scheduling calls. This is enough to test per-user data deposition,
but production should replace it with real sessions/OAuth/JWT.

## Personalization Flow

```text
profile/task/context dump/reflection
  -> local embedding
  -> memories table
  -> semantic retrieval
  -> LangGraph schedule nodes
  -> schedule decision / re-entry prompt
```

Embedding memory does not replace the scheduler. It provides personalized
evidence to the scheduler, such as similar interruptions, previous rejected
plans, and successful re-entry patterns.
