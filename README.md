# repo_intel

`repo_intel` is a local-first repository knowledge and navigation engine for
coding agents. It is designed to find a small, traceable evidence set for an
engineering task instead of placing an entire repository in a model context.

The project is under active development. Modules 1 through 3 provide the
Python package, stable CLI, platform-aware local setup, read-only diagnostics,
hardware-aware Qwen recommendations, and safe local project registration and
cleanup. Repository indexing begins in later modules.

## Supported platforms

- macOS
- Ubuntu Linux
- Python 3.12 or newer

Other Linux distributions are not part of the first-release test matrix.

## Prerequisites

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) before
setting up the Python environment. A complete local runtime also uses Git,
ripgrep, Ollama, and Docker with the Docker Compose plugin.

`repo_intel` does not install system software. `doctor` reports missing
dependencies and prints platform-specific guidance so you remain in control of
system changes.

## Clone and install

```bash
git clone <repository-url>
cd repo_intel
uv sync --locked --all-groups
```

Inspect the machine before changing anything:

```bash
uv run repo-intel doctor
```

`doctor` is read-only. It checks Git, ripgrep, Ollama, Docker, Qdrant,
`nomic-embed-text`, and the recommended Qwen model. It distinguishes missing
dependencies from stopped and unhealthy services. Exit code `5` means a
required dependency is missing; exit code `7` means a required local service
is stopped or unhealthy.

## Safe setup

Run interactive setup after reviewing `doctor`:

```bash
uv run repo-intel setup
```

Setup always prepares deterministic application-owned configuration and a
pinned Qdrant Compose file. Every external action is proposed separately and
defaults to “no”. There is deliberately no global `--yes` option.

Explicit flags approve only their named action:

```bash
# Pull the required embedding model if it is missing.
uv run repo-intel setup --no-input --pull-embedding

# Pull the model recommended for this machine if it is missing.
uv run repo-intel setup --no-input --pull-qwen

# Start the managed Qdrant service if it is stopped.
uv run repo-intel setup --no-input --start-qdrant
```

`--no-input` declines every action that does not have its own explicit flag.
Declining or cancelling is successful and leaves those external services
unchanged. Re-running setup preserves user configuration, updates only the
managed Compose file when necessary, and does nothing when the current state
is already correct.

To exercise the full manual flow:

```bash
uv run repo-intel doctor
uv run repo-intel setup --no-input
uv run repo-intel setup --no-input --pull-embedding
uv run repo-intel setup --no-input --pull-qwen
uv run repo-intel setup --no-input --start-qdrant
uv run repo-intel setup --no-input
uv run repo-intel doctor
```

Model pulls can be large. Each pull requires its own prompt confirmation or
explicit flag. Qdrant startup likewise requires its own confirmation or flag.

## Model recommendation policy

Setup inspects memory, architecture, and supported acceleration when the host
exposes them reliably:

| Detected hardware | Recommendation |
|---|---|
| Less than 16 GiB memory | `qwen2.5-coder:1.5b` |
| 16 through 47 GiB memory | `qwen2.5-coder:7b` |
| At least 48 GiB plus Apple Metal or NVIDIA CUDA | `qwen3-coder:30b` |

Unknown memory falls back to `qwen2.5-coder:1.5b`. At least 48 GiB without a
confirmed supported accelerator falls back to `qwen2.5-coder:7b`. Both cases
are labelled uncertain. Qwen is optional for deterministic v1 indexing and
retrieval; `nomic-embed-text` is required for semantic indexing.

## Local files and services

On macOS, state is placed below the normal user Library locations:

- configuration: `~/Library/Application Support/repo-intel/config`
- generated data: `~/Library/Application Support/repo-intel/data`
- cache: `~/Library/Caches/repo-intel`
- logs: `~/Library/Logs/repo-intel`

On Ubuntu, XDG locations are honored, with these defaults:

- configuration: `~/.config/repo-intel`
- generated data: `~/.local/share/repo-intel`
- cache: `~/.cache/repo-intel`
- logs: `~/.local/state/repo-intel/log`

The user configuration is `config.toml`. The managed service definition is
`qdrant.compose.yaml`, pinned to `qdrant/qdrant:v1.19.1`. Qdrant storage is
under the platform data directory. Its REST and gRPC ports bind only to
`127.0.0.1:6333` and `127.0.0.1:6334`.

## Project lifecycle

Register the current Git worktree, or an explicit repository path:

```bash
uv run repo-intel init
uv run repo-intel init /path/to/repository
```

Registration follows Git worktrees from nested, spaced, Unicode, and symlink
alias paths. It stores a stable UUID in a global SQLite registry and never
writes an identifier or marker into the source repository or its `.git`
directory. Repeating `init` for the same repository returns the existing UUID
and repairs an interrupted initialization.

List registrations and inspect one by path or UUID:

```bash
uv run repo-intel projects
uv run repo-intel status
uv run repo-intel status /path/to/repository
uv run repo-intel status --project-id PROJECT_UUID
```

