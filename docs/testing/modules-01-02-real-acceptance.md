# Modules 1–2 Real-Machine Acceptance Test

This acceptance test validates the delivered Module 1 and Module 2 behavior on
an actual supported macOS or Ubuntu machine. It uses the real filesystem,
Ollama installation, Docker daemon, Qdrant container, and recommended Qwen
model. It does not substitute fakes for external services.

## Effects on the machine

The runner first asks whether to begin. It then asks separately before each
external change:

- pulling `nomic-embed-text` with Ollama;
- pulling the Qwen model recommended for the detected hardware;
- starting the managed Qdrant Docker Compose service.

Every prompt defaults to **no**. A declined action makes the acceptance result
incomplete rather than passed. Successfully downloaded models, the Qdrant
container, generated configuration, and Qdrant data remain in place so the
machine is ready for normal `repo_intel` use. The runner never removes existing
models, containers, configuration, or data.

The recommended Qwen download may be substantial. Depending on detected memory
and acceleration, it can be `qwen2.5-coder:1.5b`, `qwen2.5-coder:7b`, or
`qwen3-coder:30b`.

## Prerequisites

- Run from the root of a `repo_intel` clone.
- Install `uv`, Git, ripgrep, Ollama, Docker, and the Docker Compose plugin.
- Start Ollama and the Docker daemon before running the acceptance test.
- Ensure ports `127.0.0.1:6333` and `127.0.0.1:6334` are available for the
  managed Qdrant service.
- Allow enough disk space for the embedding and recommended Qwen models.

If a prerequisite is missing, the runner stops with guidance. Repair it and
rerun the same command; completed setup work is intentionally idempotent.

## Run the complete acceptance test

```bash
uv run python scripts/acceptance_modules_01_02.py
```

Answer `y` to begin. To obtain a complete pass, answer `y` to each action that
is not already satisfied on the machine. The underlying `repo-intel setup`
command still receives one explicit action flag at a time; the runner never
uses or adds a global approval option.

## What Module 1 validates

- locked dependency synchronization;
- Ruff lint and formatting;
- strict MyPy checking, including the acceptance runner;
- the complete Pytest suite;
- source-distribution and wheel builds;
- console help, version, and `python -m repo_intel` entry points;
- imports without network access;
- configuration precedence;
- native macOS or Ubuntu application paths.

## What Module 2 validates

- `doctor` creates no state when run against isolated application paths;
- real Git, ripgrep, Ollama, and Docker diagnostics;
- initial `setup --no-input` performs no unapproved external action;
- user configuration is preserved;
- the generated Compose file uses `qdrant/qdrant:v1.19.1`, localhost-only
  ports, and the platform-native Qdrant data path;
- the real `nomic-embed-text` pull and installed-model diagnostic;
- the real hardware-aware Qwen recommendation, pull, and diagnostic;
- real managed Qdrant startup and readiness;
- the running container uses the pinned image, localhost-only runtime port
  bindings, and a storage bind mount;
- final `doctor` success;
- a subsequent setup run changes neither managed files nor external services.

## Result codes

- `0`: every Module 1–2 acceptance check passed.
- `1`: an acceptance assertion or external command failed.
- `2`: the run was cancelled or at least one required live action was declined.
- `130`: the run was interrupted with Ctrl-C.

The successful final line is:

```text
ACCEPTANCE PASSED: Modules 1 and 2 work end to end on this machine.
```

Keep the complete terminal output as the local platform evidence for closing
the Module 2 gate.
