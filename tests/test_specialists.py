import copy

import pytest

from graph_stock.specialists import (
    EVIDENCE_VERSION, SpecialistError, build_business_quality, build_competitor,
    build_industry, build_moat, render_specialist_note, validate_report,
)


def golden_evidence(source, content=b""):
    prefix = f"evidence:{source['id'][:12]}"
    def item(suffix, page):
        return {"id": f"{prefix}:{suffix}", "source_id": "S1", "pdf_page": page,
                "section": "fixture", "statement": suffix,
                "evidence_type": "fact_source_reported", "confidence": "high"}
    return {
        "version": EVIDENCE_VERSION, "symbol": source["symbol"], "period": "FY2025",
        "period_end": "2025-03-31",
        "source_index": [{"source_id": "S1", "source_name": source["title"],
            "source_type": "primary filing", "provider_or_owner": source["symbol"],
            "as_of_date": "2025-03-31", "retrieved_at": source["retrieved_at"],
            "period_covered": "FY2025", "source_location": "fixture pages",
            "freshness_status": "acceptable", "notes": "bounded fixture"}],
        "evidence": [item(name, page) for name, page in (
            ("p46:business-model", 46), ("p48:business-mix", 48),
            ("p48:products-services", 48), ("p48:portfolio", 48),
            ("p45:industry-driver", 45), ("p50:order-book", 50),
            ("p50:research", 50), ("p45:market-position", 45),
            ("p90:technology-risk", 90), ("peer-hal-missing", None),
            ("peer-bdl-missing", None), ("p92:non-defence-target", 92),
            ("p92:risk-governance", 92),
        )],
        "peer_coverage": [{"symbol": source["symbol"], "status": "available", "source_period": "FY2025"},
                          {"symbol": "HAL", "status": "missing", "source_period": None},
                          {"symbol": "BDL", "status": "missing", "source_period": None}],
    }


def source():
    return {"id": "a" * 64, "symbol": "BEL", "title": "BEL annual report",
            "retrieved_at": "2025-08-05T15:08:33+00:00"}


def test_golden_company_and_peer_set_builds_grounded_reports():
    bundle = golden_evidence(source())
    reports = [build_business_quality(bundle), build_industry(bundle), build_competitor(bundle)]
    moat = build_moat(bundle, reports)
    assert [report["rating"] for report in reports] == ["supported", "mixed", "insufficient"]
    assert "HAL and BDL" in reports[2]["summary"]
    assert moat["rating"] == "provisional"
    assert set(moat["input_report_ids"]) == {report["report_id"] for report in reports}
    assert "S1 p.48" in render_specialist_note(reports[0], bundle)


def test_unknown_evidence_and_missing_moat_dependency_are_rejected():
    bundle = golden_evidence(source())
    report = build_business_quality(bundle)
    changed = copy.deepcopy(report)
    changed["claims"][0]["evidence_ids"] = ["evidence:not-allowed"]
    with pytest.raises(SpecialistError, match="unsupported evidence"):
        validate_report(changed, {item["id"] for item in bundle["evidence"]})
    with pytest.raises(SpecialistError, match="requires business"):
        build_moat(bundle, [build_business_quality(bundle), build_industry(bundle)])
