# Module 2: Setup, Diagnostics, and Model Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, repeatable macOS and Ubuntu setup, read-only diagnostics, a pinned local Qdrant service, and conservative hardware-aware Qwen recommendations.

**Architecture:** External commands and HTTP probes sit behind small injected protocols so every failure mode is deterministic in tests and no import performs machine discovery. `doctor` composes read-only dependency, service, model, and hardware checks into immutable results; `setup` prepares platform-native files and executes only individually confirmed external actions. Hardware recommendation remains a pure policy function, while platform-specific inspection only gathers evidence.

**Tech Stack:** Python 3.12+, Typer, Pydantic 2, standard-library subprocess/urllib/TOML support, Docker Compose, Ollama, Pytest, Ruff, MyPy

**Spec:** `docs/design/repo-intel-v1-design.md`, especially sections 3, 5, 6, 10, and Module 2

## Execution Status

- Tasks 1–6 are implemented in commits `c081528`, `0a7dd0b`, `b49de0e`,
  `ab7c030`, `92fd2ac`, and `e47333e`.
- Task 7's local acceptance gate passed on macOS with Python 3.12.14 and uv
  0.12.21: Ruff lint and format, strict MyPy, 165 tests, source and wheel
  builds, all CLI smoke commands, and Git whitespace validation passed.
- Whole-module self-review completed across `02ff765..8377a67`. It found one
  Important integration defect: Qdrant's successful `/healthz` response is
  plain text, while the shared bounded client intentionally accepts JSON only.
  Commit `fd1dd31` now treats only a 2xx plain-text result from that fixed
  Qdrant endpoint as healthy; the red/green regression and full gate passed.
- No Critical or Important review finding remains. Module 2 stays `In progress`
  pending GitHub Actions results for the exact pushed reviewed HEAD on macOS
  and Ubuntu.

## Global Constraints

- Support macOS and Ubuntu only; retain the explicit unsupported-platform error.
- Discover Git, ripgrep, Ollama, Docker, `sysctl`, and `nvidia-smi` through PATH; never hardcode executable locations.
- Keep `repo-intel doctor` read-only: no directory creation, file writes, downloads, service starts, or configuration changes.
- Require an individual confirmation or an explicit action flag before pulling a model or starting Qdrant.
- Do not install system software; report platform-specific guidance instead.
- Bind Qdrant only to localhost and pin `qdrant/qdrant:v1.19.1` in the generated Compose file.
- Treat `nomic-embed-text` as required and Qwen coding models as recommendations only.
- Recommend `qwen2.5-coder:1.5b` below 16 GiB, `qwen2.5-coder:7b` from 16 through 47 GiB, and `qwen3-coder:30b` only at 48 GiB or more with a supported accelerator.
- Fall back to `qwen2.5-coder:1.5b` with an uncertainty notice when total memory is unknown; fall back to the 7B tier when memory is at least 48 GiB but accelerator suitability is absent or unknown.
- Never print raw subprocess output, environment values, HTTP bodies, or tokens in diagnostics or errors.
- Keep imports and help/version commands independent of Ollama, Docker, and Qdrant availability.
- Preserve configuration precedence and platform-native state locations established by Module 1.

## Review Focus

- A binary path containing spaces must be passed as one subprocess argument and never through a shell; Task 1 tests this.
- A command timeout, connection refusal, HTTP error, and malformed JSON must produce distinct internal outcomes without leaking raw output; Tasks 1 and 3 test this.
- Missing or malformed macOS/Ubuntu hardware evidence must produce a conservative, explicitly uncertain recommendation; Task 2 tests this.
- Existing user configuration must never be overwritten, while a changed managed Compose file must update atomically; Task 4 tests this.
- Declining every prompt, cancelling a prompt, or rerunning setup after success must leave external services unchanged and exit with useful guidance; Tasks 5 and 6 test this.

---

## File Structure

