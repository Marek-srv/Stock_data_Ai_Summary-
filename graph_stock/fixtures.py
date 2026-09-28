"""Tiny, explicitly synthetic catalogue. Never used as a live provider."""

from decimal import Decimal

CATALOGUE = (
    {"security_id": "NSE:HAL", "symbol": "HAL", "name": "Hindustan Aeronautics Limited", "exchange": "NSE"},
    {"security_id": "NSE:BEL", "symbol": "BEL", "name": "Bharat Electronics Limited", "exchange": "NSE"},
    {"security_id": "NSE:BHEL", "symbol": "BHEL", "name": "Bharat Heavy Electricals Limited", "exchange": "NSE"},
)


def search(query: str):
    text = " ".join(query.upper().split())
    exact = [c for c in CATALOGUE if text in (c["symbol"], c["name"].upper(), c["security_id"])]
    matches = exact or [c for c in CATALOGUE if text and text in (c["symbol"] + " " + c["name"]).upper()]
    return {"status": "resolved" if len(matches) == 1 else "ambiguous" if matches else "not-found",
            "mode": "fixture", "candidates": matches}


def fixture_snapshot(security: dict, run_id: str, timestamp: str):
    # Fixed quantities support independently hand-checked golden expectations.
    previous, current, operating_profit = Decimal("1000"), Decimal("1200"), Decimal("180")
    growth = (current - previous) / previous * 100
    margin = operating_profit / current * 100
    evidence_id = f"fixture:{security['symbol']}:financials:v1"
    evidence = {"id": evidence_id, "kind": "synthetic-fixture", "version": "1",
                "title": f"{security['symbol']} · synthetic financial sample",
                "period": "Demo period A → Demo period B (not real fiscal periods)",
                "facts": {"revenue_A": "1000", "revenue_B": "1200", "operating_profit_B": "180", "unit": "INR crore"},
                "locator": "Bundled fixture / facts", "collected_at": timestamp}
    return {
        "schema_version": "fixture-snapshot/v1", "mode": "fixture", "run_id": run_id,
        "security": security, "saved_at": timestamp,
        "notice": "SYNTHETIC TEST DATA — not live company research or investment advice.",
        "period": evidence["period"],
        "summary": "This synthetic sample demonstrates how a research snapshot is calculated, saved and retrieved. It is not an assessment of this company.",
        "metrics": [
            {"id": "revenue", "label": "Revenue", "value": str(current), "unit": "INR crore", "period": "Demo period B", "evidence_id": evidence_id, "formula": "fixture fact: revenue_B"},
            {"id": "growth", "label": "Revenue growth", "value": str(growth), "unit": "%", "period": "A → B", "evidence_id": evidence_id, "formula": "(revenue_B - revenue_A) / revenue_A × 100"},
            {"id": "margin", "label": "Operating margin", "value": str(margin), "unit": "%", "period": "Demo period B", "evidence_id": evidence_id, "formula": "operating_profit_B / revenue_B × 100"},
        ],
        "evidence": [evidence],
        "missing": ["Real filings and financial history", "Business, valuation and risk analysis", "Validated backtests and paper signals"],
        "research_score": None, "confidence": None,
    }
