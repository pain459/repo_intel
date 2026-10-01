# repo_intel

`repo_intel` is a local-first repository knowledge and navigation engine for
coding agents. It is designed to find a small, traceable evidence set for an
engineering task instead of placing an entire repository in a model context.

The project is under active development. Module 1 establishes the package,
CLI contracts, typed configuration, platform paths, and service interfaces.
Repository indexing begins in later modules.

## Supported platforms

- macOS
- Ubuntu Linux
- Python 3.12 or newer

Other Linux distributions are not part of the first-release test matrix.

## Prerequisite

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) before
cloning the project. `uv` manages the Python environment and locked project
dependencies.

## Clone and install

```bash
git clone <repository-url>
cd repo_intel
uv sync --locked --all-groups
```

## Smoke checks

```bash
uv run repo-intel --help
uv run repo-intel version
uv run python -m repo_intel --help
```

Module 1 imports and smoke commands do not require or contact Ollama, Docker,
or Qdrant. Later modules add explicit, confirmed setup for those local
services.

## Development checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/repo_intel tests
uv run pytest -q
uv build
```

The same checks run on macOS and Ubuntu in GitHub Actions.

## Design and execution references

- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) describes the long-term product vision.
- [`docs/design/repo-intel-v1-design.md`](docs/design/repo-intel-v1-design.md)
  defines the approved first-release architecture.
- [`docs/plans/repo-intel-v1-execution-plan.md`](docs/plans/repo-intel-v1-execution-plan.md)
  tracks module status and decisions.