```text
repo_intel/
├── src/repo_intel/
│   ├── cli/
│   │   ├── app.py                       # register setup and doctor commands
│   │   ├── doctor.py                    # diagnostic rendering and exit mapping
│   │   └── setup.py                     # confirmations and setup rendering
│   ├── diagnostics/
│   │   ├── __init__.py
│   │   ├── dependencies.py              # PATH and command-backed checks
│   │   ├── doctor.py                    # read-only orchestration
│   │   ├── models.py                    # immutable diagnostic records
│   │   └── services.py                  # Ollama, model, and Qdrant HTTP checks
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── commands.py                  # safe subprocess abstraction
│   │   └── http.py                      # bounded JSON HTTP abstraction
│   └── setup/
│       ├── __init__.py
│       ├── actions.py                   # confirmed model/service mutations
│       ├── files.py                     # atomic platform-native setup files
│       ├── guidance.py                  # macOS and Ubuntu installation hints
│       ├── hardware.py                  # platform hardware evidence gathering
│       ├── models.py                    # hardware/setup value objects
│       ├── recommendation.py            # pure Qwen tier policy
│       └── resources/qdrant.compose.yaml # pinned localhost-only template
└── tests/
    ├── integration/
    │   ├── test_doctor_workflow.py
    │   └── test_setup_workflow.py
    └── unit/
        ├── test_cli_doctor.py
        ├── test_cli_setup.py
        ├── test_dependencies.py
        ├── test_hardware.py
        ├── test_http.py
        ├── test_recommendation.py
        ├── test_runtime_commands.py
        ├── test_service_diagnostics.py
        ├── test_setup_actions.py
        └── test_setup_files.py
```

## Public Interfaces Fixed by This Plan

```python
# src/repo_intel/runtime/commands.py
@dataclass(frozen=True, slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

class CommandRunner(Protocol):
    def which(self, executable: str) -> Path | None: ...
    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> CommandResult: ...


# src/repo_intel/runtime/http.py
class HttpState(StrEnum):
    OK = "ok"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    INVALID_JSON = "invalid_json"
    TOO_LARGE = "too_large"

@dataclass(frozen=True, slots=True)
class JsonResponse:
    state: HttpState
    status_code: int | None
    payload: object | None

class JsonHttpClient(Protocol):
    def get(self, url: str, *, timeout_seconds: float) -> JsonResponse: ...


# src/repo_intel/setup/models.py
class AcceleratorKind(StrEnum):
    APPLE_METAL = "apple_metal"
    NVIDIA_CUDA = "nvidia_cuda"

@dataclass(frozen=True, slots=True)
class HardwareProfile:
    memory_bytes: int | None
    architecture: str
    accelerator: AcceleratorKind | None
    complete: bool

@dataclass(frozen=True, slots=True)
class ModelRecommendation:
    model: str
    reason: str
    uncertain: bool

class SetupActionKind(StrEnum):
    PULL_EMBEDDING = "pull_embedding"
    PULL_QWEN = "pull_qwen"
    START_QDRANT = "start_qdrant"

@dataclass(frozen=True, slots=True)
class SetupPaths:
    user_config: Path
    compose_file: Path
    qdrant_data_dir: Path

@dataclass(frozen=True, slots=True)
class PreparedSetup:
    paths: SetupPaths
    changed_paths: tuple[Path, ...]

@dataclass(frozen=True, slots=True)
class SetupAction:
    kind: SetupActionKind
    description: str
    args: tuple[str, ...]
    timeout_seconds: float
    stream: bool
    env: Mapping[str, str] | None = None

@dataclass(frozen=True, slots=True)
class SetupActionResult:
    kind: SetupActionKind
    succeeded: bool


# src/repo_intel/diagnostics/models.py
class CheckState(StrEnum):
    INSTALLED = "installed"
    MISSING = "missing"
    HEALTHY = "healthy"
    STOPPED = "stopped"
    UNHEALTHY = "unhealthy"

@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    state: CheckState
    summary: str
    required: bool
    guidance: str | None = None

@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DiagnosticCheck, ...]
    hardware: HardwareProfile
    recommendation: ModelRecommendation
    @property
    def exit_code(self) -> ExitCode: ...
```

