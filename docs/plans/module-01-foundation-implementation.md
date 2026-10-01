# Module 1: Project Foundation and Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a Python 3.12 package with a stable CLI, typed configuration, supported-platform abstraction, error and logging conventions, internal service contracts, and macOS/Ubuntu quality gates.

**Architecture:** The package uses a `src` layout and keeps policy-bearing domain models separate from implementation ports. CLI, configuration, and platform modules depend only on the standard library plus Typer and Pydantic; importing the package performs no service discovery or network activity. Module 1 defines the minimum interfaces later modules consume without implementing repository indexing.

**Tech Stack:** Python 3.12+, uv/uv_build, Typer, Pydantic 2, Pytest, Ruff, MyPy, GitHub Actions

**Spec:** `docs/design/repo-intel-v1-design.md`

## Execution Status

- Tasks 1–5 are complete in commits `3b5f4c2`, `1c03161`, `90a4672`,
  `8764caf`, and `200e1d1`.
- Task 6 implementation and the complete local macOS gate are complete in
  commits `1cbc3ef` and `aee0165`.
- Final review added commit `2baa134`, restoring the repository's original
  Python ignore coverage and rejecting relative Ubuntu `XDG_*_HOME` roots.
- Local evidence after that correction: Ruff lint and format checks passed,
  strict MyPy passed for 24 source files, all 66 tests passed, both
  distributions built, and Git whitespace validation plus all three CLI smoke
  commands passed.
- GitHub Actions run `36864796238` passed both `Quality (macos-latest)` and
  `Quality (ubuntu-latest)`, including dependency installation, lint,
  formatting, strict typing, tests, builds, and CLI smoke checks.
- Task 6 remains complete, but Module 1 is reopened pending both GitHub Actions
  platform jobs on the reviewed HEAD. Module 2 remains gated.

## Global Constraints

- Support Python 3.12 or newer.
- Support macOS and Ubuntu; reject other platforms explicitly.
- Require `uv` as the bootstrap dependency.
- Discover future executables through PATH; never hardcode Homebrew or Linux binary paths.
- Keep imports and Module 1 commands independent of Ollama, Docker, and Qdrant availability.
- Use CLI option, `REPO_INTEL_` environment variable, repository config, user config, then built-in default as configuration precedence.
- Default the context budget to 10,000 estimated model tokens.
- Write generated state only beneath platform-native application directories; Module 1 computes paths but does not create runtime state.
- Treat the design document as authoritative and update `docs/plans/repo-intel-v1-execution-plan.md` whenever plan status or an approved decision changes.

## Review Focus

- Malformed or unknown TOML settings must raise a typed configuration error and never fall back silently; Task 3 tests this.
- Unsupported Linux distributions must return a typed platform error rather than inheriting Ubuntu paths; Task 4 tests this.
- HOME and XDG paths containing spaces or Unicode must remain exact `Path` values; Task 4 tests this.
- Package and CLI imports must not connect to Ollama, Docker, Qdrant, or any socket; Tasks 1 and 6 test this.
- Invalid environment and CLI override values must identify the setting and carry the documented configuration error code; Tasks 2 and 3 test this.

---

## File Structure

```text
repo_intel/
├── .github/workflows/ci.yml             # macOS and Ubuntu quality matrix
├── .gitignore                            # local Python/build artifacts
├── .python-version                      # local Python selection
├── pyproject.toml                        # package, dependency, and tool config
├── uv.lock                               # reproducible dependency resolution
├── README.md                             # clone, sync, and Module 1 usage
├── src/repo_intel/
│   ├── __init__.py                       # package version
│   ├── __main__.py                       # python -m entry point
│   ├── errors.py                         # stable error and exit-code taxonomy
│   ├── log.py                            # logging configuration
│   ├── cli/
│   │   ├── __init__.py
│   │   └── app.py                        # Typer application and version command
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py                     # source merge and validation
│   │   └── models.py                     # immutable typed settings
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py                     # shared immutable value objects
│   ├── platform/
│   │   ├── __init__.py
│   │   ├── base.py                       # platform types and protocol
│   │   ├── detection.py                  # macOS/Ubuntu selection
│   │   ├── macos.py                      # macOS application paths
│   │   └── ubuntu.py                     # XDG application paths
│   └── ports.py                          # scanner/store/parser/retrieval protocols
└── tests/
    ├── integration/test_offline_import.py
    └── unit/
        ├── test_cli.py
        ├── test_config.py
        ├── test_contracts.py
        ├── test_errors.py
        ├── test_package.py
        └── test_platform.py
```

