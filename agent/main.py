import os

import anthropic
import sengol
from fastapi import FastAPI
from pydantic import BaseModel
from sengol import BlockedError
from sengol.evaluators.deterministic.pii import PIIEvaluator

from knowledge_base import get_context

app = FastAPI(title="RAG Financial Advisor")

_AGENT_ID = "rag-advisor-001"
_AGENT_VERSION = "0.1.0"
_TENANT_ID = os.environ.get("SENGOL_TENANT_ID", "acme-bank-ca")
_MODEL_PROVIDER = os.environ.get("SENGOL_MODEL_PROVIDER", "anthropic")

# sengol.configure() + sengol.instrument() (ADR-0084) monkey-patch the
# Anthropic and OpenAI clients at startup. Every client.messages.create() /
# client.chat.completions.create() call is intercepted automatically — no
# per-call wiring in the request handlers.
#
# The audit sink is resolved from SENGOL_API_URL / SENGOL_API_TOKEN by the
# instrument layer itself; records are WAL-spooled locally and replayed on
# reconnect for durability.
#
# Only deterministic evaluators belong in the runtime intercept path.
# LLM judges (FaithfulnessEvaluator, HallucinationEvaluator) run in CI via EvalSuite.
sengol.configure(
    agent_id=_AGENT_ID,
    agent_version=_AGENT_VERSION,
    tenant_id=_TENANT_ID,
    policies=["OSFI_E23"],
    pre_evaluators=[],
    post_evaluators=[PIIEvaluator()],
    block_message="I cannot provide this information at this time.",
)
sengol.instrument()


async def _generate_answer(question: str, context: str) -> str:
    system = (
        "You are a Canadian bank financial advisor. "
        "Answer using only the provided context. "
        "Do not invent products, rates, or terms not in the context.\n\n"
        f"Context:\n{context}"
    )
    if _MODEL_PROVIDER == "openai":
        import openai
        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=512,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        return resp.choices[0].message.content
    else:
        client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        return resp.content[0].text


class AskRequest(BaseModel):
    question: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": _AGENT_VERSION}


@app.post("/ask")
async def ask(req: AskRequest) -> dict:
    context = get_context(req.question)
    try:
        answer = await _generate_answer(req.question, context)
    except BlockedError as e:
        # The AuditRecord is WAL-enqueued before BlockedError is raised.
        return {"blocked": True, "reason": e.failure_mode}
    return {"answer": answer}