### Task 1: Safe command and HTTP runtime adapters

**Files:**
- Create: `src/repo_intel/runtime/__init__.py`
- Create: `src/repo_intel/runtime/commands.py`
- Create: `src/repo_intel/runtime/http.py`
- Create: `tests/unit/test_runtime_commands.py`
- Create: `tests/unit/test_http.py`

**Interfaces:**
- Consumes: `RepoIntelError`, `ExitCode`
- Produces: `CommandResult`, `CommandRunner`, `SubprocessCommandRunner`, `HttpState`, `JsonResponse`, `JsonHttpClient`, and `UrllibJsonHttpClient`

- [x] **Step 1: Write failing command-runner tests**

Test that `which()` returns an exact `Path`, an executable path containing spaces remains `args[0]`, `shell=False` is used, a timeout returns `timed_out=True` without raising, and `stream=True` does not retain stdout or stderr. Inject the subprocess and PATH lookup callables rather than executing machine commands.

- [x] **Step 2: Run the command-runner tests and verify the module is missing**

Run: `uv run pytest tests/unit/test_runtime_commands.py -v`

Expected: FAIL during import because `repo_intel.runtime.commands` does not exist.

- [x] **Step 3: Implement the command interfaces and adapter**

Implement the signatures in “Public Interfaces.” Convert `TimeoutExpired` into a `CommandResult` with return code `124`; never use a string command or `shell=True`. Merge an explicit action environment onto a copy of the current environment without modifying `os.environ`. Mark captured stdout and stderr fields `repr=False`.

- [x] **Step 4: Write failing bounded-HTTP tests**

Cover valid JSON, connection refusal, socket timeout, non-2xx HTTP status, invalid JSON, and a response larger than 1 MiB. Assert all failures become `JsonResponse` states and no response body appears in exceptions or representations.

- [x] **Step 5: Implement `UrllibJsonHttpClient`**

Use GET requests, a caller-supplied timeout, a 1 MiB response limit, UTF-8 JSON decoding, and the exact `HttpState` categories above. Mark the decoded payload `repr=False`. Do not follow this with retries; `doctor` is a snapshot.

- [x] **Step 6: Run focused and full tests**

Run: `uv run pytest tests/unit/test_runtime_commands.py tests/unit/test_http.py -v`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests PASS.

- [x] **Step 7: Commit Task 1**

```bash
git add src/repo_intel/runtime tests/unit/test_runtime_commands.py tests/unit/test_http.py
git commit -m "feat: add safe runtime adapters"
```

### Task 2: Hardware inspection and conservative Qwen recommendation

**Files:**
- Create: `src/repo_intel/setup/__init__.py`
- Create: `src/repo_intel/setup/models.py`
- Create: `src/repo_intel/setup/hardware.py`
- Create: `src/repo_intel/setup/recommendation.py`
- Create: `tests/unit/test_hardware.py`
- Create: `tests/unit/test_recommendation.py`

**Interfaces:**
- Consumes: `PlatformKind`, `CommandRunner`
- Produces: `AcceleratorKind`, `HardwareProfile`, `ModelRecommendation`, `inspect_hardware(platform: PlatformKind, runner: CommandRunner, *, architecture: str | None = None, meminfo_path: Path = Path("/proc/meminfo")) -> HardwareProfile`, and `recommend_qwen(profile: HardwareProfile) -> ModelRecommendation`

- [x] **Step 1: Write failing recommendation-policy tests**

Assert exact boundary behavior for unknown memory, 15 GiB, 16 GiB, 47 GiB, 48 GiB without an accelerator, 48 GiB with Apple Metal, and 48 GiB with NVIDIA CUDA. Unknown memory must recommend `qwen2.5-coder:1.5b` with `uncertain=True`; 48 GiB without confirmed acceleration must recommend `qwen2.5-coder:7b` with `uncertain=True`.

- [x] **Step 2: Implement the immutable models and pure recommendation function**

Use binary GiB (`1024**3`). Recommendation reasons must mention the evidence used without machine identifiers or raw command output.

