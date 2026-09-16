# End-to-end journey suite for the example agent

**Date:** 2026-09-16
**Repository:** `sengol-io/sengol-example`
**Status:** design, approved in conversation; not yet implemented

## The problem

This repository is both a sales artifact and the product's only integration
test with a real agent in it. `docker compose up` gives a real Postgres, a
real Sengol API and `rag-advisor`, an actual agent container serving `/ask`.
Nothing about that is a fixture.

But almost none of it is exercised by automation.

- `sengol.yml` runs the compliance gate on every PR **against a remote server
  supplied through secrets**, with `fail-on-gate-failure: true`. A merge here
  can be blocked by someone else's environment being down. AWS-SETUP-RUNBOOK
  §2.4c is explicit that no example repo may hard-fail on `sengol-qa` in a
  per-PR gate, because that account is best-effort by decision.
- `drift-sim.yml` posts synthetic traffic to a deployed API on a schedule. It
  guards correctly on the environment being configured and exits 0 when it is
  not. It never touches the agent.
- **Nothing runs `make live`, `test-happy` or `test-pii-fail`.** The runtime
  guardrail — a PII answer being blocked in the response path — is the
  product's headline claim and has never been exercised by CI. It is a README
  instruction a human follows by hand. And running those targets would not be
  enough on its own: they pipe `curl` through `python3 -m json.tool`
  (`Makefile:50-59`), which checks that the reply is JSON and nothing more.
  `test-pii-fail` succeeds whether or not the SIN was blocked.

The Console is in the same position: the README's journey says "open
`/traces`", "open Governance and decide a review item", and no automation
opens either.

## Goals

Cover the README's 15-minute journey end to end, on every pull request, with no
real credentials and no dependency on any deployed environment:

seed → inspect a trace in the Console → decide a review item → export an
evidence pack → verify it offline, plus the PII block and drift detection.

## Non-goals, for this version

Delegation call graphs, quotas, MCP tool-integrity and multi-tenant isolation.
They are real and they are next; including them here trades a working suite for
a longer one.

Anything that asserts absence over a window — coverage gates and Merkle
anchoring cadence. These are unreachable from a bounded run and need deployed
agents on a schedule.

A caution about the source, because it changed this list. §2.4c also names
leader election, cross-replica SSE, shared rate-limit budget, retention
automation and multi-tenant isolation as reasons for deployed agents.
`STATUS.md` lists every one of those under **"Being cut"** — archived out of
the single-tenant appliance. `REPOSITORY-RESET-2026-09.md`, a founder ruling
of 2026-09-07, explicitly scopes the runbook's build order, and the runbook
sections are from August. Read §2.4b/c against `STATUS.md` before treating
anything in them as current.

## Where it lives

In this repository. The compose stack, the agent, the trace fixtures and the
Makefile targets are all already here; the suite is mostly assertions around
what exists. Putting it in `sengol` would mean a cross-repo checkout to test an
artifact that lives here.

## Shape

A new workflow stands the stack up itself — `docker compose up -d` for
Postgres, the API on `:8080` and `rag-advisor` on `:3000` — so the suite needs
no deployed environment and can gate pull requests honestly.

**The stack needs a `.env` that is not in the repository.** `docker-compose.yml`
declares `env_file: .env` for `rag-advisor` (line 46) and `.gitignore` lists
`.env`; only `.env.example` is tracked. A fresh checkout therefore cannot
`docker compose up` at all. The workflow copies `.env.example` to `.env` and
overrides the handful of values a keyless run needs. A `make .env` target does
the same for a human, so the README's 15-minute journey stops depending on an
undocumented manual step.

**The agent must not start before the model stub is listening.** `rag-advisor`'s
healthcheck calls its own `/health`, which never touches the model endpoint, and
its `depends_on` names only `sengol-api`. So on a cold start the agent can report
healthy while the stub is still binding, and the first `/ask` fails on an
upstream connection error a second before the stack would have worked. The stub
gets its own healthcheck, `rag-advisor` depends on it being healthy, and the
suite's first step waits on all three services rather than two.

**The suite asserts on responses itself rather than shelling out to `make live`.**
Those targets stay as human-facing demos; the suite issues the same two requests
and asserts on the bodies. The keyed job below asserts on bodies too, for the
same reason, but **not the same assertions** — its criteria are set out in its
own section, because a real provider's wording is not ours to predict.

