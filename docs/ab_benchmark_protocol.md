# A/B Benchmark Protocol — repo_intel vs Bare Agent on HTTPX

## 1. Objective

Determine whether repo_intel improves a coding agent's ability to perform 
realistic implementation tasks on an unfamiliar codebase, compared to the 
same agent with only filesystem access.

The HTTPX codebase is used because:
- It is already indexed in the live repo_intel stack.
- It has well-defined public APIs, clear module boundaries, and a comprehensive
  test suite for verifying correctness.
- The previous QA benchmark identified its strengths and weaknesses.

## 2. Experimental Design

### 2.1 Agents

| Variable | Agent A (control) | Agent B (treatment) |
|---|---|---|
| LLM | Same model | Same model |
| Model ID | `ollama/qwen3.6-resilient` | `ollama/qwen3.6-resilient` |
| Temperature | Same | Same |
| System prompt | Standard coding agent | Standard + repo_intel tool descriptions |
| repo_intel MCP | Disabled | Enabled (port 8765) |
| Filesystem read | Enabled (`cat`, `grep`, `head`, etc.) | Enabled (same tools) |
| File write | Enabled | Enabled |
| Python execution | Enabled (for running tests) | Enabled (same) |
| Token budget | Same per task | Same per task |

### 2.2 Repository State

- HTTPX repository as currently mounted: `/repos/httpx` (read-only in containers).
- Agent B uses repo_intel with the active generation 
  (`c8b6a4d1-df61-4f4a-9b2f-d582cce1c879`).
- Both agents work on a **writeable copy** of HTTPX to avoid polluting the 
  indexed read-only mount. A git worktree or symlink is created at task start 
  and discarded at task completion.
- Both agents receive the same starting state (HTTPX at commit 
  `b5addb64f0161ff6bfe94c124ef76f6a1fba5254`).

### 2.3 Evaluation Method

**Independent reviewer** scores each task output without knowing which agent 
produced which result (blind evaluation).

Scoring rubric per task (1-5 scale):

| Score | Meaning |
|---|---|
| 5 | Complete, correct solution; compiles/tests pass; no unnecessary changes |
| 4 | Correct solution; minor issues; tests pass with small fixes |
| 3 | Partially correct; correct approach but incomplete |
| 2 | Incorrect approach; some relevant understanding |
| 1 | No correct understanding; hallucinated or irrelevant changes |

Additionally, each task receives a **binary pass/fail** on whether the 
changes compile and pass the relevant existing tests.

## 3. Tasks

Eight implementation tasks are designed to test different capabilities. Each 
task includes a description and acceptance criteria.

### Task 1 — Add `options()` method to Client and AsyncClient

**Description:** HTTPX has `get()`, `post()`, `put()`, `patch()`, `delete()`, 
and `head()` convenience methods on `Client` and `AsyncClient`. Add an 
`options()` method.

**Acceptance criteria:**
- Method exists on both `Client` and `AsyncClient` with correct signatures.
- Method exported in `httpx/__init__.py` module-level `options()`.
- Existing tests still pass.
- Follows the existing pattern used by other HTTP verb methods.

**Tests capability:** Symbol lookup, understanding class structure, 
consistent pattern application.

---

### Task 2 — Add a `max_redirects` parameter to Client constructor

**Description:** Currently, the maximum number of redirects is hardcoded 
(checked in `_send_handling_redirects()`). Add a `max_redirects` parameter 
to `Client`/`AsyncClient` constructors, defaulting to the existing value.

**Acceptance criteria:**
- New parameter accepted in `Client.__init__()` and `AsyncClient.__init__()`.
- Parameter stored as instance attribute.
- `_send_handling_redirects()` uses the instance attribute instead of the 
  hardcoded value.
- Default value equals existing hardcoded value.
- Tests still pass.

**Tests capability:** Execution tracing, understanding parameter flow through 
method call chains.

---

### Task 3 — Add a `trace()` debug logging option

**Description:** Implement a `trace` boolean parameter on `Client`/`AsyncClient` 
that, when True, logs request URL and response status code at DEBUG level 
before sending and after receiving.

**Acceptance criteria:**
- `trace` parameter in constructors, default False.
- When True, logs `Request: {method} {url}` before send and 
  `Response: {status_code}` after receive.
- Logging happens at the `_send_single_request()` level or equivalent.
- Does not break existing behavior when False (default).

**Tests capability:** Finding the right insertion point, 
understanding the request lifecycle.

---

### Task 4 — Fix cookie handling on cross-domain redirect

**Description:** When a redirect changes the domain, cookies set by the 
original domain should not be sent to the new domain. Implement domain-aware 
cookie filtering in `_build_redirect_request()`.

**Acceptance criteria:**
- When redirect crosses from `example.com` to `other.com`, cookies from 
  `example.com` are not included in the redirected request.
- Cookies for the new domain are preserved.
- Does not affect same-domain redirects.
- Existing tests still pass.

**Tests capability:** Cross-module understanding (client + cookies + redirects), 
implementing new behavior.

---

### Task 5 — Add HTTP/2 priority support

**Description:** Add an optional `priority` parameter to request methods that 
sets the HTTP/2 `PRIORITY` pseudo-header when using an HTTP/2 transport.

**Acceptance criteria:**
- `priority` parameter accepted by `request()`, `send()`, etc.
- When provided and transport is HTTP/2, the priority is included in the 
  request headers.
- Does not affect HTTP/1.1 requests.
- Gracefully handled when transport doesn't support priority.

**Tests capability:** Understanding transport abstraction layer, 
conditional behavior.

---

### Task 6 — Add `trust_env` override for specific proxies