- [x] **Step 3: Write failing platform inspection tests**

Cover macOS `sysctl -n hw.memsize`, Apple Silicon Metal inference on `arm64`, Intel macOS without an inferred accelerator, Ubuntu `/proc/meminfo`, successful `nvidia-smi`, absent `nvidia-smi`, malformed memory values, missing files, command failure, and Unicode paths.

- [x] **Step 4: Implement `inspect_hardware`**

Resolve `sysctl` and `nvidia-smi` through `CommandRunner.which`. Parse only the total memory value and accelerator availability; discard raw output after parsing. Mark `complete=False` whenever required evidence is absent or malformed and reuse the existing typed platform error outside macOS and Ubuntu.

- [x] **Step 5: Run focused and full tests**

Run: `uv run pytest tests/unit/test_hardware.py tests/unit/test_recommendation.py -v`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests PASS.

- [x] **Step 6: Commit Task 2**

```bash
git add src/repo_intel/setup tests/unit/test_hardware.py tests/unit/test_recommendation.py
git commit -m "feat: recommend Qwen models from hardware"
```

### Task 3: Read-only dependency and service diagnostics

**Files:**
- Create: `src/repo_intel/diagnostics/__init__.py`
- Create: `src/repo_intel/diagnostics/models.py`
- Create: `src/repo_intel/diagnostics/dependencies.py`
- Create: `src/repo_intel/diagnostics/services.py`
- Create: `src/repo_intel/diagnostics/doctor.py`
- Create: `tests/unit/test_dependencies.py`
- Create: `tests/unit/test_service_diagnostics.py`
- Create: `tests/integration/test_doctor_workflow.py`

**Interfaces:**
- Consumes: runtime adapters, `HardwareProfile`, `ModelRecommendation`, `PlatformKind`, and `ExitCode`
- Produces: `CheckState`, `DiagnosticCheck`, `DoctorReport`, `check_executable(name: str, runner: CommandRunner, guidance: str) -> DiagnosticCheck`, and `run_doctor(platform: PlatformKind, runner: CommandRunner, http: JsonHttpClient, *, hardware_profile: HardwareProfile | None = None) -> DoctorReport`

- [x] **Step 1: Write failing executable-check tests**

Test installed and missing Git, ripgrep, Ollama, and Docker. Assert summaries contain only dependency names and fixed status text, not resolved paths or environment values.

- [x] **Step 2: Implement diagnostic records and PATH checks**

`DoctorReport.exit_code` returns `EXTERNAL_SERVICE` when any required service is stopped or unhealthy, otherwise `DEPENDENCY` when a required command or `nomic-embed-text` is missing, otherwise `SUCCESS`. Use `DiagnosticCheck.required` rather than names to select failures. A recommended Qwen model is optional and must not change the exit code.

- [x] **Step 3: Write failing service and model tests**

Cover:

- Ollama executable missing → `MISSING`
- Ollama endpoint unreachable or timed out → `STOPPED`
- Ollama non-2xx, oversized, malformed, or schema-invalid response → `UNHEALTHY`
- valid `/api/tags` response → `HEALTHY`
- exact `nomic-embed-text` tag present or absent → `INSTALLED` or `MISSING`
- recommended Qwen tag present or absent without changing report failure status
- Docker executable present with a successful `docker info` → `HEALTHY`
- Docker’s recognized “daemon not running” failure → `STOPPED`
- any other nonzero Docker result or timeout → `UNHEALTHY`
- Qdrant `/healthz` success, refusal, timeout, and HTTP failure → `HEALTHY`, `STOPPED`, or `UNHEALTHY`

Use fixed summaries; raw stdout, stderr, and HTTP payloads must not appear.

Treat an unqualified requested model name as matching either the identical tag
or the same tag with `:latest`; never treat another version or a prefix match
as installed.

- [x] **Step 4: Implement service checks and doctor orchestration**