Path and `--project-id` selectors are mutually exclusive. UUID selection keeps
a moved or missing repository manageable. If a repository moves on the same
machine, refresh its canonical path explicitly while preserving its UUID and
generated allocations:

```bash
uv run repo-intel projects relocate PROJECT_UUID /new/repository/path
```

If the old path contains a different Git repository, status reports it as
`reused`; it is never silently attached to the old registration. Use the UUID
to inspect, relocate, or remove the original registration.

Preview cleanup before approving it:

```bash
uv run repo-intel remove --project-id PROJECT_UUID --dry-run
uv run repo-intel remove /path/to/repository --dry-run
```

The preview prints every provider, exact resource identifier, existence state,
and action without prompting or changing state. Normal removal prints the same
plan and asks for confirmation that defaults to no. `--force` skips only that
prompt; it preserves target validation, provider execution, progress tracking,
and failure exit codes. `--dry-run` and `--force` cannot be combined.

```bash
uv run repo-intel remove --project-id PROJECT_UUID
uv run repo-intel remove --project-id PROJECT_UUID --force
```

Cleanup is provider-based and retryable. Completed providers are skipped on a
retry, newly introduced providers are added, and the registration remains
until every recorded provider completes. Use `--project-id` to recover cleanup
when the source path is moved, missing, reused, or initialization stopped
partway through. Only repo-intel-owned UUID directories are removed; source
files, Git metadata, the global registry, and `.repo-intel.toml` are never
cleanup targets.

Project state uses these platform-native locations:

| Platform | Registry | Project data | Project cache | Project logs |
|---|---|---|---|---|
| macOS | `~/Library/Application Support/repo-intel/data/registry.sqlite3` | `~/Library/Application Support/repo-intel/data/projects/<uuid>` | `~/Library/Caches/repo-intel/projects/<uuid>` | `~/Library/Logs/repo-intel/projects/<uuid>` |
| Ubuntu | `~/.local/share/repo-intel/registry.sqlite3` | `~/.local/share/repo-intel/projects/<uuid>` | `~/.cache/repo-intel/projects/<uuid>` | `~/.local/state/repo-intel/log/projects/<uuid>` |

Ubuntu honors `XDG_DATA_HOME`, `XDG_CACHE_HOME`, and `XDG_STATE_HOME` in place
of those defaults.

## Troubleshooting

- If `doctor` reports a missing program, follow its macOS or Ubuntu guidance;
  setup will not invoke a package manager for you.
- If Ollama is stopped, start it normally and rerun `doctor` before approving
  model pulls.
- If Docker is stopped or unhealthy, restore Docker daemon access before
  approving Qdrant startup.
- If Qdrant is stopped, run `setup --no-input --start-qdrant`; if it is
  unhealthy, inspect the local container and rerun `doctor`.
- If a model pull or service start fails offline, restore connectivity or the
  local service and rerun setup. Completed actions are not repeated.
- Paths containing spaces and Unicode are supported; do not move generated
  files into the source repository.

## Smoke checks

```bash
uv run repo-intel --help
uv run repo-intel setup --help
uv run repo-intel doctor --help
uv run repo-intel init --help
uv run repo-intel projects --help
uv run repo-intel projects relocate --help
uv run repo-intel status --help
uv run repo-intel remove --help
uv run repo-intel version
uv run python -m repo_intel --help
```

Help, version, and package imports do not contact Ollama, Docker, or Qdrant.

## Development checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/repo_intel tests scripts
uv run pytest -q
uv build
```

The same checks and fake-backed setup/doctor acceptance workflows run on macOS
and Ubuntu in GitHub Actions. CI does not pull models, start Docker, or contact
local services.

## Real Module 1–2 acceptance test

After starting Ollama and Docker, run the real-machine acceptance workflow:

```bash
uv run python scripts/acceptance_modules_01_02.py
```

This performs the complete quality gate, uses real platform paths and services,
and separately asks permission to download `nomic-embed-text`, download the
hardware-recommended Qwen model, and start managed Qdrant. Successful resources
remain installed for normal use. See the
[`Modules 1–2 real-machine acceptance guide`](docs/testing/modules-01-02-real-acceptance.md)
for prerequisites, validations, retained resources, and result codes.

## Isolated Module 3 acceptance test

Run the complete project registration, relocation, path-reuse, cleanup-failure,
and retry workflow with real temporary Git repositories:

```bash
uv run python scripts/acceptance_module_03.py
```

This non-interactive runner isolates HOME and all XDG roots beneath one
temporary directory. It neither uses the real user registry nor contacts
Ollama, Docker, or Qdrant. See the
[`Module 3 project lifecycle acceptance guide`](docs/testing/module-03-project-lifecycle-acceptance.md)
for the exact safety and preservation checks.

## Design and execution references

- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) describes the long-term product vision.
- [`docs/design/repo-intel-v1-design.md`](docs/design/repo-intel-v1-design.md)
  defines the approved first-release architecture.
- [`docs/plans/repo-intel-v1-execution-plan.md`](docs/plans/repo-intel-v1-execution-plan.md)
  tracks module status and decisions.
