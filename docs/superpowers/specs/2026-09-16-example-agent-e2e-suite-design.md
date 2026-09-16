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

**The suite asserts on responses itself rather than shelling out to `make live`.**
Those targets stay as human-facing demos; the suite issues the same two requests
and asserts on the bodies. The keyed job below gets the same assertions, for the
same reason.

**The `sengol` CLI comes from the image, not from PyPI.** `pyproject.toml`
declares the `sengol` console script and the image installs the package, so
`docker compose exec sengol-api sengol gate ...` works. This matters because
the package is not published — `https://pypi.org/pypi/sengol/json` returns 404
— which is what makes the existing `sengol.yml` gate red on every pull
request. `datasets` is imported lazily, inside a function, for HuggingFace
loading only, so the extras the image already installs cover the local JSONL
fixtures this suite uses.

The suite is a Python test module that drives the same Makefile targets a human
follows, plus a Playwright layer over the Console. It reads `SENGOL_API_URL`
and `SENGOL_AGENT_URL` from the environment rather than hardcoding localhost.
That single decision is what lets the identical suite later run against a
deployed environment without a second implementation.

## What it asserts

| Step | Driven by | Assertion |
|---|---|---|
| Stack is up | compose + healthcheck | API and agent both answer before anything else runs |
| Seed | `make demo` | Signed `AuditRecord`s land for both trace sets |
| Runtime guardrail | agent `/ask`, fake model endpoint | Clean question returns the fixture answer byte-for-byte; PII question returns the block message, never the SIN, and a signed record carries the PII failure mode |
| Drift | `make check-drift` | At least one signed `DRIFT_THRESHOLD_BREACH` from the 18-row stream |
| Console — traces | Playwright | Mint an admin token, paste it into the sidebar field, open `/traces`, a seeded record is listed and its detail shows a valid signature |
| Console — review | Playwright | The failing traces produced a review item on Governance (`/governance`, the page the README names); decide it; reload; the decision persisted |
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
ANTHROPIC_BASE_URL=http://model-stub:8081
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

**Two distinct fixtures is the point.** A stub that always emitted a SIN would
block the clean case too, and a suite in which every request is blocked cannot
distinguish a working guardrail from one that blocks everything. With both
fixtures the two assertions constrain each other: the clean question must return
the fixture text unmodified, and the PII question must be blocked. A no-op
guardrail fails the second; a block-everything guardrail fails the first.

The fixtures are JSON files in the repository, so what the guardrail is asked to
catch is visible and editable without touching code.

## The keyed job, separately

A scheduled workflow runs the same two requests with a real key and a real
judge, the agent local and the API deployed — AWS-SETUP-RUNBOOK §2.4c's Tier 2
shape. It guards on the key and endpoint being present and exits 0 when they are
not, copying `drift-sim.yml`, so a missing secret or a downed environment skips
rather than fails. It asserts on the response bodies rather than on `make live`'s
exit code, for the reason given above.

The two jobs prove different things and that is why both exist. The fake
endpoint proves the governance logic — interception, evaluation, blocking,
signing, scoring — deterministically, on every pull request. The keyed job
proves that a genuine provider's response still flows through that path, and
that the LLM judges return sane verdicts on real output. That is worth knowing
and too non-deterministic to gate a merge.

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
the judge client is an Anthropic client too, so the same `ANTHROPIC_BASE_URL`
covers it, and judge verdicts arrive as fixtures.

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
- Swapping the two fixtures makes both guardrail assertions red, not one.
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

Cutting a first release comes next. It unblocks the existing gate (no
published CLI today) and is a precondition for anything that installs released
artifacts.

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