Probe only `http://127.0.0.1:11434/api/tags` and `http://127.0.0.1:6333/healthz`, each with a two-second timeout. Run `docker info --format {{.ServerVersion}}` with a five-second timeout. Keep check order deterministic: Git, ripgrep, Ollama, Docker, Qdrant, `nomic-embed-text`, recommended Qwen.

- [x] **Step 5: Prove doctor is read-only in an integration test**

Use recording fakes and a nonexistent temporary application root. Assert the report is complete, no path is created, only `which`, `docker info`, and HTTP GET operations occur, and no model pull or Docker Compose command is issued.

- [x] **Step 6: Run focused and full tests**

Run: `uv run pytest tests/unit/test_dependencies.py tests/unit/test_service_diagnostics.py tests/integration/test_doctor_workflow.py -v`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests PASS.

- [x] **Step 7: Commit Task 3**

```bash
git add src/repo_intel/diagnostics tests/unit/test_dependencies.py tests/unit/test_service_diagnostics.py tests/integration/test_doctor_workflow.py
git commit -m "feat: add read-only system diagnostics"
```

### Task 4: Atomic local setup files and pinned Qdrant Compose service

**Files:**
- Create: `src/repo_intel/setup/files.py`
- Create: `src/repo_intel/setup/resources/qdrant.compose.yaml`
- Create: `tests/unit/test_setup_files.py`
- Modify: `pyproject.toml`
- Modify: `tests/unit/test_package.py`

**Interfaces:**
- Consumes: `AppPaths`
- Produces: `SetupPaths`, `PreparedSetup`, `setup_paths(app_paths: AppPaths) -> SetupPaths`, and `prepare_setup_files(app_paths: AppPaths) -> PreparedSetup`

- [x] **Step 1: Write failing setup-file tests**

Assert exact locations:

- user config: `<config_dir>/config.toml`
- managed Compose: `<config_dir>/qdrant.compose.yaml`
- Qdrant data: `<data_dir>/qdrant`

Cover spaces and Unicode in every root, a missing root, an existing user config with custom bytes, an unchanged managed file, a stale managed file, write failure before `os.replace`, and two consecutive successful runs. Existing user configuration must remain byte-for-byte unchanged; managed output must be deterministic.

- [x] **Step 2: Add the Compose resource and package-resource test**

Pin `qdrant/qdrant:v1.19.1`, bind REST and gRPC ports as `127.0.0.1:6333:6333` and `127.0.0.1:6334:6334`, use the rendered absolute Qdrant data directory as a bind mount, and set `restart: "no"`. Add a wheel-content assertion proving the template is packaged.

- [x] **Step 3: Implement atomic preparation**

Create only platform-owned directories. Create `config.toml` only when absent, with valid TOML comments and no secrets. Render the Compose template using JSON quoting for the absolute bind-mount path, write temporary files in the destination directory, flush and `fsync`, then replace atomically. Return which paths changed so the CLI can explain idempotency.

- [x] **Step 4: Run focused tests and inspect built artifacts**

Run: `uv run pytest tests/unit/test_setup_files.py tests/unit/test_package.py -v`

Expected: PASS.

Run: `uv build`

Expected: the source distribution and wheel contain `qdrant.compose.yaml`.

- [x] **Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests PASS.

- [x] **Step 6: Commit Task 4**

```bash
git add pyproject.toml src/repo_intel/setup/files.py src/repo_intel/setup/resources/qdrant.compose.yaml tests/unit/test_setup_files.py tests/unit/test_package.py
git commit -m "feat: prepare managed Qdrant service files"
```

### Task 5: Confirmed and idempotent setup actions

**Files:**
- Create: `src/repo_intel/setup/actions.py`
- Create: `tests/unit/test_setup_actions.py`
- Create: `tests/integration/test_setup_workflow.py`

**Interfaces:**
- Consumes: `DoctorReport`, `SetupPaths`, `CommandRunner`, `SetupActionKind`
- Produces: `SetupAction`, `SetupActionResult`, `plan_setup_actions(report: DoctorReport, setup: SetupPaths, runner: CommandRunner) -> tuple[SetupAction, ...]`, and `execute_setup_action(action: SetupAction, runner: CommandRunner) -> SetupActionResult`

