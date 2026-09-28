"""Evidence-gated baseline business, industry, competitor and moat research."""

from __future__ import annotations

import hashlib
import io
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader


EVIDENCE_VERSION = "bel-qualitative-evidence/v4"
SPECIALIST_SCHEMA_VERSION = "specialist-report/v2"
SPECIALIST_POLICY_VERSION = "evidence-gated-specialists/v1"
SUPPORTED_BEL_SHA256 = "db47a73b477737b5c5241d6c62bfba08446a734fb8b59972b6a6577e0fe7867d"


class SpecialistError(Exception):
    pass


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str = Field(min_length=1)
    evidence_type: Literal[
        "fact_source_reported", "issuer_management_claim", "analyst_interpretation",
        "missing_required_source",
    ]
    confidence: Literal["high", "medium", "low"]
    evidence_ids: list[str] = Field(min_length=1)


class SpecialistReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str
    schema_version: Literal["specialist-report/v2"]
    policy_version: Literal["evidence-gated-specialists/v1"]
    evidence_version: str
    kind: Literal["business_quality", "industry", "competitor", "moat"]
    symbol: str
    period: str
    period_end: str
    summary: str
    rating: Literal["supported", "mixed", "provisional", "insufficient"]
    claims: list[Claim]
    source_periods: list[str]
    limitations: list[str]
    input_report_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def moat_declares_inputs(self):
        if self.kind == "moat" and len(self.input_report_ids) != 3:
            raise ValueError("Moat reports require three declared specialist inputs")
        if self.kind != "moat" and self.input_report_ids:
            raise ValueError("Only moat reports may declare report inputs")
        return self


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _item(item_id, page, section, statement, evidence_type="fact_source_reported", confidence="high"):
    return {
        "id": item_id, "source_id": "S1", "pdf_page": page, "section": section,
        "statement": statement, "evidence_type": evidence_type, "confidence": confidence,
    }


