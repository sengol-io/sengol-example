_FACTS = [
    {
        "id": "hisa",
        "keywords": ["hisa", "savings", "interest", "rate", "high-interest"],
        "text": (
            "Acme High-Interest Savings Account (HISA): 3.5% annual interest on balances "
            "up to $500,000. No minimum balance. CDIC insured up to $100,000."
        ),
    },
    {
        "id": "mortgage",
        "keywords": ["mortgage", "home", "loan", "fixed", "variable", "amortization"],
        "text": (
            "Acme Mortgage: 5-year fixed rate 5.24%, variable rate prime + 0.45% (currently 7.20%). "
            "Maximum amortization 25 years for insured mortgages."
        ),
    },
    {
        "id": "chequing",
        "keywords": ["chequing", "checking", "account", "debit", "fees", "monthly", "balance"],
        "text": (
            "Acme Everyday Chequing: $4.95/month fee (waived with $1,000 minimum daily balance). "
            "Unlimited debit transactions. Interac e-Transfer included."
        ),
    },
    {
        "id": "gic",
        "keywords": ["gic", "guaranteed", "investment", "term", "certificate", "redeem"],
        "text": (
            "Acme GIC: 1-year at 4.80%, 2-year at 4.60%, 5-year at 4.40%. "
            "Minimum $1,000. CDIC insured. Non-redeemable before maturity."
        ),
    },
    {
        "id": "credit_card",
        "keywords": ["credit", "card", "visa", "rewards", "cash", "back", "infinite"],
        "text": (
            "Acme Visa Infinite: 2% cash back on groceries and gas, 1% on all other purchases. "
            "$120 annual fee. Minimum $60,000 personal income required."
        ),
    },
]

_FALLBACK = (
    "Acme Bank offers savings, chequing, mortgage, GIC, and credit card products. "
    "For specific rates, please visit a branch or call 1-800-ACME-BANK."
)


def get_context(query: str) -> str:
    query_lower = query.lower()
    matched = [
        f["text"]
        for f in _FACTS
        if any(kw in query_lower for kw in f["keywords"])
    ]
    return " ".join(matched) if matched else _FALLBACK