- [x] **Step 1: Write failing action-planning tests**

Assert that missing `nomic-embed-text` plans `ollama pull nomic-embed-text`, a missing recommended Qwen plans the exact recommended tag, and stopped Qdrant plans `docker compose --project-name repo-intel --file <absolute-compose-path> up --detach qdrant`. Healthy or installed items produce no action. Missing Ollama or Docker commands produce guidance rather than impossible actions.

- [x] **Step 2: Implement immutable actions and deterministic planning**

Every action stores its kind, fixed description, exact argument tuple, timeout, streaming choice, and optional environment. Model pulls use streaming output and a 3,600-second timeout; Qdrant startup uses a 120-second timeout. Resolve executables through `which` before constructing actions.

- [x] **Step 3: Write failing execution tests**

Cover successful pulls/startup, timeout, nonzero exit, a path containing spaces, and a disappearing executable. Assert failures raise typed `DEPENDENCY` or `EXTERNAL_SERVICE` errors with actionable fixed guidance and no captured command output.

- [x] **Step 4: Implement one-action execution**

Execute only an action already selected by the caller; this layer must never infer consent. Use argument sequences, never a shell. Do not retry model downloads or service startup automatically.

- [x] **Step 5: Add the idempotent workflow integration test**

Prepare files, construct a report, explicitly approve all planned actions in a fake executor, then rerun against a healthy report. Assert the second run changes no files and executes no external action. Add a failure midway and assert a later rerun plans only unfinished work.

- [x] **Step 6: Run focused and full tests**

Run: `uv run pytest tests/unit/test_setup_actions.py tests/integration/test_setup_workflow.py -v`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests PASS.

- [x] **Step 7: Commit Task 5**

```bash
git add src/repo_intel/setup/actions.py tests/unit/test_setup_actions.py tests/integration/test_setup_workflow.py
git commit -m "feat: execute confirmed setup actions"
```

### Task 6: macOS and Ubuntu guidance plus CLI workflows

**Files:**
- Create: `src/repo_intel/setup/guidance.py`
- Create: `src/repo_intel/cli/doctor.py`
- Create: `src/repo_intel/cli/setup.py`
- Modify: `src/repo_intel/cli/app.py`
- Create: `tests/unit/test_cli_doctor.py`
- Create: `tests/unit/test_cli_setup.py`
- Modify: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: platform detection/paths, `run_doctor`, `prepare_setup_files`, setup actions, `RepoIntelError`
- Produces: `repo-intel doctor` and `repo-intel setup` with `--pull-embedding`, `--pull-qwen`, `--start-qdrant`, and `--no-input`

- [x] **Step 1: Write failing guidance and doctor CLI tests**

Assert macOS and Ubuntu provide distinct fixed guidance for missing Git, ripgrep, Ollama, and Docker without executing installers. Test deterministic doctor rows, the Qwen recommendation and uncertainty note, `SUCCESS` for a healthy report, `DEPENDENCY` for missing requirements, and `EXTERNAL_SERVICE` for stopped or unhealthy services. Assert output excludes raw paths, environment values, stderr, HTTP bodies, and supplied sentinel secrets.

- [x] **Step 2: Implement guidance and doctor rendering**

Render one row per check in report order and a final recommendation. Catch only typed application errors; unexpected failures retain the existing internal-error behavior. Do not create application paths while resolving `doctor` dependencies.

- [x] **Step 3: Write failing setup CLI tests**

Cover:

- first run creates local files and shows proposed actions
- `--no-input` declines all unflagged actions without prompting or executing them
- interactive yes/no confirmation is requested separately for every unflagged action
- EOF or cancellation declines the current and remaining actions cleanly
- each explicit action flag authorizes only its matching action
- declining everything exits successfully with rerun guidance
- a failed approved action returns its typed nonzero code
- a second healthy run reports no changes and performs no action
- unsupported platforms fail before writing files

- [x] **Step 4: Implement setup orchestration**

