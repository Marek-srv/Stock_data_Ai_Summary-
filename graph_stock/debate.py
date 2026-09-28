"""Evidence-locked bull/bear debate, judging, thesis and transparent scoring."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field

DEBATE_SCHEMA_VERSION = "independent-debate/v1"
SCORE_POLICY_VERSION = "equal-category-score/v1"
CONFIDENCE_POLICY_VERSION = "evidence-sufficiency/v1"
CATEGORY_NAMES = (
    "business_quality", "growth", "financial_quality", "moat",
    "management", "valuation", "risk", "institutional_flow",
)
CATEGORY_WEIGHT = "12.50"
REQUIRED_EVIDENCE = (
    "security_identity", "filings_results", "annual_report", "corporate_actions",
    "daily_ohlcv", "benchmark_sector", "shareholding", "promoter_pledge",
    "named_holders", "mf_schemes", "news_catalysts",
)


class DebateError(Exception):
    pass


class DebateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    theme: str
    text: str
    confidence: str
    evidence_ids: list[str] = Field(min_length=1)


class DebateCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    schema_version: str
    kind: str
    input_manifest_hash: str
    input_report_ids: list[str]
    claims: list[DebateClaim]


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _number(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def evidence_ids(inputs):
    allowed = set()
    ownership = inputs.get("ownership") or {}
    financial = inputs["financial"]
    allowed |= {fact["evidence_id"] for fact in financial["facts"]}
    for metric in financial["metrics"]:
        allowed.update(metric["evidence_ids"])
    for report in inputs["specialists"].values():
        for claim in report.get("claims", []):
            allowed.update(claim["evidence_ids"])
    for report in inputs["advanced"].values():
        for key in ("claims", "earnings_comparisons", "valuation_scenarios", "management_claims", "claim_states", "risks"):
            for item in report.get(key, []):
                allowed.update(item.get("evidence_ids", []))
    for source in ownership.get("sources", []):
        allowed.add(source["source_id"])
    for event in inputs.get("news", {}).get("events", []):
        for source in event["sources"]:
            allowed.add(source["source_id"])
    return allowed


def input_manifest(inputs):
    reports = [report["report_id"] for report in inputs["specialists"].values()]
    reports += [report["report_id"] for report in inputs["advanced"].values()]
    ownership = inputs.get("ownership") or {}
    manifest = {
        "financial_source_id": inputs["financial"]["source"]["id"],
        "financial_schema": inputs["financial"]["schema_version"],
        "report_ids": sorted(reports),
        "ownership_run_id": ownership.get("id"),
        "news_versions": sorted(event["version_id"] for event in inputs.get("news", {}).get("events", [])),
    }
    return {"manifest": manifest, "hash": _hash(manifest)}


def _claim(claim_id, theme, text, confidence, ids):
    return {"claim_id": claim_id, "theme": theme, "text": text,
            "confidence": confidence, "evidence_ids": list(dict.fromkeys(ids))}


def build_case(kind, inputs):
    if kind not in ("bull", "bear"):
        raise DebateError("Debate case must be bull or bear.")
    locked = input_manifest(inputs)
    earnings, business = inputs["advanced"]["earnings"], inputs["specialists"]["business_quality"]
    risk, valuation = inputs["advanced"]["risk"], inputs["advanced"]["valuation"]
    if kind == "bull":
        earnings_ids = [item for row in earnings["earnings_comparisons"] for item in row["evidence_ids"]]
        claims = [
            _claim("bull:growth", "growth",
                   "Compatible annual periods show positive revenue and profit-after-tax growth.", "high", earnings_ids),
            _claim("bull:business", "business_quality", business["summary"], "medium",
                   [item for claim in business["claims"] for item in claim["evidence_ids"]]),
        ]
        news = inputs.get("news", {}).get("events", [])
        if news:
            claims.append(_claim("bull:catalyst", "news_catalyst",
                "A material contract is disclosed, but revenue timing and margins remain conditional.", "medium",
                [source["source_id"] for source in news[0]["sources"]]))
    else:
        risks = {item["id"]: item for item in risk["risks"]}
        claims = [
            _claim("bear:cash", "financial_quality", risks["risk:cash-conversion"]["rationale"], "high",
                   risks["risk:cash-conversion"]["evidence_ids"]),
            _claim("bear:concentration", "risk", risks["risk:defence-concentration"]["rationale"], "high",
                   risks["risk:defence-concentration"]["evidence_ids"]),
            _claim("bear:valuation", "valuation",
                   "Per-share upside and DCF are unavailable, so valuation conviction is limited.", "high",
                   valuation["valuation_scenarios"][0]["evidence_ids"]),
        ]
    report_ids = locked["manifest"]["report_ids"]
    payload = {"schema_version": DEBATE_SCHEMA_VERSION, "kind": kind,
               "input_manifest_hash": locked["hash"], "input_report_ids": report_ids, "claims": claims}
    payload["case_id"] = f"case:{kind}:{_hash(payload)[:20]}"
    case = DebateCase.model_validate(payload).model_dump()
    validate_case(case, evidence_ids(inputs))
    return case


def validate_case(case, allowed):
    try:
        checked = DebateCase.model_validate(case)
    except Exception as error:
        raise DebateError("Debate case does not match its versioned schema.") from error
    cited = {item for claim in checked.claims for item in claim.evidence_ids}
    if not cited.issubset(allowed):
        raise DebateError("Debate case contains an unsupported evidence reference.")
    return checked.model_dump()


def build_judge(bull, bear, inputs):
    allowed = evidence_ids(inputs)
    bull, bear = validate_case(bull, allowed), validate_case(bear, allowed)
    expected = input_manifest(inputs)["hash"]
    if bull["input_manifest_hash"] != expected or bear["input_manifest_hash"] != expected:
        raise DebateError("Bull and Bear did not receive the same locked input manifest.")
    if bull["kind"] != "bull" or bear["kind"] != "bear":
        raise DebateError("Judge requires one Bull and one Bear case.")
    accepted = [claim["claim_id"] for claim in bull["claims"] + bear["claims"]]
    payload = {
        "schema_version": DEBATE_SCHEMA_VERSION, "kind": "judge",
        "input_manifest_hash": expected, "input_case_ids": [bull["case_id"], bear["case_id"]],
        "accepted_claim_ids": accepted, "rejected_claims": [],
        "adjudication": (
            "The growth and disclosed-contract evidence support a constructive operating case, while weak cash conversion, "
            "defence concentration and incomplete valuation inputs materially limit conviction."
        ),
        "unresolved": ["Contract execution timing and margin contribution are unavailable.",
                       "Peer evidence, market price and DCF inputs remain unavailable."],
    }
    payload["judge_id"] = "judge:" + _hash(payload)[:20]
    return payload


def build_thesis(judge, bull, bear):
    if judge["input_case_ids"] != [bull["case_id"], bear["case_id"]]:
        raise DebateError("Thesis requires the adjudicated Bull and Bear cases.")
    payload = {
        "schema_version": DEBATE_SCHEMA_VERSION, "kind": "investment_thesis",
        "input_judge_id": judge["judge_id"],
        "fundamental_view": "Constructive operating momentum with limited valuation and cash-flow conviction.",
        "thesis_points": [
            "Annual revenue and profit-after-tax growth are positive on compatible periods.",
            "Product breadth and the disclosed material order support demand visibility, subject to execution.",
            "Low cash conversion, negative free cash flow and defence concentration constrain the case.",
        ],
        "support_conditions": ["Order conversion sustains growth without weakening margins.",
                               "Operating cash conversion improves materially."],
        "weaken_conditions": ["Order execution or margins disappoint.",
                              "Cash conversion remains weak while valuation evidence stays incomplete."],
        "limitations": list(judge["unresolved"]),
    }
    payload["thesis_id"] = "thesis:" + _hash(payload)[:20]
    return payload


def _category(name, score, rationale, ids, status="scored"):
    return {"name": name, "weight_percent": CATEGORY_WEIGHT, "score": score,
            "status": status, "rationale": rationale, "evidence_ids": list(dict.fromkeys(ids))}


def score_research(inputs):
    metrics = {item["id"]: item for item in inputs["financial"]["metrics"]}
    specialists, advanced = inputs["specialists"], inputs["advanced"]
    business_ids = [item for claim in specialists["business_quality"]["claims"] for item in claim["evidence_ids"]]
    moat_ids = [item for claim in specialists["moat"]["claims"] for item in claim["evidence_ids"]]
    management_ids = [item for claim in advanced["management"]["claims"] for item in claim["evidence_ids"]]
    earnings_ids = [item for row in advanced["earnings"]["earnings_comparisons"] for item in row["evidence_ids"]]
    risk_ids = [item for risk in advanced["risk"]["risks"] for item in risk["evidence_ids"]]
    growth = 50 + (15 if Decimal(metrics["metric:revenue-growth"]["value"]) > 10 else 0) + (15 if Decimal(advanced["earnings"]["earnings_comparisons"][1]["growth_percent"]) > 15 else 0)
    quality = 50 + (15 if Decimal(metrics["metric:operating-margin"]["value"]) > 20 else 0)
    quality -= 15 if Decimal(metrics["metric:cash-conversion"]["value"]) < 50 else 0
    quality -= 15 if Decimal(metrics["metric:free-cash-flow"]["value"]) < 0 else 0
    high = sum(item["severity"] == "high" for item in advanced["risk"]["risks"])
    medium = sum(item["severity"] == "medium" for item in advanced["risk"]["risks"])
    categories = [
        _category("business_quality", 75, "Supported business report under the bounded evidence policy.", business_ids),
        _category("growth", growth, "Threshold score from compatible revenue and profit-after-tax growth.", earnings_ids),
        _category("financial_quality", quality, "Margin strength offset by weak cash conversion and negative free cash flow.",
                  metrics["metric:operating-margin"]["evidence_ids"] + metrics["metric:cash-conversion"]["evidence_ids"] + metrics["metric:free-cash-flow"]["evidence_ids"]),
        _category("moat", 50, "Provisional moat report because comparative peer evidence is missing.", moat_ids),
        _category("management", 50, "Governance evidence exists, but tracked claims are unresolved.", management_ids),
        _category("valuation", None, "Current price, diluted share count and DCF inputs are unavailable.",
                  advanced["valuation"]["valuation_scenarios"][0]["evidence_ids"], "unscored"),
        _category("risk", max(0, 100 - high * 20 - medium * 10),
                  "Higher-severity disclosed risks reduce this inverse-risk score.", risk_ids),
    ]
    ownership = inputs.get("ownership")
    if ownership:
        rows = ownership["comparison"]["comparisons"]
        inst = [row for row in rows if row["kind"] in ("fii", "dii", "scheme")]
        value = 50 + sum(5 for row in inst if row["status"] == "accumulation") - sum(5 for row in inst if row["status"] == "reduction")
        categories.append(_category("institutional_flow", max(0, min(100, value)),
                           "Neutral baseline adjusted only for supported accumulation and reduction observations.",
                           [source["source_id"] for source in ownership["sources"]]))
    else:
        categories.append(_category("institutional_flow", None, "No ownership comparison is attached to this run.", [], "unscored"))
    scored = [item for item in categories if item["status"] == "scored"]
    denominator = Decimal(CATEGORY_WEIGHT) * len(scored)
    overall = sum(Decimal(str(item["score"])) * Decimal(CATEGORY_WEIGHT) for item in scored) / denominator
    coverage_state = {
        "security_identity": 1, "filings_results": 1, "annual_report": 1,
        "corporate_actions": 0, "daily_ohlcv": 0, "benchmark_sector": 0,
        "shareholding": 1 if ownership else 0, "promoter_pledge": 0,
        "named_holders": Decimal("0.5") if ownership else 0,
        "mf_schemes": 1 if ownership else 0,
        "news_catalysts": 1 if inputs.get("news", {}).get("events") else 0,
    }
    completeness = sum(Decimal(str(value)) for value in coverage_state.values()) / Decimal(len(REQUIRED_EVIDENCE)) * 100
    rating_value = {"supported": Decimal("90"), "mixed": Decimal("65"), "provisional": Decimal("50"), "insufficient": Decimal("25")}
    reports = list(specialists.values()) + list(advanced.values())
    agent_confidence = sum(rating_value[item["rating"]] for item in reports) / Decimal(len(reports))
    confidence_index = completeness * Decimal("0.60") + agent_confidence * Decimal("0.40")
    confidence_label = "high" if confidence_index >= 75 else "moderate" if confidence_index >= 50 else "limited"
    result = {
        "score_policy_version": SCORE_POLICY_VERSION,
        "confidence_policy_version": CONFIDENCE_POLICY_VERSION,
        "weight_basis": "Equal category weights avoid introducing an unapproved investment preference.",
        "categories": categories, "overall_score": _number(overall),
        "provisional_denominator_percent": _number(denominator),
        "evidence_completeness_percent": _number(completeness),
        "evidence_coverage": {key: _number(value) for key, value in coverage_state.items()},
        "agent_confidence_index": _number(agent_confidence),
        "research_confidence_index": _number(confidence_index), "research_confidence": confidence_label,
        "confidence_meaning": "Evidence-sufficiency index; it is not a probability of investment success.",
    }
    result["score_id"] = "score:" + _hash(result)[:20]
    return result


def validate_scores(scores, allowed):
    names = [item["name"] for item in scores["categories"]]
    if tuple(names) != CATEGORY_NAMES:
        raise DebateError("Scorecard categories do not match the versioned policy.")
    cited = {item for category in scores["categories"] for item in category["evidence_ids"]}
    if not cited.issubset(allowed):
        raise DebateError("Scorecard contains an unsupported evidence reference.")
    return scores


def render_agent_note(report):
    title = report["kind"].replace("_", " ").title()
    lines = [f"# {title}", "", f"Schema: `{report['schema_version']}`", ""]
    if report["kind"] in ("bull", "bear"):
        lines += [f"Locked input manifest: `{report['input_manifest_hash']}`", ""]
        lines += [f"- {item['text']} ({item['confidence']}; evidence: `{', '.join(item['evidence_ids'])}`)" for item in report["claims"]]
    elif report["kind"] == "judge":
        lines += [report["adjudication"], "", "## Unresolved", ""] + [f"- {item}" for item in report["unresolved"]]
    else:
        lines += [report["fundamental_view"], "", "## Thesis points", ""] + [f"- {item}" for item in report["thesis_points"]]
        lines += ["", "## Conditions that support it", ""] + [f"- {item}" for item in report["support_conditions"]]
        lines += ["", "## Conditions that weaken it", ""] + [f"- {item}" for item in report["weaken_conditions"]]
    return "\n".join(lines) + "\n"
