# Module 3 Project Lifecycle Acceptance

## Purpose

This workflow exercises the delivered Module 3 CLI against real Git
repositories, SQLite, and filesystem cleanup on macOS or Ubuntu. It does not
use a real user registry: every repository, HOME directory, XDG root, registry,
allocation, replacement repository, and sentinel is created inside one
temporary directory and removed when the process exits.

The workflow does not download Ollama models, start Docker, contact Qdrant, or
require network access.

## Prerequisites

- macOS or Ubuntu
- Git available on `PATH`
- Python 3.12 or newer
- the locked development environment installed with `uv`

## Run

From the repository root:

```bash
uv sync --locked --all-groups
uv run python scripts/acceptance_module_03.py
```

The command is non-interactive. A successful run ends with:

```text
MODULE 3 ACCEPTANCE PASSED
```

Any failure returns a nonzero exit code and names the failed stage without
printing captured command output or sentinel contents.

## Validated workflow

The runner verifies:

1. native application paths remain beneath the temporary root;
2. nested and repeated initialization return one UUID;
3. a second repository receives an independent UUID;
4. listing and UUID status render complete stable records;
5. a same-filesystem move requires explicit relocation and preserves identity;
6. a replacement repository at the registered path is reported as reused;
7. dry-run cleanup reports data, cache, and log resources without mutation;
8. a cache-directory symlink is refused without touching its external
   sentinel, while data and log providers still complete;
9. cleanup progress remains retryable in the `removing` state;
10. repairing the isolated symlink lets a retry delete the first registration;
11. source files, `.repo-intel.toml`, the replacement repository, sentinel,
    and unrelated project remain unchanged; and
12. final cleanup leaves the isolated registry with no projects.

The runner creates marker files in every unrelated-project allocation and
compares protected content, timestamps, and modes across cleanup stages. It
also verifies that removed UUIDs are no longer addressable.

## CI coverage

GitHub Actions runs the same command after the complete test suite on both
`macos-latest` and `ubuntu-latest`. The Module 3 gate remains open until both
matrix jobs pass for the exact reviewed commit pushed by the user.
