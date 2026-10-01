# repo_intel — High-Level Project Blueprint

## 1. Project Purpose

`repo_intel` is a **local-first repository intelligence platform** designed to make local coding agents substantially better at understanding large codebases.

The core problem is simple:

> Large repositories contain far more information than a coding model can safely and efficiently hold in one context window.

Instead of sending entire repositories to the model, `repo_intel` builds a structured local knowledge system around the repository and gives the coding agent only the most relevant context for the task.

The system should answer questions such as:

- Where is this behavior implemented?
- What calls this function?
- What depends on this module?
- What tests cover this code?
- What configuration affects this behavior?
- Why was this code changed?
- What is the likely blast radius of modifying this symbol?
- Which files matter for this task?
- What architectural area does this belong to?
- What changed recently around this feature?
- What should an agent inspect before modifying this code?

The project is intended to sit behind tools such as OpenCode, Codex-like agents, or future local development agents.

---

## 2. Core Philosophy

The system should follow five principles.

### 2.1 Local First

Repository contents, embeddings, metadata, history, and engineering memory remain local.

Core operation must not depend on cloud APIs.

### 2.2 Retrieval Over Brute-Force Context

Do not try to solve repository understanding by pushing 100,000 lines of source into an LLM.

Instead:

```text
question
   ↓
retrieve relevant repository knowledge
   ↓
compose focused context
   ↓
agent reads authoritative source
   ↓
reason / change / test
```

### 2.3 Source Code Remains Authoritative

RAG results are for navigation and reasoning.

The agent should always read the actual source before modifying it.

### 2.4 Hybrid Intelligence

No single retrieval method is sufficient.

The system combines:

```text
semantic search
+
lexical search
+
symbol relationships
+
dependency graph
+
Git history
+
test relationships
```

### 2.5 Incremental and Persistent

After the initial repository scan, normal changes should result in small incremental updates rather than full re-indexing.

---

## 3. High-Level Architecture

```text
                           ┌──────────────────────────┐
                           │       Developer          │
                           │                          │
                           │   OpenCode / Agent UI    │
                           └────────────┬─────────────┘
                                        │
                                        │ MCP
                                        ▼
                         ┌────────────────────────────┐
                         │       repo_intel MCP       │
                         │                            │
                         │  repository tools          │
                         │  context tools             │
                         │  impact tools              │
                         └─────────────┬──────────────┘
                                       │
                                       ▼
                         ┌────────────────────────────┐
                         │      Context Engine        │
                         │                            │
                         │ query understanding        │
                         │ retrieval orchestration    │
                         │ ranking                    │
                         │ deduplication              │
                         │ token budgeting            │
                         │ context composition        │
                         └─────────────┬──────────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
                 │                     │                     │
                 ▼                     ▼                     ▼
        ┌────────────────┐   ┌──────────────────┐   ┌────────────────┐
        │ Semantic Index │   │ Structural Index │   │ Lexical Index  │
        │                │   │                  │   │                │
        │ embeddings     │   │ symbols          │   │ FTS/BM25       │
        │ chunks         │   │ imports          │   │ ripgrep        │
        │ docs           │   │ calls            │   │ exact matches  │
        └───────┬────────┘   │ references       │   └───────┬────────┘
                │            │ inheritance      │           │
                │            │ tests            │           │
                │            └────────┬─────────┘           │
                │                     │                     │
                └─────────────────────┼─────────────────────┘
                                      │
                                      ▼
                         ┌────────────────────────────┐
                         │ Repository Knowledge Store │
                         │                            │
                         │ files                      │
                         │ symbols                    │
                         │ relationships              │
                         │ chunks                     │
                         │ Git history                │
                         │ tests                      │
                         │ memory                     │
                         │ metadata                   │
                         └─────────────┬──────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
              ┌───────────┐      ┌───────────┐      ┌───────────┐
              │  SQLite   │      │  Qdrant   │      │   Git     │
              │ metadata  │      │ vectors   │      │ history   │
              └───────────┘      └───────────┘      └───────────┘

                                       │
                                       ▼
                              ┌──────────────────┐
                              │      Ollama      │
                              │                  │
                              │ qwen3-coder:30b  │
                              │ qwen2.5-coder:7b │
                              │ qwen2.5-coder:1.5b
                              │ nomic-embed-text │
                              └──────────────────┘
```