Run a pre-setup diagnostic snapshot, prepare local files, plan actions, collect consent, execute approved actions in embedding/Qwen/Qdrant order, then run a final read-only diagnostic snapshot. Explicit flags count as consent only for their named action; `--no-input` declines every other action. Never add a global `--yes` option.

- [x] **Step 5: Register commands and preserve existing CLI behavior**

Keep `version`, no-argument help, and `python -m repo_intel` unchanged. Update help tests to require `setup`, `doctor`, and `version`.

- [x] **Step 6: Run focused and full tests**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/test_cli_doctor.py tests/unit/test_cli_setup.py -v`

Expected: PASS.

Run: `uv run pytest -q`

Expected: all tests PASS.

- [x] **Step 7: Commit Task 6**

```bash
git add src/repo_intel/cli src/repo_intel/setup/guidance.py tests/unit/test_cli.py tests/unit/test_cli_doctor.py tests/unit/test_cli_setup.py
git commit -m "feat: expose setup and doctor workflows"
```

### Task 7: Cross-platform acceptance gate and user documentation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/plans/module-02-setup-diagnostics-implementation.md`
- Modify: `docs/plans/repo-intel-v1-execution-plan.md`

**Interfaces:**
- Consumes: every Module 2 deliverable
- Produces: documented clone-to-setup workflow and macOS/Ubuntu evidence for the Module 2 gate

- [x] **Step 1: Add deterministic CI acceptance commands**

Add fake-backed acceptance tests for macOS and Ubuntu to the existing matrix; do not pull models, start Docker, or contact localhost services in CI. Add CLI help smoke checks for `repo-intel setup --help` and `repo-intel doctor --help`.

- [x] **Step 2: Document setup, consent, and troubleshooting**

Document `uv sync`, `uv run repo-intel doctor`, and `uv run repo-intel setup`; explain every explicit setup flag, model tiers, platform locations, localhost ports, `--no-input`, rerun behavior, and that system dependencies are guidance-only. Include manual commands for a user to inspect `doctor`, decline all setup actions, approve one action at a time, and rerun idempotently.

- [x] **Step 3: Run the complete local gate**

Run:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src/repo_intel tests
uv run pytest -q
uv build
uv run repo-intel --help
uv run repo-intel setup --help
uv run repo-intel doctor --help
uv run repo-intel version
uv run python -m repo_intel --help
git diff --check
```

Expected: every command exits zero.

- [x] **Step 4: Record the local checkpoint and commit Task 7**

Keep Module 2 `In progress` until the pushed commit passes both GitHub Actions jobs.

```bash
git add .github/workflows/ci.yml README.md docs/plans/module-02-setup-diagnostics-implementation.md docs/plans/repo-intel-v1-execution-plan.md
git commit -m "ci: gate setup diagnostics on both platforms"
```

- [ ] **Step 5: Verify remote macOS and Ubuntu jobs**

After the user pushes, verify both matrix jobs pass for the exact reviewed commit. Record the run URL, commit, local commands, platform evidence, known limitations, and the next authorized module in the execution index.

- [ ] **Step 6: Close the Module 2 gate**

Mark Module 2 `Complete` only after the local gate, whole-module review, and both remote jobs pass. Commit the completion record locally; do not push it.

```bash
git add docs/plans/module-02-setup-diagnostics-implementation.md docs/plans/repo-intel-v1-execution-plan.md
git commit -m "docs: close module two gate"
```

## Plan Self-Review Record

- Spec coverage: all Module 2 deliverables and success criteria have an owning task, including consent, idempotency, offline behavior, unsupported platforms, and both CI platforms.
- Step scan: every implementation step fixes an interface, observable behavior, exact constant, or verification command without supplying production function bodies.
- Type consistency: runtime adapters feed diagnostics; diagnostics and setup paths feed action planning; the CLI consumes only those declared interfaces.
- Review focus: all five named failure classes have explicit tests in their owning task.
- Proportion: the plan is longer than the compact module design because it fixes safety boundaries and cross-platform cases, but leaves algorithms and implementation bodies to the implementer.