def extract_bel_evidence(source: dict, content: bytes) -> dict:
    """Extract a measured qualitative evidence set from the supported BEL report."""
    if source.get("symbol") != "BEL" or source.get("sha256") != SUPPORTED_BEL_SHA256:
        raise SpecialistError("Qualitative extraction currently supports the measured BEL FY2025 report only.")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        pages = {page: " ".join((reader.pages[page - 1].extract_text() or "").split()) for page in (45, 46, 48, 50, 90, 92)}
    except Exception:
        raise SpecialistError("The saved PDF could not be read for qualitative evidence.") from None
    anchors = {
        45: ("self-reliance", "market leader in domestic defence electronics"),
        46: ("primarily engaged in developing electronics technology solutions",),
        48: ("TURNOVER BREAK-UP", "Radars", "NON-DEFENCE SEGMENT"),
        50: ("total investment in R&D", "order book continued to be healthy"),
        90: ("Rapid changes in technologies", "single source for technologies"),
        92: ("about 20% of company's turnover", "5.74% of turnover", "Enterprise Risk Management"),
    }
    if any(any(anchor.lower() not in pages[page].lower() for anchor in required) for page, required in anchors.items()):
        raise SpecialistError("The supported report pages no longer match the measured qualitative layout.")
    prefix = f"evidence:{source['id'][:12]}"
    evidence = [
        _item(f"{prefix}:p46:business-model", 46, "About Bharat Electronics Limited",
              "BEL says it primarily develops electronics technology solutions for defence and civilian segments."),
        _item(f"{prefix}:p48:business-mix", 48, "Our Core Businesses",
              "FY2025 turnover mix is disclosed as defence 89.75%, non-defence 5.75%, exports 3.87% and others 0.63%."),
        _item(f"{prefix}:p48:products-services", 48, "Our Core Businesses",
              "FY2025 turnover by source is disclosed as sale of products 90.47% and services 9.53%."),
        _item(f"{prefix}:p48:portfolio", 48, "Our Core Businesses",
              "The disclosed portfolio spans radars, missile systems and C4I, defence communications, electronic warfare, naval systems, electro-optics, tank electronics, seekers and precision weapons."),
        _item(f"{prefix}:p45:industry-driver", 45, "Resilient Growth",
              "BEL attributes defence-sector growth to self-reliance, military modernisation, budgets, policy support and indigenisation.",
              "issuer_management_claim", "medium"),
        _item(f"{prefix}:p50:order-book", 50, "Message from the CMD",
              "BEL reports an order book of INR 71,650 crore as of 1 April 2025 and expects good order inflows over the next two to three years.",
              "issuer_management_claim", "medium"),
        _item(f"{prefix}:p50:research", 50, "Message from the CMD",
              "BEL reports FY2025 R&D investment at 6.4% of turnover and says 74% of turnover came from indigenous products."),
        _item(f"{prefix}:p45:market-position", 45, "Resilient Growth",
              "BEL describes itself as the market leader in domestic defence electronics.",
              "issuer_management_claim", "medium"),
        _item(f"{prefix}:p90:technology-risk", 90, "Management Discussion and Analysis",
              "BEL identifies rapid technology change, sourcing of critical technologies, private-sector policy and proprietary single-source lock-in as challenges."),
        _item(f"{prefix}:p92:non-defence-target", 92, "Diversification / Expansion Plans",
              "BEL reports non-defence turnover at about 5.74% and aims for about 20% in coming years.",
              "issuer_management_claim", "medium"),
        _item(f"{prefix}:p92:risk-governance", 92, "Risk Management",
              "BEL says its enterprise risk framework spans business units, uses Board-level oversight and reports significant risks and mitigation status to the Board."),
        _item(f"{prefix}:peer-hal-missing", None, "Source inventory",
              "No HAL primary filing is included in the bounded source set.", "missing_required_source", "high"),
        _item(f"{prefix}:peer-bdl-missing", None, "Source inventory",
              "No BDL primary filing is included in the bounded source set.", "missing_required_source", "high"),
    ]
    return {
        "version": EVIDENCE_VERSION,
        "symbol": "BEL", "period": "FY2025", "period_end": "2025-03-31",
        "source_index": [{
            "source_id": "S1", "source_name": source["title"], "source_type": "primary filing",
            "provider_or_owner": "Bharat Electronics Limited", "as_of_date": source.get("document_date"),
            "retrieved_at": source["retrieved_at"], "period_covered": "FY2025",
            "source_location": "PDF pages 45, 46, 48, 50, 90 and 92", "freshness_status": "stale",
            "notes": "Historical issuer-only sample; management positioning is not independently verified.",
        }],
        "evidence": evidence,
        "peer_coverage": [
            {"symbol": "BEL", "status": "available", "source_period": "FY2025"},
            {"symbol": "HAL", "status": "missing", "source_period": None},
            {"symbol": "BDL", "status": "missing", "source_period": None},
        ],
    }


def validate_evidence_bundle(bundle: dict) -> dict:
    required = {"version", "symbol", "period", "period_end", "source_index", "evidence", "peer_coverage"}
    if set(bundle) != required or not bundle["source_index"] or not bundle["evidence"]:
        raise SpecialistError("Qualitative evidence bundle is incomplete or has unknown fields.")
    ids = [item.get("id") for item in bundle["evidence"]]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise SpecialistError("Qualitative evidence IDs must be present and unique.")
    return bundle


def _report(kind, bundle, summary, rating, claim_specs, limitations, inputs=None):
    claims = [Claim.model_validate({"id": f"{kind}:{index}", **spec}).model_dump() for index, spec in enumerate(claim_specs, 1)]
    payload = {
        "schema_version": SPECIALIST_SCHEMA_VERSION, "policy_version": SPECIALIST_POLICY_VERSION,
        "evidence_version": bundle["version"],
        "kind": kind, "symbol": bundle["symbol"], "period": bundle["period"],
        "period_end": bundle["period_end"], "summary": summary, "rating": rating,
        "claims": claims, "source_periods": [f"S1 {bundle['period']}"],
        "limitations": limitations, "input_report_ids": inputs or [],
    }
    payload["report_id"] = f"report:{kind}:{_hash(payload)[:20]}"
    return SpecialistReport.model_validate(payload).model_dump()


