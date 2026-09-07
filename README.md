# Sengol Agent Example — OSFI E-23 RAG Financial Advisor

A runnable, regulated AI agent for Canadian banking. This is the reference
agent used by the hosted trial's seed data and by the quickstart — the
fastest way to see Sengol's full governance lifecycle end to end.

## The 15-minute journey

1. **Seed the agent** — `docker compose up -d && make seed` (no LLM key needed).
2. **Look at a trace in the Console** — open http://localhost:8080/traces and
   inspect a signed record.
3. **Decide a review item** — open Console → Governance and approve or
   reject the item the seeded failing traces put in the review queue.
4. **Export an evidence pack** — `make export-evidence` writes `pack.zip`.
5. **Verify it on your laptop** — `pip install sengol-verify && sengol-verify pack.zip`.

The rest of this README walks each step in more depth, plus the delegation
chain, drift detection, and obligation drill-down demos.

## Prerequisites

- Docker 24+
- `sengol` CLI: `pip install "sengol>=2.0,<3"` (for `make gate`-based targets, run from the host)
- An Anthropic API key (optional — only needed by `make live` and by the
  LLM-judge evaluators in `make pre-deploy-check` / CI; `make seed` / `make demo`
  need no key at all)
- An OpenAI API key (optional — only needed when `SENGOL_MODEL_PROVIDER=openai`)

## Quickstart

```bash
git clone https://github.com/sengol-io/agent-example
cd agent-example
cp .env.example .env       # add your ANTHROPIC_API_KEY (optional — see step 1)
docker compose up -d       # starts postgres + sengol-api + rag-advisor
make seed                  # step 1 — replays the pre-recorded traces into the Console
```

Services:
- **Sengol Console** (traces, governance tab): http://localhost:8080
- **RAG Financial Advisor** (the agent): http://localhost:3000

The audit store is always the API — `ApiAuditSink` sends every signed record
to `SENGOL_API_URL` (authenticated with `SENGOL_API_TOKEN`). There is no
in-process fallback in this example; a forgotten credential fails loudly
instead of silently discarding evidence.

## Step 1 — seed the agent

```bash
make seed        # alias for `make demo`
```

This replays `traces/passing_traces.jsonl` and `traces/failing_traces.jsonl`
through `sengol gate` into the running API. `PIIEvaluator` (deterministic)
scores every row for real with no key required; the LLM judges
(`FaithfulnessEvaluator`, `HallucinationEvaluator`) fail closed and log
rather than crash when `ANTHROPIC_API_KEY` is unset — either way both trace
sets land in the Console as signed `AuditRecord`s.

## Step 2 — look at a trace in the Console

Open http://localhost:8080/traces. The passing traces show green; the
failing traces show a PII or hallucination badge. Click one to see the full
signed record — prompt, response, per-evaluator scores, and the HMAC that
covers all of it.

## Step 3 — decide a review item

A failing trace with a CRITICAL finding lands in the human review queue.
Open Console → **Governance**, find the pending item, and approve or reject
it (a rejection requires a `failure_mode`). Review decisions are append-only
signed evidence, exactly like the traces that produced them.

## Step 4 — export an evidence pack

```bash
make export-evidence
```

Wraps `sengol audit export --tenant $(SENGOL_TENANT_ID) --agent rag-advisor-001
--out pack.zip` — a self-contained bundle of `AuditRecord`s, countersignatures,
anchor receipts, and public-key metadata for offline verification.

## Step 5 — verify it on your laptop

```bash
pip install sengol-verify
sengol-verify pack.zip
```

No network access and no Sengol server required — `sengol-verify` recomputes
every HMAC from the bundle's own bytes against the embedded public keys.

## Before deploying — run the compliance gate

```bash
# Gate FAILS on failing traces (PII leak + hallucination) — expect exit code 1
make pre-deploy-check

# Gate PASSES on clean traces — expect exit code 0
make test-ci-pass
```

## After deploying — exercise the agent

```bash
make live              # test-happy + test-pii-fail against the running agent (needs ANTHROPIC_API_KEY)
make test-happy        # clean question → answer + green badge in Console
make test-pii-fail     # PII trigger → response blocked by GuardrailRuntime
make verify-audit      # HMAC-verify the most recent AuditRecord
make open-console      # open http://localhost:8080
```

## See the delegation chain