## Public Interfaces Fixed by This Plan

```python
# src/repo_intel/errors.py
class ExitCode(IntEnum): ...

class RepoIntelError(Exception):
    message: str
    exit_code: ExitCode
    hint: str | None
    def __init__(
        self,
        message: str,
        exit_code: ExitCode,
        hint: str | None = None,
    ) -> None: ...


# src/repo_intel/config/models.py
class LogLevel(StrEnum): ...

class AppConfig(BaseModel):
    log_level: LogLevel = LogLevel.INFO
    context_token_budget: PositiveInt = 10_000


# src/repo_intel/config/loader.py
def load_config(
    *,
    user_file: Path | None = None,
    repository_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
) -> AppConfig: ...


# src/repo_intel/platform/base.py
class PlatformKind(StrEnum):
    MACOS = "macos"
    UBUNTU = "ubuntu"

@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    log_dir: Path

class PlatformAdapter(Protocol):
    kind: PlatformKind
    def paths(self, *, home: Path, environ: Mapping[str, str]) -> AppPaths: ...


# src/repo_intel/platform/detection.py
def detect_platform(
    *,
    system: str | None = None,
    os_release: Mapping[str, str] | None = None,
) -> PlatformAdapter: ...
```

The domain records and service protocols are specified in Task 5 because their
fields form one cohesive contract.

### Task 1: Package skeleton and reproducible quality tooling

**Files:**
- Create: `.gitignore`
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `src/repo_intel/__init__.py`
- Create: `tests/unit/test_package.py`

**Interfaces:**
- Produces: installable `repo-intel` distribution and `repo_intel.__version__: str`
- Consumes: none

- [ ] **Step 1: Create package metadata and write the failing package test**

Create `.gitignore` covering `.venv/`, `dist/`, Python bytecode, Pytest, MyPy,
and Ruff caches. Create `.python-version` with `3.12`; create `pyproject.toml` with
`requires-python = ">=3.12"`, distribution version `0.1.0`, the uv build
backend with `uv_build>=0.12,<0.13`, runtime dependencies `typer>=0.16,<1` and
`pydantic>=2.11,<3`, and a development dependency group containing
`pytest>=8.4,<10`, `ruff>=0.12,<1`, and `mypy>=1.16,<2`. Configure Ruff for
Python 3.12 with a 100-character line limit and MyPy in strict mode for
`src/repo_intel`. Then add:

```python
def test_distribution_version_matches_package_version() -> None:
    assert repo_intel.__version__ == metadata.version("repo-intel")


def test_supported_python_floor() -> None:
    assert sys.version_info >= (3, 12)
```

- [ ] **Step 2: Resolve development dependencies and verify the package test fails**

Run: `uv lock && uv sync --no-install-project --all-groups && uv run --no-sync pytest tests/unit/test_package.py -v`

Expected: FAIL because the `repo_intel` package does not exist.

- [ ] **Step 3: Add the minimal package implementation**

Implement `repo_intel.__version__` with `importlib.metadata.version`.

- [ ] **Step 4: Install the project environment**

Run `uv sync --all-groups` so the project and its locked dependencies are
installed.

- [ ] **Step 5: Run the package test and package build**

Run: `uv run pytest tests/unit/test_package.py -v && uv build`

Expected: both tests PASS and uv creates wheel and source-distribution
artifacts.