---

## 4. Main Subsystems

### 4.1 Repository Scanner

Responsible for discovering what belongs to the repository.

It should understand:

- tracked files
- ignored files
- generated files
- binary files
- source files
- documentation
- tests
- configuration
- migration files
- build files

The scanner should respect:

```text
.gitignore
repo_intel ignore rules
generated-file heuristics
file-size limits
language allow/deny rules
```

Output:

```text
repository file inventory
```

### 4.2 Code Parser

The parser converts source code into meaningful structural units.

Primary technology:

```text
Tree-sitter
```

It should extract:

- functions
- methods
- classes
- interfaces
- modules
- imports
- exports
- inheritance
- routes
- constants
- configuration objects
- test definitions

Where deeper semantic indexers are available later, SCIP can augment this layer.

Important distinction:

```text
Tree-sitter = broad syntax coverage
SCIP        = deeper semantic relationships where supported
```

SCIP should enhance the platform, not become a mandatory dependency.

### 4.3 Chunking System

Code must not be chunked using arbitrary token windows.

Preferred units:

```text
function
method
class
interface
module
route
configuration section
documentation section
test
SQL statement
```

Each chunk should retain metadata like:

```text
repository
path
language
symbol
kind
start line
end line
parent symbol
imports
hash
last commit
```

This allows semantic search results to be traceable back to actual code.

### 4.4 Semantic Indexing

Use:

```text
Ollama
+
nomic-embed-text
+
Qdrant
```

Embeddings should be generated for:

- code chunks
- documentation
- configuration
- selected Git summaries
- architecture memory
- engineering discoveries

### 4.5 Lexical Retrieval

Semantic search is not enough for source code.

Exact names matter enormously.

Use:

```text
SQLite FTS5
ripgrep
```

for:

- symbol names
- configuration keys
- error messages
- environment variables
- API paths
- class names
- function names
- constants

### 4.6 Structural Code Graph

Represent relationships such as:

```text
file imports file
symbol calls symbol
symbol references symbol
class inherits class
route invokes service
service invokes repository
test covers symbol
configuration influences component
migration modifies table
```

This graph enables:

- caller lookup
- dependency lookup
- related-file discovery
- blast-radius analysis
- architectural navigation

Initially, this can live in SQLite.

### 4.7 Git Intelligence

Index:

```text
commit messages
changed files
change relationships
tags
branches
selected diff summaries
```

Useful questions:

- Why is this guard condition here?
- When did this behavior change?
- What files usually change together?
- What was modified when this bug was fixed?

### 4.8 Test Intelligence

Tests should be first-class repository entities.

The system should attempt to map:

```text
implementation
    ↕
tests
```

using:

- imports
- symbol references
- naming conventions
- test execution history later
- coverage data later

---

## 5. Retrieval Engine

The retrieval engine should query several systems in parallel:

```text
user query
   │
   ├── semantic search
   ├── lexical search
   ├── symbol search
   ├── dependency graph
   ├── test relationships
   └── Git history
```

Then combine results.

For ranking, start simple.

A strong initial method is:

```text
Reciprocal Rank Fusion
```

Later, a local reranker can improve ordering.

---

## 6. Context Composer

The context composer is arguably the core product.

It converts raw retrieval results into a compact engineering briefing.

Instead of returning many unrelated chunks, return a structured package containing:

```text
TASK
PRIMARY IMPLEMENTATION
DIRECT CALLERS
TESTS
CONFIGURATION
RELATED HISTORY
LIKELY CHANGE SURFACE
```