The `/ask` endpoint never delegates to another agent or a risky tool — so to see
Sengol's delegation-chain governance in action, replay a synthetic OTLP trace
that simulates the RAG advisor calling a declared tool and then an undeclared
one:

```bash
make replay-delegation-trace
```

This registers `rag-advisor-001`'s declared tool capabilities
(`knowledge_base_lookup`), exchanges the registration secret for a signed JWT,
and posts `traces/delegation_hops_otlp.json` to `POST /v1/traces/otlp` — the
same OTLP ingestion endpoint any OTel-instrumented framework uses. The trace
contains two spans under one agent span:

- `knowledge_base_lookup` — **declared** (in `declared_capabilities`) → passes.
- `wire_transfer` — **undeclared** → `UnauthorizedDelegation` (CRITICAL).

The command prints a short-lived API token — paste it into the Console's
**API token** field (sidebar), then:

- **Traces** (http://localhost:8080/traces) — the `wire_transfer` hop shows a
  **CRITICAL** badge in the Severity column.
- **Call Graph** — expand that row and click "View call graph →" (or go
  directly to `/traces/{trace_id}/call-graph`) to see both hops rendered as
  declared / undeclared cards.

Both hops are signed `AgentCallRecord` evidence (`record_type=sengol.agent.call`,
HMAC-verifiable like every other AuditRecord) — nothing here is Console-only
state.

## See drift detection

Sengol's `DriftDetector` runs a CUSUM (cumulative sum) test over the per-input
pass-rate stream and fires when the statistic crosses a decision interval —
sustained degradation, not a single bad response. `sengol.yaml`'s
`governance.drift_response_policy` (`on_drift: alert_only`) and
`governance.drift_evidence_policy` (`level: breach`) turn this on; `controlbook.yaml`'s
`gold_score_formula.minimum_floor` (0.80) is the reference pass rate the CUSUM
statistic tracks against.

```bash
make check-drift
```

This runs `traces/drift_stream.jsonl` (18 rows: 8 clean, then 10 that leak a
SIN + email) through the same `osfi-e23-qa` suite as `make pre-deploy-check`,
against the running API stack (`make up`). Each PII-leaking row trips
`PIIEvaluator` (a CRITICAL evaluator), which short-circuits the LLM-judge
stage per-input, so the pass-rate stream drops sharply regardless of the LLM
judges' own verdicts. Watch for `audit.written` lines near the end of the
output — each one is a signed `AuditRecord` with
`failure_mode=DRIFT_THRESHOLD_BREACH`, written by the same
`DriftEvidencePipeline` a production deployment uses. With `ANTHROPIC_API_KEY`
set and the clean rows correctly scored as passing, expect 5 breaches
concentrated in the PII tail; without a key the LLM judges fail closed on
every row (logged, not a crash) so the pass rate is degraded throughout and
you'll see more (9, on this fixture) — either way it's the real CUSUM
detector firing on real evidence, not a canned demo.

> **Why not `sengol check-drift` directly?** That CLI subcommand only *reads*
> durable drift evidence a live server + async eval worker already wrote to a
> persistent audit store — it takes `--agent`/`--suite`/`--since`, not a
> dataset, and can't replay a fixture. The CUSUM detector itself is wired
> into `gate` (`AsyncEvalWorker._on_result_hook`), so `make check-drift`
> drives it that way instead — same detector, same signed evidence.

## Drill into an obligation

Open the **Governance** tab (http://localhost:8080/governance), enter
`rag-advisor-001` as the Agent ID under **Obligation Coverage**, and click
**Load**. Click the caret on an obligation row (e.g. `E23-3.2`) to expand the
evaluator × record drill-down matrix — every signed record that contributed to
that obligation's pass rate, with its per-evaluator scores and severity. Click
"trace →" on a row to jump to that record's Call Graph.

These drill-down numbers come from the same `roll_up_obligations()` path that
drives `sengol report generate` — the Console isn't a second source of truth,
it's a read view over the signed evidence chain.

## Watch drift happen (self-driving demo)

To *see* quality drift + alerts without hand-crafting a decline, drive a degrading
workload at the running stack. `simulate.py` posts batches whose PII-leak rate rises,
so the `E23-3.2` (`PIIEvaluator`) pass rate falls below the `0.90` baseline, Sengol's
**CUSUM `DriftDetector`** accumulates, and once it exceeds `cusum_threshold: 5.0` a
`DriftAlert` fires — surfacing in the `eval.drift_threshold_breach` **webhook**
(`SENGOL_DRIFT_WEBHOOK`) and the **Console → Traces → Drift** live chart.

```bash
make up                       # persistent Postgres audit store (drift needs history)
export SENGOL_DRIFT_WEBHOOK="https://hooks.slack.com/services/..."   # optional
make simulate-drift           # post a full multi-day decline, then check-drift → DRIFT DETECTED
```

This runs **without an Anthropic key** — it uses the deterministic `PIIEvaluator` via an
additive `sengol.drift.yaml`, so the main `sengol.yaml` compliance gate is untouched.

Two more ways to drive it against a **deployed** environment (set the `SENGOL_API_URL` /
`SENGOL_API_TOKEN` repo secrets):

- **On-demand:** GitHub → **Actions → Drift Simulation → Run workflow** (`days=7`) trips drift
  immediately for a live demo.
- **Scheduled:** the daily `cron` in `.github/workflows/drift-sim.yml` posts a degraded batch
  each day; the CUSUM accumulates until it breaches on its own.

Swap `on_drift: alert_only` in `sengol.drift.yaml` for `trigger_reeval` or `suspend_agent`
(with `require_approval: true`, which lands in **Governance → Open Escalations** with a
countdown) to demo the other drift responses. See the
[Drift Detection & Alerts guide](https://docs.sengol.io/guides/drift-monitoring).

## What this demonstrates

| Governance angle | Mechanism |
|-----------------|----------|
| Build-time eval | `sengol gate` on JSONL trace files |
| CI gate | GitHub Actions with `sengol-github-action` |
| Production guardrail | `GuardrailRuntime` wraps every `/ask` response |
| HMAC audit records | Every response → signed `AuditRecord` → the Sengol API |
| Compliance report | `sengol report generate ...` (JSON + PDF) |
| Drift detection | CUSUM `DriftDetector` via `make check-drift` |
| Offline verification | `sengol audit export` → `sengol-verify` |
| Console UI | Traces, Governance tab, obligation coverage |

## Files

| File | Purpose |
|------|--------|
| `docker-compose.yml` | postgres + sengol-api + rag-advisor |
| `.env.example` | Environment variable template |
| `sengol.yaml` | Agent governance config (the compliance gate) |
| `sengol.drift.yaml` | Additive drift-demo config — deterministic `PIIEvaluator` + CUSUM `governance.drift` |
| `simulate.py` | Emits degrading batches (rising PII-leak rate) to drive the drift demo |
| `controlbook.yaml` | OSFI E-23 obligation mappings |
| `Makefile` | Developer shortcuts (`seed`/`demo`, `live`, `export-evidence`, `simulate-drift`, `check-drift`, ...) |
| `agent/main.py` | FastAPI agent with GuardrailRuntime |
| `agent/knowledge_base.py` | 5 Canadian banking product facts |
| `traces/passing_traces.jsonl` | 10 clean traces (CI gate passes) |
| `traces/failing_traces.jsonl` | 5 failing traces (PII + hallucination) |
| `traces/delegation_hops_otlp.json` | OTLP trace (`POST /v1/traces/otlp`) with a declared + an undeclared delegation hop — `make replay-delegation-trace` |
| `traces/drift_stream.jsonl` | 8 clean + 10 PII-leaking traces — a pass-rate stream that trips the CUSUM `DriftDetector` — `make check-drift` |
| `.github/workflows/sengol.yml` | CI gate workflow |
| `.github/workflows/drift-sim.yml` | Drift simulation — scheduled cron + on-demand `workflow_dispatch` |

## ControlBook — OSFI E-23 obligations

| Obligation | Evaluator | Risk | Threshold | Notes |
|-----------|-----------|------|-----------|------|
| E23-3.2 (PII protection) | `PIIEvaluator` | HIGH | 100% pass | CRITICAL veto — blocks response |
| E23-3.1 (faithfulness) | `FaithfulnessEvaluator` | HIGH | 90% pass | CI-only (LLM judge) |
| E23-6.1 (drift monitoring) | `DriftMonitorPresent` | HIGH | 95% pass | Deterministic check |

> **Note:** `PIIEvaluator` is deterministic and runs in both CI and production (GuardrailRuntime).
> `FaithfulnessEvaluator` is an LLM judge and runs in CI only — never wired into GuardrailRuntime.

> **Security note:** The Docker Compose stack uses hardcoded development credentials.
> **Do not use in production.**