- [ ] **Step 6: Commit Task 1**

```bash
git add .gitignore .python-version pyproject.toml uv.lock src/repo_intel/__init__.py tests/unit/test_package.py
git commit -m "build: establish Python package"
```

### Task 2: CLI, error taxonomy, and logging convention

**Files:**
- Create: `src/repo_intel/__main__.py`
- Create: `src/repo_intel/cli/__init__.py`
- Create: `src/repo_intel/cli/app.py`
- Create: `src/repo_intel/errors.py`
- Create: `src/repo_intel/log.py`
- Create: `tests/unit/test_cli.py`
- Create: `tests/unit/test_errors.py`

**Interfaces:**
- Consumes: `repo_intel.__version__`
- Produces: `repo-intel` console command, `python -m repo_intel`, `ExitCode`, `RepoIntelError`, and `configure_logging(level: str, stream: TextIO | None = None) -> None`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_help_lists_version_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.stdout


def test_version_command_prints_distribution_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == repo_intel.__version__


def test_module_entry_point_has_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "repo_intel", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Repository intelligence" in result.stdout
```

- [ ] **Step 2: Write failing error and logging tests**

Assert that `ExitCode` defines `SUCCESS=0`, `INTERNAL=1`, `USAGE=2`,
`CONFIG=3`, `PLATFORM=4`, `DEPENDENCY=5`, `DATA=6`, and
`EXTERNAL_SERVICE=7`; `RepoIntelError` retains message, code, and optional
hint; and two `configure_logging` calls leave exactly one handler on the
`repo_intel` logger.

- [ ] **Step 3: Run the tests and verify missing modules fail**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/test_errors.py -v`

Expected: FAIL because the CLI, error, and logging modules do not exist.

- [ ] **Step 4: Implement the minimal CLI and console entry point**

Create a Typer application with `no_args_is_help=True`, help text containing
"Repository intelligence", a `version` command, and a callable
`main() -> None`. Register `repo-intel = "repo_intel.cli.app:main"` in
`pyproject.toml`. Make `python -m repo_intel` call the same `main` function.

- [ ] **Step 5: Implement the error and logging contracts**

Use the exact exit codes in Step 2. `RepoIntelError.__str__` returns the
message; presentation of hints remains a CLI concern. `configure_logging`
must be idempotent, write to stderr by default, and reject unknown levels with
a `RepoIntelError` carrying `ExitCode.CONFIG`.

- [ ] **Step 6: Run focused verification**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/test_errors.py -v`

Expected: all focused tests PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add pyproject.toml uv.lock src/repo_intel/__main__.py src/repo_intel/cli src/repo_intel/errors.py src/repo_intel/log.py tests/unit/test_cli.py tests/unit/test_errors.py
git commit -m "feat: add foundational CLI contracts"
```

### Task 3: Typed configuration and source precedence

**Files:**
- Create: `src/repo_intel/config/__init__.py`
- Create: `src/repo_intel/config/models.py`
- Create: `src/repo_intel/config/loader.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `RepoIntelError`, `ExitCode.CONFIG`
- Produces: `LogLevel`, immutable `AppConfig`, and `load_config(...) -> AppConfig` with the signature fixed above

- [ ] **Step 1: Write the failing default and precedence tests**

```python
def test_defaults() -> None:
    config = load_config(environ={})
    assert config.log_level is LogLevel.INFO
    assert config.context_token_budget == 10_000


def test_precedence(tmp_path: Path) -> None:
    user = write_toml(tmp_path / "user.toml", log_level="WARNING", context_token_budget=1_000)
    repo = write_toml(tmp_path / "repo.toml", log_level="ERROR", context_token_budget=2_000)
    config = load_config(
        user_file=user,
        repository_file=repo,
        environ={"REPO_INTEL_LOG_LEVEL": "DEBUG", "REPO_INTEL_CONTEXT_TOKEN_BUDGET": "3000"},
        cli_overrides={"context_token_budget": 4_000},
    )
    assert config.log_level is LogLevel.DEBUG
    assert config.context_token_budget == 4_000