**Description:** The `trust_env` parameter controls whether HTTPX reads proxy 
configuration from environment variables (`HTTP_PROXY`, etc.). Implement per-proxy 
scheme override, so `trust_env=False` can be overridden for specific schemes.

**Acceptance criteria:**
- New parameter or option to selectively enable env-based proxy for specific 
  schemes despite `trust_env=False`.
- Integrates with existing `_get_proxy_map()` logic.
- Does not change default behavior.

**Tests capability:** Understanding proxy handling, modifying existing 
configuration logic.

---

### Task 7 — Add response time metrics

**Description:** Add a `elapsed` attribute to `Response` that records the time 
taken from request send to response complete (similar to Python requests library).

**Acceptance criteria:**
- `Response.elapsed` returns a `datetime.timedelta`.
- Time is measured from the start of `handle_request()` to completion.
- Available on both sync and async responses.
- Existing Response interface not broken.

**Tests capability:** Finding the right place to hook timing, 
understanding response creation flow.

---

### Task 8 — Add custom header validation hook

**Description:** Implement an optional `event_handler` that fires with the 
request headers before they are sent, allowing the caller to validate or 
modify headers programmatically.

**Acceptance criteria:**
- New hook mechanism that receives headers before send.
- Hook can modify headers in-place or return replacement headers.
- Integrates with existing event hook system (or creates a parallel mechanism).
- Synchronous and asynchronous variants.
- Default: no-op, no performance impact.

**Tests capability:** Understanding event hook architecture, 
implementing extensibility.

## 4. Measurement Instruments

### 4.1 Primary Metrics

| Metric | How Measured |
|---|---|
| **Task score** | Independent reviewer, 1-5 blind rubric |
| **Test pass/fail** | `cd <worktree> && pytest tests/test_relevant.py -v` |
| **Solution correctness** | Does the change do what the task asks? |
| **Unnecessary changes** | Count of unrelated file modifications |

### 4.2 Instrumentation Metrics

| Metric | How Measured | Agent A | Agent B |
|---|---|---|---|
| **Token usage** | Model API response headers / usage field | Yes | Yes |
| **File reads** | Count of `cat`/`head`/grep calls in shell history | Yes | Yes |
| **repo_intel calls** | — | 0 (N/A) | MCP call log |
| **Wall time** | Task start to "done" signal | Yes | Yes |
| **Iterations** | Number of edit-compile-test cycles | Yes | Yes |

### 4.3 Session Recording

Both agents produce a session log that captures:
1. Model prompts and responses (for token counting)
2. Shell commands executed (for file-read counting)
3. MCP tool calls (Agent B only)
4. Final diff of changes made

## 5. Procedure

### 5.1 Setup (per task)

1. Create a git worktree of HTTPX from the indexed commit.
2. Record the starting state (`git rev-parse HEAD`).
3. Present the task description to both agents.
4. Start the timer.

### 5.2 Execution

1. Agent works on the task, with full access to its tools.
2. Token budget enforced: 120,000 tokens per task. If exceeded, the agent 
   reports with what it has completed.
3. When the agent indicates completion (or budget exhausted), stop the timer.
4. Record the final state as a git diff.

### 5.3 Verification

1. Run HTTPX's test suite on each agent's changes:
   ```bash
   cd <worktree> && python -m pytest tests/ -x -q --tb=short
   ```
2. Record pass/fail and any failures.
3. For tasks with more specific tests, run those directly:
   ```bash
   pytest tests/client/test_client.py -v -k "relevant_keyword"
   ```

### 5.4 Scoring

1. Annotate each task output with:
   - Task ID, Agent ID (A or B)
   - Token usage
   - File reads count
   - MCP calls (Agent B)
   - Wall time
   - Test pass/fail
   - Reviewer score (1-5)
2. Present both agents' results side-by-side to the independent reviewer.

### 5.5 Repeat

Each task is run once per agent. If there is a clear outlier (e.g., one agent 
fails due to tool error rather than reasoning), that task may be re-run.

## 6. Success Criteria

repo_intel is considered to add value if Agent B (with repo_intel) 
significantly outperforms Agent A (without) on:

- **Mean task score**: At least 1 point higher on the 1-5 rubric.
- **Token efficiency**: Uses fewer tokens to achieve equivalent or better 
  solutions.
- **File reads**: Fewer filesystem reads for equivalent understanding.
- **Correctness**: Same or higher test pass rate.

If Agent B performs worse or no better, repo_intel's value for coding tasks 
is unproven (though repository QA may remain valuable for exploration).

## 7. Constraints

- The existing Docker Compose stack is reused.
- The HTTPX read-only mount is not modified.
- repo_intel's regex parser is not changed during the benchmark.
- The embedding model remains `nomic-embed-text`.
- No new services, databases, or infrastructure.
- Agent session logs are stored in `benchmark/ab_runs/` for auditability.

## 8. Risk Mitigation

| Risk | Mitigation |
|---|---|
| Agent B overuses MCP calls | Token budget cap + manual inspection |
| Agent A gets lucky with grep | Tasks designed to require deep understanding, not just keyword search |
| Subjective reviewer bias | Blind evaluation + written justification per score |
| Model variability | Same model, same temperature, same system prompt structure |
| repo_intel index becomes stale | Index is not modified during benchmark |

## 9. Timeline (estimated)

| Phase | Duration |
|---|---|
| Protocol review | 0.5 day |
| Per-task execution (8 tasks × 2 agents) | 1-2 days |
| Independent review & scoring | 0.5-1 day |
| Analysis & report | 0.5 day |
| **Total** | **2.5-4 days** |