**The `sengol` CLI comes from the image, not from PyPI.** The package is not
published — `https://pypi.org/pypi/sengol/json` returns 404 — which is what makes
the existing `sengol.yml` gate red on every pull request. The image installs the
package and `pyproject.toml` declares the `sengol` console script, so the binary
is there.

Getting at it needs its own compose service, not `exec` into `sengol-api`. That
service has no bind mount, so the CLI would run against the image filesystem with
none of this repository's `sengol.yaml`, `controlbook.yaml` or `traces/*.jsonl`
visible; and its environment carries only `DATABASE_URL`, the signing keys and
`SENGOL_API_TOKEN` — no `SENGOL_API_URL`, `SENGOL_AUDIT_URI`, `SENGOL_TENANT_ID`
or `ANTHROPIC_*` (`docker-compose.yml:18-32`). The gate exits 2 without the
audit-store URI. So `docker-compose.yml` gains a `sengol-cli` service on the same
image with the checkout bind-mounted, `env_file: .env`, and
`profiles: ["cli"]` so `docker compose up` does not start it. Every CLI step is
`docker compose run --rm sengol-cli sengol ...`, and the Makefile targets are
repointed at it so a human and CI run the identical command.

`datasets` is imported lazily, inside a function, for HuggingFace loading only,
so the extras the image already installs cover the local JSONL fixtures this
suite uses.

**The agent image has the same problem, and today it cannot be built at all.**
`agent/Dockerfile:8-13` installs `sengol>=2.0,<3` from PyPI, which does not
resolve, so `docker compose up --build` fails on `rag-advisor` before any health
check runs. Sourcing the CLI from the API image does nothing for this. The agent
image is therefore rebased on `ghcr.io/sengol-io/sengol-api:latest`, which
already carries the package, with `fastapi`, `uvicorn`, `anthropic` and `openai`
layered on top. Two things follow. The agent and the API provably run the same
`sengol` build, which for an integration test is an improvement rather than a
workaround. And the base is a build argument, so when the first release ships the
Dockerfile goes back to a plain `pip install sengol` in one line — because a
customer copying this repository will install from PyPI, and the reference agent
should show them that, not this bridge.

This also sharpens the ordering argument at the end of this document. Cutting a
first release is not only about turning the existing gate green; until it ships,
nobody who clones this repository can start the stack.

The suite is a Python test module that drives the same Makefile targets a human
follows, plus a Playwright layer over the Console. It reads `SENGOL_API_URL`
and `SENGOL_AGENT_URL` from the environment rather than hardcoding localhost.
That single decision is what lets the identical suite later run against a
deployed environment without a second implementation.

## What it asserts

| Step | Driven by | Assertion |
|---|---|---|
| Stack is up | compose + healthchecks | API, **model stub** and agent all answer before anything else runs |
| Seed | `make demo` | Signed `AuditRecord`s land for both trace sets |
| Runtime guardrail | agent `/ask`, fake model endpoint | Clean question returns `{"answer": ...}` with the fixture text byte-for-byte; PII question returns `{"blocked": true, "reason": "<PII failure mode>"}` with the SIN absent from the body, and a signed record carries that failure mode |
| Drift | `make check-drift` | At least one signed `DRIFT_THRESHOLD_BREACH` from the 18-row stream |
| Console — traces | Playwright | Mint an admin token, paste it into the sidebar field, open `/traces`, a seeded record is listed and its detail shows a valid signature — and, on the fabricated 8.5% return (`traces/failing_traces.jsonl:3`), the per-evaluator scores the README promises include a **failed `FaithfulnessEvaluator`**, named |
| Console — review | Playwright | Open Governance (`/governance`, the page the README names), find the pending item from the PII rows, decide it, reload, the decision persisted |
| Evidence | `make export-evidence` | `pack.zip` is produced |
| Offline verification | `sengol-verify pack.zip` | Exits 0 |
| Audit | `make verify-audit` | The latest record HMAC-verifies |

## The fake model endpoint

`agent/main.py` reads `os.environ["ANTHROPIC_API_KEY"]` directly (line 62) and
raises `KeyError` without it, so the agent cannot serve `/ask` in a keyless job.
The obvious fix — a third `SENGOL_MODEL_PROVIDER=stub` branch returning a canned
string — is wrong, and understanding why fixes the design.