```

- [ ] **Step 2: Write failing validation tests**

Cover malformed TOML, unknown keys, a zero or negative token budget, a
non-integer environment budget, an invalid log level, a missing optional
configuration file, an unknown `REPO_INTEL_` environment variable, and an
explicit CLI override of `None` being ignored. Every invalid supplied value
must raise `RepoIntelError` with
`ExitCode.CONFIG` and name the invalid setting without printing unrelated
configuration values.

- [ ] **Step 3: Run configuration tests and verify failure**

Run: `uv run pytest tests/unit/test_config.py -v`

Expected: FAIL because configuration modules do not exist.

- [ ] **Step 4: Implement immutable models**

Define `LogLevel` values `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`.
Configure `AppConfig` as frozen with unknown fields forbidden and the exact
defaults in the public interface section.

- [ ] **Step 5: Implement deterministic loading**

Read TOML with `tomllib`. Merge built-in defaults, user file, repository file,
the two documented `REPO_INTEL_` variables, and non-`None` CLI overrides in
ascending precedence. Reject other variables bearing the `REPO_INTEL_` prefix.
Convert TOML and Pydantic validation failures to the typed configuration error
required by Step 2.

- [ ] **Step 6: Run focused verification**

Run: `uv run pytest tests/unit/test_config.py -v`

Expected: all configuration tests PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/repo_intel/config tests/unit/test_config.py
git commit -m "feat: define configuration precedence"
```

### Task 4: macOS and Ubuntu platform adapters

**Files:**
- Create: `src/repo_intel/platform/__init__.py`
- Create: `src/repo_intel/platform/base.py`
- Create: `src/repo_intel/platform/detection.py`
- Create: `src/repo_intel/platform/macos.py`
- Create: `src/repo_intel/platform/ubuntu.py`
- Create: `tests/unit/test_platform.py`

**Interfaces:**
- Consumes: `RepoIntelError`, `ExitCode.PLATFORM`
- Produces: `PlatformKind`, `AppPaths`, `PlatformAdapter`, and `detect_platform(...) -> PlatformAdapter` with the signatures fixed above

- [ ] **Step 1: Write failing macOS path tests**

For home `/Users/Test User`, assert:

```text
config_dir = /Users/Test User/Library/Application Support/repo-intel/config
data_dir   = /Users/Test User/Library/Application Support/repo-intel/data
cache_dir  = /Users/Test User/Library/Caches/repo-intel
log_dir    = /Users/Test User/Library/Logs/repo-intel
```

Also cover a Unicode home path and verify the adapter only computes paths; it
must not create directories.

- [ ] **Step 2: Write failing Ubuntu/XDG path tests**

Assert explicit `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, and
`XDG_STATE_HOME` values are honored. With an empty environment and home
`/home/test user`, assert `.config/repo-intel`, `.local/share/repo-intel`,
`.cache/repo-intel`, and `.local/state/repo-intel/log` beneath that home.

- [ ] **Step 3: Write failing platform-detection tests**

Assert `Darwin` selects macOS; `Linux` with `ID=ubuntu` selects Ubuntu; Linux
with `ID=fedora`, Windows, or an absent Ubuntu identity raises
`RepoIntelError(ExitCode.PLATFORM)` with supported-platform guidance.

- [ ] **Step 4: Run platform tests and verify failure**

Run: `uv run pytest tests/unit/test_platform.py -v`

Expected: FAIL because platform modules do not exist.

- [ ] **Step 5: Implement adapters and side-effect-free detection**

Implement the exact path rules and detection behavior from Steps 1–3. When
`os_release` is omitted on Linux, parse `/etc/os-release`; injected mappings
must bypass host-file access so tests remain deterministic.

- [ ] **Step 6: Run focused verification**

Run: `uv run pytest tests/unit/test_platform.py -v`

Expected: all platform tests PASS on both supported hosts.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/repo_intel/platform tests/unit/test_platform.py
git commit -m "feat: add supported platform adapters"
```