def validate_report(report: dict, evidence_ids: set[str]) -> dict:
    try:
        validated = SpecialistReport.model_validate(report)
    except Exception as error:
        raise SpecialistError("Specialist report does not match the versioned schema.") from error
    cited = {evidence_id for claim in validated.claims for evidence_id in claim.evidence_ids}
    if not cited.issubset(evidence_ids):
        raise SpecialistError("Specialist report contains an unsupported evidence reference.")
    return validated.model_dump()


def _ids(bundle):
    return {item["id"].split(":")[-1]: item["id"] for item in bundle["evidence"]}


def build_business_quality(bundle: dict) -> dict:
    bundle, ids = validate_evidence_bundle(bundle), _ids(bundle)
    return _report("business_quality", bundle,
        "BEL is a product-led defence-electronics business with broad programmes, concentrated defence exposure and a smaller civilian operation.",
        "supported", [
            {"text": "The business develops electronics solutions for defence and civilian customers.", "evidence_type": "fact_source_reported", "confidence": "high", "evidence_ids": [ids["business-model"]]},
            {"text": "Defence represented 89.75% of FY2025 turnover; the remaining disclosed mix was non-defence, exports and other.", "evidence_type": "fact_source_reported", "confidence": "high", "evidence_ids": [ids["business-mix"]]},
            {"text": "Product sales represented 90.47% of FY2025 turnover and services 9.53%.", "evidence_type": "fact_source_reported", "confidence": "high", "evidence_ids": [ids["products-services"]]},
            {"text": "A broad electronics portfolio and a large reported order book are the main disclosed operating drivers.", "evidence_type": "analyst_interpretation", "confidence": "medium", "evidence_ids": [ids["portfolio"], ids["order-book"]]},
        ], ["Segment profitability and customer-level concentration are not disclosed in the bounded evidence set."])


def build_industry(bundle: dict) -> dict:
    bundle, ids = validate_evidence_bundle(bundle), _ids(bundle)
    return _report("industry", bundle,
        "The issuer links demand to Indian defence modernisation and indigenisation, while technology access and competitive intensity remain material constraints.",
        "mixed", [
            {"text": "Management identifies military modernisation, policy support and indigenisation as sector demand drivers.", "evidence_type": "issuer_management_claim", "confidence": "medium", "evidence_ids": [ids["industry-driver"]]},
            {"text": "Technology change, access to critical technologies and private-sector policy are disclosed industry-facing challenges.", "evidence_type": "fact_source_reported", "confidence": "high", "evidence_ids": [ids["technology-risk"]]},
            {"text": "The reported order book supports demand visibility for BEL, but it does not establish industry growth on its own.", "evidence_type": "analyst_interpretation", "confidence": "medium", "evidence_ids": [ids["order-book"]]},
        ], ["Industry size, market growth and independent government procurement data are absent.", "Sector outlook is issuer-authored and may be optimistic."])


def build_competitor(bundle: dict) -> dict:
    bundle, ids = validate_evidence_bundle(bundle), _ids(bundle)
    missing = [peer["symbol"] for peer in bundle["peer_coverage"] if peer["status"] == "missing"]
    missing_text = " and ".join(missing) if len(missing) <= 2 else ", ".join(missing[:-1]) + f", and {missing[-1]}"
    return _report("competitor", bundle,
        f"BEL's market-position claim is recorded, but comparative ranking is withheld because primary coverage is missing for {missing_text}.",
        "insufficient", [
            {"text": "BEL describes itself as the domestic defence-electronics market leader; this is an issuer claim, not an independently verified rank.", "evidence_type": "issuer_management_claim", "confidence": "medium", "evidence_ids": [ids["market-position"]]},
            {"text": f"Primary peer evidence is missing for {missing_text}, so no peer ranking is supported.", "evidence_type": "missing_required_source", "confidence": "high", "evidence_ids": [ids["peer-hal-missing"], ids["peer-bdl-missing"]]},
        ], ["HAL and BDL primary filings are not present in this run.", "Platform manufacturers and defence-electronics suppliers may have different product, customer and accounting mixes."])