`sengol.instrument()` patches `anthropic.resources.messages.AsyncMessages.create`
and `Messages.create` at the resource class level
(`sengol/instrument/anthropic_patch.py:51,90-91`). The guardrail — the
evaluators, the block decision, the signed audit record — lives *inside* that
patched method. A provider branch that returns a string without ever calling
`client.messages.create()` never enters it. No evaluator would run, nothing
would be blocked, no record would be written, and the assertion "the response
does not contain the SIN" would pass because the branch was never asked to emit
one. That test would prove nothing at all.

So the substitution has to sit below the SDK, not above it. The agent keeps its
Anthropic branch unchanged and the SDK is pointed at a local fake server:

```
ANTHROPIC_BASE_URL=http://model-stub:8081/agent
ANTHROPIC_API_KEY=sk-ant-stub-not-a-real-key
```

The Anthropic SDK reads `ANTHROPIC_BASE_URL` in its constructor — measured on
`anthropic` 1.6.0: with that variable set, `AsyncAnthropic(api_key="dummy")`
resolves `base_url` to it. **No change to `agent/main.py` is needed.** The agent
still constructs a real client, still calls `client.messages.create()`, still
enters the patched method, still runs the evaluators and writes the record. Only
the upstream HTTP call is replaced.

The fake server is a small service in this repository serving the Messages API
response shape, added to `docker-compose.yml`. It returns fixtures keyed by what
it is asked, not one canned answer:

| Request contains | Fixture response |
|---|---|
| the HISA rate question | a clean product answer, no PII |
| the "John Smith ... SIN" question | an answer that repeats `123456789` |
| anything else | a clean default |

**Agent traffic and judge traffic get separate routes.** The same endpoint also
serves the LLM-judge evaluators (see the gate section below), and a judge call is
not an agent call: it carries a compliance criterion and expects a verdict back,
in a strict format. Routing both through one table would hand a judge prompt
containing the HISA question the product answer, which `parse_judge_response`
rejects outright (`sengol/judges/_prompt.py:52-70`).

No prompt-sniffing is needed, because the two clients already have separate
configuration. `AnthropicJudgeClient` reads `JUDGE_LLM_BASE_URL`
(`sengol/judges/anthropic.py:63`), distinct from the SDK-wide
`ANTHROPIC_BASE_URL` the agent uses. The Anthropic SDK preserves a path prefix on
`base_url` — measured on 1.6.0: `base_url="http://host/judge"` resolves to
`http://host/judge/v1/messages` — so one service serves both:

```
ANTHROPIC_BASE_URL=http://model-stub:8081/agent    # the agent's answers
JUDGE_LLM_BASE_URL=http://model-stub:8081/judge    # the evaluators' verdicts
```

The judge route returns the exact three-line shape the strict parser requires —
`VERDICT: PASS|FAIL`, `REASON:`, `CONFIDENCE:` — and, like the agent route,
returns different fixtures for different inputs.

**It keys on the record and the evaluator, never on which file the record came
from.** "Everything in `failing_traces.jsonl` gets `FAIL`" is wrong and would
quietly hollow out the suite. Row 5 of that file is a straightforward GIC answer
that fabricates nothing; it is in the failing set because its
`drift_monitor_enabled` is `false`, which is `DriftMonitorPresent`'s business and
not the judge's. A fixture that failed it on faithfulness would write a finding
the record does not deserve, and the per-evaluator assertions and the compliance
roll-up would then be measuring my fixture routing rather than the suite's
wiring. So the fixture table lists the verdict each record actually warrants:
`FaithfulnessEvaluator` fails rows 3 and 4, the fabricated 8.5% return and the
fabricated promotional mortgage rate, and passes everything else including row 5
and all of `passing_traces.jsonl`.

The `FAIL` fixture is not decoration: the Console **traces** assertion below
requires a named failed `FaithfulnessEvaluator` on row 3, which an always-`PASS`
judge would never produce. It is not what raises the review item — rows 1 and 2
do that deterministically, whatever the judge says.

**Two distinct fixtures is the point.** A stub that always emitted a SIN would
block the clean case too, and a suite in which every request is blocked cannot
distinguish a working guardrail from one that blocks everything. With both
fixtures the two assertions constrain each other: the clean question must return
the fixture text unmodified, and the PII question must be blocked. A no-op
guardrail fails the second; a block-everything guardrail fails the first.

The fixtures are JSON files in the repository, so what the guardrail is asked to
catch is visible and editable without touching code.