### Task 5: Shared domain records and implementation ports

**Files:**
- Create: `src/repo_intel/domain/__init__.py`
- Create: `src/repo_intel/domain/models.py`
- Create: `src/repo_intel/ports.py`
- Create: `tests/unit/test_contracts.py`

**Interfaces:**
- Consumes: only standard-library types
- Produces: immutable domain values and runtime-checkable protocols used by Modules 3–9

- [ ] **Step 1: Write failing domain-model tests**

The tests construct and verify these frozen, slotted dataclasses and enums:

```python
class FileKind(StrEnum):
    PYTHON = "python"
    TEST = "test"
    DOCUMENTATION = "documentation"
    CONFIGURATION = "configuration"
    MIGRATION = "migration"
    GENERATED = "generated"
    BINARY = "binary"
    SENSITIVE = "sensitive"
    OVERSIZED = "oversized"
    IGNORED = "ignored"
    OTHER = "other"

@dataclass(frozen=True, slots=True)
class RepositoryRef:
    repository_id: UUID
    root: Path

@dataclass(frozen=True, slots=True)
class SourceLocation:
    repository_id: UUID
    relative_path: PurePosixPath
    start_line: int
    end_line: int
    source_hash: str

@dataclass(frozen=True, slots=True)
class ScannedFile:
    repository_id: UUID
    relative_path: PurePosixPath
    kind: FileKind
    source_hash: str
    size_bytes: int

@dataclass(frozen=True, slots=True)
class SymbolRecord:
    symbol_id: str
    qualified_name: str
    kind: str
    location: SourceLocation

@dataclass(frozen=True, slots=True)
class ChunkRecord:
    chunk_id: str
    text: str
    location: SourceLocation
    symbol_id: str | None

@dataclass(frozen=True, slots=True)
class ParsedFile:
    file: ScannedFile
    symbols: tuple[SymbolRecord, ...]
    chunks: tuple[ChunkRecord, ...]

@dataclass(frozen=True, slots=True)
class SearchRequest:
    repository_id: UUID
    query: str
    limit: int = 10

@dataclass(frozen=True, slots=True)
class SearchHit:
    location: SourceLocation
    score: float
    signals: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ContextPackage:
    query: str
    hits: tuple[SearchHit, ...]
    estimated_tokens: int
    token_budget: int
```

Validate absolute repository roots; relative source paths that are nonempty,
non-absolute, and contain no `..`; one-based ordered line ranges;
64-character lowercase hexadecimal SHA-256 hashes; nonnegative byte counts;
nonblank identifiers, chunk text, signal names, and queries; positive limits
and token budgets; finite scores; and nonnegative token usage not exceeding
the budget.

- [ ] **Step 2: Write failing protocol-conformance tests**

Define runtime-checkable protocols with these methods:

```python
class RepositoryScanner(Protocol):
    def scan(self, repository: RepositoryRef) -> tuple[ScannedFile, ...]: ...

class MetadataStore(Protocol):
    def replace_inventory(
        self, repository: RepositoryRef, files: Sequence[ScannedFile]
    ) -> None: ...

class SourceParser(Protocol):
    def parse(self, file: ScannedFile, source: str) -> ParsedFile: ...

class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...

class Retriever(Protocol):
    def search(self, request: SearchRequest) -> tuple[SearchHit, ...]: ...

class ContextComposer(Protocol):
    def compose(
        self,
        request: SearchRequest,
        hits: Sequence[SearchHit],
        token_budget: int,
    ) -> ContextPackage: ...
```

Use minimal fake classes to prove structural conformance. Do not create real
scanner, store, parser, embedder, retriever, or composer implementations.

- [ ] **Step 3: Run contract tests and verify failure**

Run: `uv run pytest tests/unit/test_contracts.py -v`

Expected: FAIL because the domain and port modules do not exist.