The model then reads those files directly.

---

## 7. Blast-Radius Engine

Given:

```text
change AuthService.refresh_token
```

the system should estimate affected areas.

Signals can include:

```text
direct callers
indirect callers
imports
shared interfaces
test coverage
configuration
Git co-change history
public API usage
dependency distance
```

Output should be evidence-based rather than pretending certainty.

---

## 8. Engineering Memory

Over time, repositories contain information that is not obvious from source.

Examples:

```text
All database writes must use Repository layer.
This worker must remain idempotent.
API v1 is frozen for backward compatibility.
This folder is generated and must not be edited manually.
```

Store durable discoveries separately from embeddings.

Potential layout:

```text
.repo_intel/
└── memory/
    ├── architecture.md
    ├── conventions.md
    ├── decisions.md
    └── discoveries.jsonl
```

Memory should be evidence-linked.

---

## 9. Incremental Indexing

Track:

```text
file hash
Git HEAD
dirty files
parser version
embedding model
index schema version
```

Update path:

```text
file changes
    ↓
hash comparison
    ↓
reparse changed files only
    ↓
remove stale symbols/chunks
    ↓
rebuild affected relationships
    ↓
embed changed chunks
    ↓
update vector store
```

No full repository rebuild unless necessary.

---

## 10. MCP Layer

Potential API:

```text
repo_context
repo_search
repo_symbol
repo_references
repo_dependencies
repo_tests
repo_history
repo_impact
repo_architecture
repo_status
```

The most important tool should be:

```text
repo_context(query)
```

It should orchestrate multiple internal systems so agents do not need many low-level calls.

---

## 11. Agent Interaction Model

Desired workflow:

```text
Developer
   ↓
OpenCode
   ↓
repo_context(...)
   ↓
repo_intel identifies implementation, callers, tests, config, Git history
   ↓
OpenCode reads actual files
   ↓
OpenCode plans
   ↓
OpenCode edits
   ↓
tests run
   ↓
repo_intel can reevaluate impact
```

---

## 12. Recommended Technology Stack

| Area | Technology |
|---|---|
| Core language | Python 3.12+ |
| Dependency management | `uv` |
| CLI | Typer |
| Data models | Pydantic / dataclasses |
| Local inference | Ollama |
| Primary model | `qwen3-coder:30b` |
| Helper model | `qwen2.5-coder:7b` |
| Lightweight model | `qwen2.5-coder:1.5b` |
| Embeddings | `nomic-embed-text` |
| Vector DB | Qdrant |
| Metadata DB | SQLite |
| Full-text search | SQLite FTS5 |
| Exact search | ripgrep |
| Parsing | Tree-sitter |
| Semantic code index | SCIP later |
| Git intelligence | native Git CLI |
| Agent protocol | MCP |
| Coding UI / agent | OpenCode |
| Testing | Pytest |
| Static typing | MyPy |
| Lint / format | Ruff |
| Service runtime | local processes + Docker where justified |

---

## 13. Why SQLite + Qdrant

Use SQLite for:

```text
files
symbols
relationships
repository metadata
Git metadata
test mappings
memory references
index state
```

Use Qdrant for:

```text
embeddings
semantic similarity
```

Avoid putting everything into a vector DB.

Avoid adopting Neo4j prematurely.

---

## 14. Process / Runtime Architecture

```text
Host
│
├── OpenCode
├── Ollama
├── repo-intel CLI
├── repo-intel MCP
├── Git
├── ripgrep
│
└── Docker
     └── Qdrant
```

---

## 15. Mature Repository Structure