def build_moat(bundle: dict, reports: list[dict]) -> dict:
    bundle, ids = validate_evidence_bundle(bundle), _ids(bundle)
    expected = {"business_quality", "industry", "competitor"}
    if {report.get("kind") for report in reports} != expected:
        raise SpecialistError("Moat assessment requires business, industry and competitor reports.")
    evidence_ids = {item["id"] for item in bundle["evidence"]}
    checked = [validate_report(report, evidence_ids) for report in reports]
    return _report("moat", bundle,
        "Product breadth, R&D intensity and indigenous capabilities are possible advantages, but the moat remains provisional without peer evidence and customer-level economics.",
        "provisional", [
            {"text": "Portfolio breadth and R&D investment provide evidence of technical capability across several defence-electronics categories.", "evidence_type": "analyst_interpretation", "confidence": "medium", "evidence_ids": [ids["portfolio"], ids["research"]]},
            {"text": "Policy support and indigenous turnover may reinforce BEL's position, while technology access and single-source risks can weaken durability.", "evidence_type": "analyst_interpretation", "confidence": "medium", "evidence_ids": [ids["industry-driver"], ids["research"], ids["technology-risk"]]},
            {"text": "A comparative moat conclusion is unsupported until peer primary sources are available.", "evidence_type": "missing_required_source", "confidence": "high", "evidence_ids": [ids["peer-hal-missing"], ids["peer-bdl-missing"]]},
        ], ["No peer filings, customer retention data, programme-level margins or switching-cost evidence are available."],
        [report["report_id"] for report in sorted(checked, key=lambda item: item["kind"])])


def render_specialist_note(report: dict, bundle: dict) -> str:
    lines = [f"# {report['symbol']} — {report['kind'].replace('_', ' ').title()}", "",
             f"**Period:** {report['period']}  ", f"**Assessment:** {report['rating']}  ",
             f"**Schema:** `{report['schema_version']}`  ", f"**Report ID:** `{report['report_id']}`", "",
             f"**Evidence version:** `{report['evidence_version']}`", "",
             report["summary"], "", "## Evidence-backed findings", ""]
    evidence = {item["id"]: item for item in bundle["evidence"]}
    for claim in report["claims"]:
        locations = ", ".join(
            f"S1 p.{evidence[item]['pdf_page']}" if evidence[item]["pdf_page"] else evidence[item]["section"]
            for item in claim["evidence_ids"]
        )
        lines.append(f"- {claim['text']} ({locations}; {claim['evidence_type']}; {claim['confidence']})")
    lines.extend(["", "## Limits", ""] + [f"- {item}" for item in report["limitations"]])
    lines.extend(["", "## Source index", ""])
    for source in bundle["source_index"]:
        lines.append(f"- **{source['source_id']}** — {source['source_name']}; {source['period_covered']}; {source['source_location']}; freshness: {source['freshness_status']}.")
    if report["input_report_ids"]:
        lines.extend(["", "## Declared inputs", ""] + [f"- `{item}`" for item in report["input_report_ids"]])
    return "\n".join(lines) + "\n"


def condensed(report: dict, note: dict) -> dict:
    return {"report_id": report["report_id"], "kind": report["kind"], "rating": report["rating"],
            "summary": report["summary"], "source_periods": report["source_periods"],
            "limitations": report["limitations"], "note": note}