## The keyed job, separately

A scheduled workflow runs with a real key and a real judge, the agent local and
the API deployed — AWS-SETUP-RUNBOOK §2.4c's Tier 2 shape. It guards on the key
and endpoint being present and exits 0 when they are not, copying
`drift-sim.yml`, so a missing secret or a downed environment skips rather than
fails. It asserts on the response bodies rather than on `make live`'s exit code,
for the reason given above.

It does two things, because one is not enough.

**The two `/ask` requests, with the block assertion conditioned on the output.**
The deterministic suite can demand that the PII question be blocked because it
controls what the model says. Here it does not. A real model told to answer only
from retrieved context may quite correctly decline, or answer without repeating
the number — and then the PII evaluator passes the safe output, `/ask` returns an
unblocked answer, and a flat "must be blocked" assertion fails a job in which
everything worked. So the assertion is conditional and covers both outcomes: if
the provider's output contained the SIN the response must be blocked; if it did
not, the returned answer must not contain it either. The only failure is a leak.

**A keyed `sengol gate` run over the seeded traces, asserted per evaluator.**
Issuing `/ask` requests cannot exercise a judge at all. `agent/main.py:35` wires
only `PIIEvaluator` into the runtime path; `FaithfulnessEvaluator` and
`HallucinationEvaluator` are EvalSuite-only, by the design `controlbook.yaml:28-29`
states outright. So the job also runs the gate with the real judge and no
`JUDGE_LLM_BASE_URL` override.

Running it is not enough. A judge that always passes, or returns output the
parser cannot read, still leaves the failing dataset looking correctly
non-compliant, because the deterministic PII rows fail it on their own — the
gate's verdict would be right for the wrong reason. So the job reads the parsed
per-evaluator outcomes: `FaithfulnessEvaluator` must **fail** the fabricated 8.5%
return and **pass** a clean record from `traces/passing_traces.jsonl`. Those two
together are what supports the claim below; the gate's exit code is not.

**A fresh signed record for each keyed `/ask`, correlated by a run id.** Without
this the job does not prove what it claims. When the real provider answers
safely, both response assertions stay green even with `sengol.instrument()`
removed entirely — `/ask` returns the safe text either way and no block is
expected — and the keyed gate cannot cover the gap, because it evaluates
pre-recorded fixture traces, not these two requests. So the job requires a signed
runtime `AuditRecord` for each keyed call.

Prompt and timestamp are not enough to attribute one. This job points at the
**shared deployed** API, where `drift-sim.yml` and any manual dispatch send the
same two static prompts; an overlapping run could supply a record inside the same
window while this run's instrumentation is broken, which is the exact blind spot
the record is meant to close. So each call carries a run id — a nonce appended to
the question text, which lands verbatim in the signed record's prompt field — and
the assertion requires a record bearing that id. Putting it in the prompt rather
than in `agent_version` is deliberate: the version field means which build
produced the record, and a per-run value there would be a lie in evidence a bank
reads.

**And the clean case needs a criterion a real model can meet.** The deterministic
suite compares the clean answer byte-for-byte against the fixture; a legitimate
model paraphrases, so importing that check here fails the job for a response that
was safe and correctly instrumented. The keyed criterion is instead: a non-empty
answer, free of the SIN, plus its correlated signed record. The PII case is the
conditional one described above.

**Both LLM judges, not one.** `sengol.yaml` runs `FaithfulnessEvaluator` and
`HallucinationEvaluator`, and the claim below is about the judges plural. Naming
only Faithfulness would let Hallucination be unwired, emit unparseable output, or
always pass with both assertions still green. So the keyed gate asserts parsed
outcomes for each of them, on a clean record and on a fabricated one.

The two jobs prove different things and that is why both exist. The fake endpoint
proves the governance logic — interception, evaluation, blocking, signing,
scoring — deterministically, on every pull request. The keyed job proves that a
genuine provider's response still flows through that path, and that the LLM
judges return sane verdicts on real output. That is worth knowing and too
non-deterministic to gate a merge.

## The existing gate, and what pointing it at compose does not fix

`sengol.yml` today runs against a remote server supplied through secrets with
`fail-on-gate-failure: true`. Pointing it at the compose stack removes the
dependency on someone else's environment, which is the runbook's actual
prohibition.

