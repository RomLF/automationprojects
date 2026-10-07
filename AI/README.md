# Local LLM Supervisor

Offline local development supervisor for autonomous software projects.

## Architecture

``` text
User
  ↓
Tkinter UI
  ↓
Manager — Qwen 3.5 9B
  ↓
Plan / Approval
  ↓
Coder — Qwen 2.5 Coder
  ↓
Write Files
  ↓
Verify
  ↓
Manager Review
  ↓
Done / Fix
```

## Features

-   Local Ollama-based workflow
-   Tkinter desktop UI
-   Manager planning and approval
-   Coder implementation
-   File-target and path protection
-   Syntax and runtime verification
-   Manager review
-   Automatic fix loop
-   Maximum 5 cycles
-   Local Git checkpoints

## Requirements

-   Windows
-   Python 3
-   Ollama
-   Qwen 3.5 9B
-   Qwen 2.5 Coder

## Run

``` powershell
G:\AI\.venv\Scripts\python.exe supervisor.py
```

Ollama must be running locally.

## Project Structure

``` text
Local-LLM-Supervisor/
├── supervisor.py
├── README.md
├── requirements.txt
├── docs/
│   └── architecture.md
├── projects/
└── .gitignore
```

## Workflow

1.  Create or open a project.
2.  Enter a feature request.
3.  Manager creates a plan.
4.  Revise the plan if needed.
5.  Explicitly approve the plan.
6.  Coder implements the approved targets.
7.  Supervisor verifies the result.
8.  Manager reviews the implementation.
9.  Rejected work goes back to the Coder for fixing.
10. Successful review completes the feature.

## Offline Design

The Supervisor is designed for local development with local Ollama
models and does not require cloud AI services or external APIs.

## Git

Commit the source code and documentation.

Keep generated state, logs, caches, and temporary files out of Git using
`.gitignore`.

## Status

Development baseline for the Local LLM Agents project.