- [ ] **Step 4: Implement the domain values and protocols**

Use `__post_init__` for the exact validation rules in Step 1 and
`@runtime_checkable` for each protocol. Re-export public domain values from
`repo_intel.domain` and protocols from `repo_intel.ports`.

- [ ] **Step 5: Run focused verification**

Run: `uv run pytest tests/unit/test_contracts.py -v`

Expected: all contract tests PASS and no external service is imported.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/repo_intel/domain src/repo_intel/ports.py tests/unit/test_contracts.py
git commit -m "feat: define repository intelligence ports"
```

### Task 6: CI matrix, onboarding documentation, and Module 1 gate

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `tests/integration/test_offline_import.py`
- Modify: `README.md`
- Modify: `docs/plans/repo-intel-v1-execution-plan.md`
- Modify: `docs/plans/module-01-foundation-implementation.md`

**Interfaces:**
- Consumes: every Module 1 deliverable
- Produces: repeatable macOS/Ubuntu verification and user-facing bootstrap documentation

- [ ] **Step 1: Write the failing offline-import test**

Patch `socket.create_connection` and `socket.socket.connect` to raise an
assertion, clear loaded `repo_intel` submodules, import the public package,
CLI, configuration, platform, domain, and ports modules, and assert no socket
call occurs.

- [ ] **Step 2: Run the offline-import test before integration work**

Run: `uv run pytest tests/integration/test_offline_import.py -v`

Expected: PASS if prior tasks stayed side-effect free; otherwise FAIL and fix
the importing module before continuing.

- [ ] **Step 3: Add the macOS and Ubuntu CI matrix**

Use `actions/checkout@v7` and `astral-sh/setup-uv@v10.2.0`, Python 3.12, uv
caching, and `uv sync --locked --all-groups`. Run these separate named steps:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/repo_intel tests
uv run pytest -q
uv build
uv run repo-intel --help
uv run repo-intel version
uv run python -m repo_intel --help
```

- [ ] **Step 4: Replace the current README with Module 1 onboarding**

Document purpose, Python and uv prerequisites, clone plus `uv sync`, the three
CLI smoke commands, supported macOS/Ubuntu scope, local-first principle, and
the fact that Ollama, Docker, and Qdrant are not contacted by Module 1.

- [ ] **Step 5: Run the complete local Module 1 gate**

Run:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src/repo_intel tests
uv run pytest -q
uv build
uv run repo-intel --help
uv run repo-intel version
uv run python -m repo_intel --help
git diff --check
```

Expected: every command exits 0; Pytest reports no failures; CLI output shows
the help and version; build produces both distribution formats; Git reports no
whitespace errors.

- [ ] **Step 6: Verify both CI platform jobs**

Push the branch through the normal repository workflow and verify the
`ubuntu-latest` and `macos-latest` jobs both pass. Do not mark the module
complete from local macOS evidence alone.

- [ ] **Step 7: Update the living records**

Check completed steps in this plan. Change Module 1 from `In progress` to
`Complete` in `docs/plans/repo-intel-v1-execution-plan.md` and add the commit,
local commands, both CI job results, limitations, and authorization to plan
Module 2 under its completion record. If any gate remains open, leave status
as `In progress` and record the blocker instead.

- [ ] **Step 8: Commit Task 6**

```bash
git add .github/workflows/ci.yml README.md tests/integration/test_offline_import.py docs/plans/repo-intel-v1-execution-plan.md docs/plans/module-01-foundation-implementation.md
git commit -m "ci: enforce module one quality gate"
```

## Plan Self-Review Record

- Spec coverage: all Module 1 deliverables and success criteria have an owning task.
- Step scan: each implementation step fixes an exact interface, value, file, or verification command.
- Type consistency: configuration, platform, domain, and port signatures match across tasks.
- Review focus: all five named failure classes have explicit tests.
- Proportion: implementation bodies remain with the implementer; the plan fixes contracts and assertions rather than transcribing the program.
