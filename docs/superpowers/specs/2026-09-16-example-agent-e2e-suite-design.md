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
  instruction a human follows by hand.

The Console is in the same position: the README's journey says "open
`/traces`", "open Governance and decide a review item", and no automation
opens either.

## Goals

Cover the README's 15-minute journey end to end, on every pull request, with
no secrets and no dependency on any deployed environment:

seed → inspect a trace in the Console → decide a review item → export an
evidence pack → verify it offline, plus the PII block and drift detection.

## Non-goals, for this version

Delegation call graphs, quotas, MCP tool-integrity and multi-tenant isolation.
They are real and they are next; including them here trades a working suite for
a longer one.

Anything that asserts absence over a window — coverage gates, Merkle anchoring
cadence, retention intervals, leader election, cross-replica SSE, shared
rate-limit budget. §2.4c is right that these are unreachable from a bounded
run; they need deployed agents on a schedule.

## Where it lives

In this repository. The compose stack, the agent, the trace fixtures and the
Makefile targets are all already here; the suite is mostly assertions around
what exists. Putting it in `sengol` would mean a cross-repo checkout to test an
artifact that lives here.

## Shape

A new workflow stands the stack up itself — `docker compose up -d` for
Postgres, the API on `:8080` and `rag-advisor` on `:3000` — so the suite is
secret-free and can gate pull requests honestly.

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
| Runtime guardrail | agent `/ask`, stub provider | Clean question returns the answer unmodified; PII question is blocked and a signed record carries the PII failure mode |
| Drift | `make check-drift` | At least one signed `DRIFT_THRESHOLD_BREACH` from the 18-row stream |
| Console — traces | Playwright | Mint an admin token, paste it into the sidebar field, open `/traces`, a seeded record is listed and its detail shows a valid signature |
| Console — review | Playwright | The failing traces produced a review item on Governance (`/governance`, the page the README names); decide it; reload; the decision persisted |
| Evidence | `make export-evidence` | `pack.zip` is produced |
| Offline verification | `sengol-verify pack.zip` | Exits 0 |
| Audit | `make verify-audit` | The latest record HMAC-verifies |

## The stub model provider

`agent/main.py` reads `os.environ["ANTHROPIC_API_KEY"]` directly and raises
`KeyError` without it, so the agent cannot serve `/ask` in a secret-free job.
`SENGOL_MODEL_PROVIDER` already switches between Anthropic and OpenAI; this
adds a third value, `stub`, that returns a canned answer. The canned answer is
fixture data in the repository, not a literal in the code, so what the
guardrail is asked to catch is visible and editable.

**This is not a convenience. It is what makes the guardrail test mean
something.** With a real model, `test-pii-fail` asks about "John Smith account
SIN 123456789" and the model decides what comes back. If it declines, or
answers without repeating the number, an assertion of "the response must not
contain the SIN" passes while proving nothing — a green test cannot be
distinguished from a broken guardrail. The thing under test operates on model
output, and with a real provider the output is not controlled.

A stub that always emits a known SIN makes the assertion exact: given output
containing PII, the response is blocked and a signed record carries the failure
mode.

It bypasses no real code. The agent calls `client.messages.create(...)` and
reads `resp.content[0].text` — non-streaming, a plain string. A stub returning
a string enters the identical downstream path.

**The stub is self-proving.** Both directions are asserted: a clean question
returns the stub's answer unmodified, and the PII question is blocked. Those
cannot both pass if the guardrail is a no-op — one would leak or the other
would over-block. A single-direction test cannot make that claim.

## The keyed job, separately

A scheduled workflow runs `make live` with a real key, the agent local and the
API deployed — AWS-SETUP-RUNBOOK §2.4c's Tier 2 shape. It guards on the key and
endpoint being present and exits 0 when they are not, copying `drift-sim.yml`,
so a missing secret or a downed environment skips rather than fails.

The two jobs prove different things and that is why both exist. The stub proves
the governance logic, deterministically, on every PR. The keyed job proves a
genuine provider's response still flows through that path, SDK and all — which
is worth knowing and too non-deterministic to gate a merge.

## Fixing the existing gate

`sengol.yml` points at the compose stack instead of a remote server, which
makes it secret-free and removes the per-PR dependency the runbook forbids.
`drift-sim.yml` is unchanged; it is a scheduled post-deploy probe and already
guards correctly.

## How this is verified

Each assertion must fail when the thing it covers is broken, not merely pass
when everything works. Concretely, before the suite is considered done:

- Disabling the PII evaluator makes the guardrail test red.
- Pointing `sengol-verify` at a tampered pack makes the evidence test red.
- Seeding nothing makes the Console tests red rather than passing on an empty
  page.

A test that has never been observed failing has not been shown to test
anything.

## Follow-ups, deliberately not here

Pointing the same suite at a deployed environment post-deploy. The parameterised
URL exists for it; wiring it is a separate change.

A pre-deploy gate in `sengol` that checks this repository out and runs the suite
against an image built from the branch.

The features listed under non-goals.
