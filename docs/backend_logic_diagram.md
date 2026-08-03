# HumanOS Backend Logic

```mermaid
flowchart TD
  A[Frontend/API Request] --> B{Route}

  B -->|Auth| C[Register / Login]
  C --> C1[users table]
  C --> C2[ensure_profile]
  C2 --> C3[profiles table]

  B -->|Task input / Chat| D[parse_tasks_from_text]
  D --> D1[DeepSeek parser if available]
  D --> D2[Local parser fallback]
  D1 --> E[create_task]
  D2 --> E
  E --> E1[Task Dimension / Demand fields]
  E1 --> E2[tasks table]
  E --> E3[Task memory embedding]
  E3 --> M[memories table]

  B -->|Runtime state| F[save_runtime_state]
  F --> F1[runtime_states table]

  B -->|Context dump| G[save_context_dump]
  G --> G1[context_dumps table]
  G --> G2[Update task checkpoints]
  G --> M

  B -->|Schedule decision| H[run_schedule_graph]
  H --> H1[load_profile]
  H1 --> H2[load_task_state]
  H2 --> H3[retrieve_memory]
  H3 --> H4[analyze_inputs]
  H4 --> H4a[Task demand hypotheses]
  H4 --> H4b[Task dependencies]
  H4a --> H5[scheduler_node]
  H4b --> H5

  H5 --> S0[Build scheduling context]
  S0 --> S1[Available windows]
  S0 --> S2[Fixed events]
  S0 --> S3[Temporary constraints]
  S0 --> S4[Flexible activities]
  S0 --> S5[Buffer policy]

  S1 --> P[Generate candidate plans]
  S2 --> P
  S3 --> P
  S4 --> P
  S5 --> P

  P --> P1[energy_fit]
  P --> P2[deadline_first]
  P --> P3[balanced]

  P1 --> V[Validate hard constraints]
  P2 --> V
  P3 --> V

  V --> R[Rank candidates]
  R --> R1[Hard violation count]
  R --> R2[Remaining minutes]
  R --> R3[Daily load spread]
  R1 --> SEL[Select candidate plan]
  R2 --> SEL
  R3 --> SEL

  SEL --> J[Build joint state]
  J --> J1[Task + environment state]
  J --> J2[User state]

  J --> CA[Candidate actions]
  CA --> CA1[accept_feasible_candidate]
  CA --> CA2[repair_partial_schedule]

  CA --> EX[Explanation node]
  EX --> CP[Confirmation policy]
  CP --> DCS[Decision object]
  DCS --> LLM[Optional DeepSeek candidate comparison]
  LLM --> OUT[Return schedule decision]

  B -->|Execution feedback| I[save_execution_feedback]
  I --> I1[execution_feedback table]
  I --> I2[Update task execution_json]
  I --> I3[Calibrate task_demand]
  I --> M

  B -->|State transition| K[record_state_transition]
  K --> K1[state_transitions table]

  B -->|Pattern learning| L[pattern_candidates / promote_pattern]
  M --> L
  L --> L1[learned_patterns in profile]

  OUT --> Z[Frontend pending schedule]
```

## Core Decision Formula

```text
Joint state = task/environment state + user state

Decision =
  analyze inputs
  -> generate candidate plans
  -> validate constraints
  -> compare candidates
  -> select recommendation
  -> require user confirmation
  -> record feedback / transitions after execution
```

## Main Backend Files

- `backend/humanos_server.py`: API routes, SQLite store, task parsing, memory, feedback, state transition, DeepSeek calls.
- `backend/humanos_graph.py`: scheduling graph, candidate-plan generation, validation, candidate selection, confirmation policy.
