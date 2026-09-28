import copy

import pytest

from graph_stock.event_research import (
    EventResearchError, build_earnings, build_management, build_management_claims,
    build_risk, build_valuation, evaluate_claim, validate_advanced_report,
)
from graph_stock.financials import EXTRACTOR_VERSION, FORMULA_VERSION, SCHEMA_VERSION, calculate_metrics
from test_financials import SOURCE, golden_facts
from test_specialists import golden_evidence


def snapshot():
    facts = golden_facts(SOURCE, b"")
    return {"extractor_version": EXTRACTOR_VERSION, "formula_version": FORMULA_VERSION,
            "schema_version": SCHEMA_VERSION, "source": SOURCE, "period": "FY2025",
            "scope": "consolidated", "facts": facts, "metrics": calculate_metrics(facts), "limitations": []}


def test_earnings_periods_consensus_and_golden_valuation_scenarios():
    earnings = build_earnings(snapshot())
    assert [(item["metric"], item["growth_percent"]) for item in earnings["earnings_comparisons"]] == [
        ("revenue", "17.27"), ("profit_after_tax", "33.56")]
    assert earnings["consensus"] == {"status": "unavailable", "reason": "missing-consensus-source", "source_period": None}
    valuation = build_valuation(earnings)
    assert [item["implied_equity_value"] for item in valuation["valuation_scenarios"]] == [
        "106453.60", "133067.00", "159680.40"]
    assert len(valuation["sensitivity"]) == 9
    assert {item["status"] for item in valuation["applicability"] if item["metric"] != "earnings-multiple equity value"} == {"not-applicable"}


def test_management_promise_moves_from_pending_to_partial_met_or_missed():
    claim = {"claim_id": "claim:test", "text": "Reach 20%", "made_period": "FY2025",
             "target_period": "FY2028", "metric": "share", "baseline_value": "5.74",
             "target_value": "20", "unit": "%", "direction": "increase", "evidence_ids": ["e:claim"]}
    assert evaluate_claim(claim, None, "FY2026")["status"] == "pending"
    assert evaluate_claim(claim, {"value": "12", "evidence_id": "e:FY2028"}, "FY2028")["status"] == "partial"
    assert evaluate_claim(claim, {"value": "21", "evidence_id": "e:FY2029"}, "FY2029")["status"] == "met"
    assert evaluate_claim(claim, {"value": "5", "evidence_id": "e:FY2028-low"}, "FY2028")["status"] == "missed"


def test_management_risk_and_unsupported_evidence_propagation():
    source = {**SOURCE, "id": "a" * 64}
    bundle = golden_evidence(source)
    earnings = build_earnings(snapshot())
    valuation = build_valuation(earnings)
    tracker = build_management_claims(bundle)
    management = build_management(bundle, tracker)
    risk = build_risk(bundle, snapshot(), earnings, valuation)
    assert [item["status"] for item in tracker["claim_states"]] == ["pending", "unverifiable"]
    assert management["claims"][0]["evidence_ids"]
    assert {item["id"] for item in risk["risks"]} >= {"risk:cash-conversion", "risk:technology-access"}
    changed_snapshot = copy.deepcopy(snapshot())
    next(item for item in changed_snapshot["metrics"] if item["id"] == "metric:cash-conversion")["value"] = "80.00"
    assert build_risk(bundle, changed_snapshot, earnings, valuation)["report_id"] != risk["report_id"]
    changed = copy.deepcopy(risk)
    changed["risks"][0]["evidence_ids"] = ["evidence:unknown"]
    allowed = {item["id"] for item in bundle["evidence"]} | {
        fact["evidence_id"] for fact in snapshot()["facts"]}
    with pytest.raises(EventResearchError, match="unsupported evidence"):
        validate_advanced_report(changed, allowed)