```text
repo_intel/
│
├── README.md
├── pyproject.toml
├── uv.lock
├── Makefile
├── AGENTS.md
├── opencode.jsonc
├── compose.yaml
│
├── config/
│   ├── repo_intel.toml
│   ├── models.toml
│   └── retrieval.toml
│
├── src/repo_intel/
│   ├── cli/
│   ├── config/
│   ├── repository/
│   ├── parsing/
│   ├── indexing/
│   ├── embeddings/
│   ├── storage/
│   ├── retrieval/
│   ├── context/
│   ├── git/
│   ├── tests_intel/
│   ├── impact/
│   ├── memory/
│   ├── mcp/
│   └── runtime/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
│
├── benchmarks/
├── scripts/
├── docs/
│   ├── architecture/
│   ├── operations/
│   ├── design/
│   └── benchmarks/
│
└── .repo_intel/
    ├── metadata.db
    ├── cache/
    ├── state/
    ├── logs/
    └── memory/
```

This is illustrative and should not be created all at once.

---

## 16. User-Facing CLI

Eventually:

```bash
repo-intel init
repo-intel doctor
repo-intel index
repo-intel update
repo-intel status

repo-intel search "token refresh"
repo-intel symbol AuthService
repo-intel references AuthService.refresh_token
repo-intel context "change authentication retry behavior"
repo-intel impact AuthService.refresh_token
repo-intel history AuthService.refresh_token

repo-intel mcp
```

Possibly later:

```bash
repo-intel serve
```

---

## 17. Indexing Workflow

```text
repo-intel index
      │
      ▼
Repository scanner
      │
      ▼
File classifier
      │
      ├── source
      ├── docs
      ├── config
      ├── tests
      └── ignore
      │
      ▼
Tree-sitter
      │
      ▼
Symbols + relationships
      │
      ├───────────────┐
      ▼               ▼
Chunk builder      Graph builder
      │               │
      ▼               ▼
Embeddings        SQLite
      │
      ▼
Qdrant
      │
      ▼
Index complete
```

---

## 18. Query Workflow

```text
repo_context("change retry logic")
             │
             ▼
       Query analysis
             │
   ┌─────────┼─────────┐
   ▼         ▼         ▼
semantic   lexical   graph
   │         │         │
   └─────────┼─────────┘
             ▼
         fusion
             │
             ▼
      related tests
             │
             ▼
        Git history
             │
             ▼
        reranking
             │
             ▼
        deduplication
             │
             ▼
       token budgeting
             │
             ▼
      context package
```

---

## 19. Context Budgeting

Do not maximize context usage.

Optimize it.

For example, on a 32K model context:

```text
system/tool context       4–6K
conversation              3–5K
repo_intel context        8–12K
direct source reads       6–8K
generation reserve        5–8K
```

The exact numbers should evolve through benchmarking.

---

## 20. Benchmarking Strategy

Build controlled repositories with known answers.

Measure:

```text
Did retrieval find the correct primary file?
Did it identify the right symbol?
Did it include callers?
Did it identify tests?
Did it find relevant config?
Did it include relevant history?
How much irrelevant context was returned?
How many tokens were consumed?
Did the agent solve the task?
Did the agent modify unrelated files?
```

Eventually track:

```text
top-1 retrieval accuracy
top-5 retrieval recall
context precision
task success rate
token usage
indexing duration
incremental update duration
```

---

## 21. Security Model

Enforce:

- bind local services to localhost
- no cloud upload by default
- avoid logging source content unnecessarily
- never store secrets in embeddings
- recognize `.env`, credentials, keys, and certs
- provide exclusion rules
- avoid indexing binary/secrets directories
- redact secrets from diagnostic output
- do not expose MCP remotely by default

---

## 22. Secret Detection / Exclusion

Examples:

```text
.env
.pem
.key
credentials.json
secrets.yaml
SSH keys
API tokens
private certificates
```

Default behavior:

```text
do not embed
do not log
do not persist content
```

Metadata-only treatment may be appropriate.

---

## 23. Scaling Model

### Small Repository

```text
< ~2,000 useful source files
```

Simple full indexing.

### Medium Repository

```text
~2,000–20,000
```

Incremental updates and batched embeddings.

### Large Repository

```text
20,000+
```

Need:

- repository partitions
- priority languages
- generated-file filtering
- embedding queues
- selective Git history
- potentially multiple Qdrant collections

The high-level architecture should remain the same.

---

## 24. Future Multi-Repository Support

Design identifiers around:

```text
repository_id
```

rather than assuming one global repository forever.

Eventually support:

```text
frontend repo
backend repo
shared SDK
infra repo
```

and cross-repository impact questions.

---

## 25. Future Architecture Intelligence

Eventually derive higher-level concepts:

```text
bounded contexts
services
packages
entry points
APIs
data stores
message flows
test layers
deployment units
```

Then provide:

```bash
repo-intel architecture
```

with a machine-generated, evidence-based overview.

---

## 26. Future Repository Visualization

Possible views:

```text
dependency graph
call graph
module map
change heatmap
Git co-change graph
test coverage relationships
architecture map
```

This should come after the intelligence engine works.

---

## 27. What Not to Build Initially

Avoid early overengineering:

```text
Kubernetes
multi-agent systems
Neo4j
Elasticsearch
Kafka
microservices
distributed indexing
cloud inference abstraction
heavy UI
autonomous repair agents
complex workflow engine
```

The first useful product can remain a local Python system.

---

## 28. Suggested Evolution Path

```text
Foundation
   ↓
Repository scanning
   ↓
Parsing + symbols
   ↓
Metadata store
   ↓
Embeddings
   ↓
Hybrid retrieval
   ↓
Context composition
   ↓
MCP integration
   ↓
Dependency intelligence
   ↓
Git intelligence
   ↓
Test intelligence
   ↓
Blast radius
   ↓
Persistent engineering memory
   ↓
Benchmarking / hardening
   ↓
Visualization / advanced features
```

---

## 29. End-State Developer Experience

```bash
cd my-repository

repo-intel init
repo-intel index
repo-intel status

opencode
```

Developer asks:

> Change how failed token refresh is retried.

OpenCode calls `repo_intel` and receives:

```text
Primary:
  auth/service.py::refresh_token

Related:
  retry/policy.py
  session/manager.py

Tests:
  test_refresh.py
  test_retry.py

Config:
  auth.yaml

History:
  commit related to duplicate refresh

Impact:
  client/API and session lifecycle
```

Then it reads the actual files and works.

---

## 30. Success Definition

`repo_intel` succeeds if a local coding agent working on an unfamiliar repository can:

```text
understand faster
search less randomly
read fewer irrelevant files
identify dependencies more accurately
find relevant tests
understand historical intent
estimate change impact
use fewer prompt tokens
make safer changes
```

The project is not fundamentally a vector database or a RAG wrapper.

It is better thought of as:

> **A local repository knowledge and navigation engine for software-engineering agents.**

---

## 31. Project Positioning

`repo_intel` is not:

- an autonomous software factory
- an IDE replacement
- a code-generation product by itself
- a general knowledge RAG system
- a multi-agent orchestration platform

It is:

> A repository intelligence substrate that can be consumed by coding agents and developer tools.

---

## 32. Architectural Responsibility Boundaries

### repo_intel owns

- repository scanning
- parsing
- indexing
- repository metadata
- semantic retrieval
- lexical retrieval
- dependency intelligence
- Git intelligence
- test intelligence
- context composition
- blast-radius analysis
- repository memory
- MCP exposure

### Ollama owns

- local inference
- local embedding generation

### Qdrant owns

- vector storage
- similarity search

### SQLite owns

- structured repository metadata
- relationship data
- index state
- FTS5 lexical index

### OpenCode owns

- developer interaction
- coding-agent orchestration
- authoritative source-file reads
- source modifications
- shell/tool execution

---

## 33. Guiding Rule

The central design principle for the entire project is:

> **Do not give the model the repository. Give the model the smallest high-quality evidence set required to understand the task.**

Everything else in `repo_intel` exists to make that evidence set accurate, explainable, current, and efficient.
