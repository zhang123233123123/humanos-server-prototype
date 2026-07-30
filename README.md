# HumanOS Server Prototype

This repository contains the standalone HumanOS prototype currently served at:

`http://152.42.184.52:8766/index.html`

## Structure

```text
frontend/
  index.html
  app.js
  styles.css
  assets/diagrams/HumanOS_computational_scheduling_interactive.html

backend/
  humanos_server.py
  humanos_graph.py
  requirements.txt
  README.md
```

## Server Source Mapping

```text
/root/humanos-app/frontend  ->  frontend/
/root/humanos-app/backend   ->  backend/
```

Excluded from this repository:

```text
backend/.env
backend/data/
backend/.venv/
__pycache__/
logs/
```

## Local Run

Backend:

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python humanos_server.py
```

Frontend:

```bash
cd frontend
python3 -m http.server 8766
```

Open:

`http://127.0.0.1:8766/index.html`

## Environment

Create `backend/.env` locally if you want LLM-backed parsing:

```text
DEEPSEEK_API_KEY=your_key_here
DEEPSEEK_MODEL=deepseek-chat
```

Without a key, the backend falls back to local rule-based parsing.
