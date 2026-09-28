import copy

import pytest

from graph_stock.debate import (
    DebateError, build_case, build_judge, build_thesis, evidence_ids,
    score_research, validate_case, validate_scores,
)
from graph_stock.event_research import (
    build_earnings, build_management, build_management_claims, build_risk, build_valuation,
)
from graph_stock.financials import EXTRACTOR_VERSION, FORMULA_VERSION, SCHEMA_VERSION, calculate_metrics
from graph_stock.news import normalize_records, representative_bel_records
from graph_stock.ownership import bel_disclosures, compare_periods
from graph_stock.specialists import build_business_quality, build_competitor, build_industry, build_moat
from test_financials import SOURCE, golden_facts
from test_specialists import golden_evidence


def inputs(include_ownership=True):
    source = {**SOURCE, "title": "BEL Integrated Annual Report 2024-25",
              "origin": "https://example.test/report.pdf", "public_available_at": "2025-08-05T20:38:33+05:30",
              "retrieved_at": "2025-08-06T00:00:00+00:00"}
    facts = golden_facts(source, b"")
    financial = {"extractor_version": EXTRACTOR_VERSION, "formula_version": FORMULA_VERSION,
                 "schema_version": SCHEMA_VERSION, "source": source, "period": "FY2025",
                 "scope": "consolidated", "facts": facts, "metrics": calculate_metrics(facts), "limitations": []}
    bundle = golden_evidence(source)
    business, industry, competitor = build_business_quality(bundle), build_industry(bundle), build_competitor(bundle)
    moat = build_moat(bundle, [business, industry, competitor])
    earnings = build_earnings(financial)
    claims = build_management_claims(bundle)
    valuation = build_valuation(earnings)
    management = build_management(bundle, claims)
    risk = build_risk(bundle, financial, earnings, valuation)
    news = normalize_records("BEL", representative_bel_records("BEL"))
    news[0].update({"version": 1, "version_id": news[0]["event_id"] + ":v1", "supersedes": None})
    prior, current = bel_disclosures(source)
    ownership = {"id": "ownership:test", "sources": [
        {key: period[key] for key in ("source_id", "period", "coverage")} for period in (prior, current)],
        "comparison": compare_periods(prior, current)}
    return {"financial": financial,
            "specialists": {"business_quality": business, "industry": industry, "competitor": competitor, "moat": moat},
            "advanced": {"earnings": earnings, "management_claims": claims, "valuation": valuation,
                         "management": management, "risk": risk},
            "ownership": ownership if include_ownership else None,
            "news": {"events": news}}


def test_bull_bear_are_independent_and_judge_receives_both_afterward():
    data = inputs()
    bull = build_case("bull", data)
    bear = build_case("bear", data)
    assert bull["input_manifest_hash"] == bear["input_manifest_hash"]
    assert bull["input_report_ids"] == bear["input_report_ids"]
    assert "input_case_ids" not in bull and "input_case_ids" not in bear
    judge = build_judge(bull, bear, data)
    assert judge["input_case_ids"] == [bull["case_id"], bear["case_id"]]
    assert set(judge["accepted_claim_ids"]) == {item["claim_id"] for item in bull["claims"] + bear["claims"]}
    thesis = build_thesis(judge, bull, bear)
    assert thesis["input_judge_id"] == judge["judge_id"]


def test_equal_weight_score_expected_values_and_missing_category():
    data = inputs()
    scores = validate_scores(score_research(data), evidence_ids(data))
    values = {item["name"]: item["score"] for item in scores["categories"]}
    assert values == {"business_quality": 75, "growth": 80, "financial_quality": 35,
                      "moat": 50, "management": 50, "valuation": None,
                      "risk": 30, "institutional_flow": 40}
    assert scores["overall_score"] == "51.43"
    assert scores["provisional_denominator_percent"] == "87.50"
    assert scores["evidence_completeness_percent"] == "59.09"
    assert scores["research_confidence"] == "moderate"
    missing = inputs(False)
    missing_scores = score_research(missing)
    institutional = next(item for item in missing_scores["categories"] if item["name"] == "institutional_flow")
    assert institutional["status"] == "unscored" and institutional["score"] is None
    assert missing_scores["overall_score"] == "53.33"


def test_unsupported_citations_are_rejected():
    data = inputs()
    bull = build_case("bull", data)
    changed = copy.deepcopy(bull)
    changed["claims"][0]["evidence_ids"] = ["evidence:unsupported"]
    with pytest.raises(DebateError, match="unsupported evidence"):
        validate_case(changed, evidence_ids(data))
    scores = score_research(data)
    scores["categories"][0]["evidence_ids"] = ["evidence:unsupported"]
    with pytest.raises(DebateError, match="unsupported evidence"):
        validate_scores(scores, evidence_ids(data))