It does **not** by itself make the gate secret-free. `sengol.yaml`'s suite lists
`FaithfulnessEvaluator` and `HallucinationEvaluator`; both raise `RuntimeError`
when no judge is wired (`sengol/evaluators/llm/faithfulness.py:56`,
`llm/hallucination.py:58`), and `controlbook.yaml`'s `judge_by_tier` points every
tier at Anthropic, whose SDK needs `ANTHROPIC_API_KEY`. With
`fail-on-gate-failure: true`, a keyless run fails the merge.

The fake endpoint already in the stack resolves this without a second config:
`JUDGE_LLM_BASE_URL` points the judge client at its own route on that server, and
verdicts arrive as fixtures.

Be exact about what that buys. The per-PR gate proves the suite wiring, the
obligation scoring, the compliance weights and the evidence chain, end to end and
deterministically. It does **not** prove judge quality — a fixture verdict is not
a judgment, and a fixture that always says "pass" would hide a broken judge
prompt. That is what the keyed job is for. The distinction belongs in the
workflow's own comments, not only here, because a green per-PR gate will
otherwise be read as a claim it does not make.

`drift-sim.yml` stays a scheduled post-deploy probe, with one correction. Its
guard tests only whether `SENGOL_API_URL` and `SENGOL_API_TOKEN` are non-empty;
a configured-but-unreachable endpoint gets past it and the job fails on a
connection error — exactly the false alarm the guard exists to prevent. It gains
a reachability probe: one request to the API health endpoint, skip on failure, so
"not deployed" and "deployed and down" both skip rather than fail.

## How this is verified

Each assertion must fail when the thing it covers is broken, not merely pass
when everything works. Concretely, before the suite is considered done:

- Disabling the PII evaluator makes the guardrail test red.
- Removing `sengol.instrument()` from `agent/main.py` makes the guardrail test
  red. This one is not optional: it is the check that the fake endpoint did not
  quietly route around the thing under test, which is the mistake this design
  started out making.
- Swapping the two agent fixtures makes both guardrail assertions red, not one.
- Making the judge route always return `PASS` makes the Console **traces** test
  red, on the named `FaithfulnessEvaluator` score.

  It has to be the traces test, not the review test, and this took two tries to
  get right. Rows 1 and 2 of `traces/failing_traces.jsonl` are PII, caught
  deterministically under a CRITICAL veto (`controlbook.yaml:13-24`), so they
  keep the review queue populated whatever the judge says — a generic "an item
  exists" assertion stays green with judge routing entirely broken. But the LLM
  finding cannot be asserted on the review page either: `README.md:68-72` says a
  **CRITICAL** finding lands in the review queue, and E23-3.1 is HIGH with
  `critical_veto: false` (`controlbook.yaml:30-40`). No LLM evaluator is mapped
  CRITICAL, so the fabricated return never produces a queue entry and a Playwright
  step waiting for one would time out. The LLM result is visible where the README
  says it is — in the trace detail's per-evaluator scores — so that is where it is
  asserted. The review test decides the PII item, which is the item the README's
  own journey decides.
- Pointing `sengol-verify` at a tampered pack makes the evidence test red.
- Seeding nothing makes the Console tests red rather than passing on an empty
  page.

A test that has never been observed failing has not been shown to test
anything.

## Where this sits in the order

First, because it is the only unblocked item and because it is the payload the
later ones need. A QA stack with nothing to run in it proves nothing; this
suite runs locally on every pull request now and points at a deployed
environment later through the same parameterised URL.

Cutting a first release comes next, and it matters more than the earlier draft
of this document allowed. It is not only that the existing gate installs a CLI
that does not exist; `agent/Dockerfile` installs the same unpublished package, so
until a release ships, a prospect who clones this repository cannot build the
stack the README tells them to build. Rebasing the agent image gets this suite
running without waiting, but it is a bridge, not the answer.

The `rc` stack and the upgrade test come after that, and are deferred rather
than descoped. `STATUS.md` records that migrations restart at `0001` and there
is deliberately no upgrade path from 1.x, so the N-1 to N test needs two 2.x
releases to exist. Zero have shipped. Its scope should be re-derived from
`STATUS.md` when the time comes.

## Follow-ups, deliberately not here

Pointing the same suite at a deployed environment post-deploy. The parameterised
URL exists for it; wiring it is a separate change.

A pre-deploy gate in `sengol` that checks this repository out and runs the suite
against an image built from the branch.

The features listed under non-goals.
