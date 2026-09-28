"""Deterministic earnings, claim tracking, valuation, management and risk research."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .specialists import Claim


ADVANCED_SCHEMA_VERSION = "event-specialist-report/v2"
EARNINGS_POLICY_VERSION = "compatible-annual-earnings/v1"
CLAIM_POLICY_VERSION = "management-claim-status/v1"
VALUATION_POLICY_VERSION = "earnings-multiple-scenarios/v2"
RISK_POLICY_VERSION = "material-risk-baseline/v1"


class EventResearchError(Exception):
    pass


class EarningsComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["revenue", "profit_after_tax"]
    current_period: str
    prior_period: str
    current_value: str
    prior_value: str
    unit: str
    growth_percent: str
    formula: Literal["(current / prior - 1) × 100"]
    evidence_ids: list[str] = Field(min_length=2)


class ConsensusState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "unavailable"]
    reason: str | None
    source_period: str | None


class ValuationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["conservative", "base", "optimistic"]
    earnings_value: str
    earnings_period: str
    earnings_unit: str
    pe_multiple: str
    implied_equity_value: str
    output_unit: Literal["INR crore"]
    formula: Literal["profit after tax × P/E multiple"]
    evidence_ids: list[str] = Field(min_length=1)


class SensitivityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    earnings_change_percent: int
    pe_multiple: int
    implied_equity_value: str


class Applicability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["earnings-multiple equity value", "per-share value/upside", "DCF"]
    status: Literal["applicable", "not-applicable"]
    reason: str


class ManagementClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    text: str
    made_period: str
    target_period: str
    metric: str
    baseline_value: str | None
    target_value: str | None
    unit: str | None
    direction: Literal["increase", "decrease", "qualitative"]
    evidence_ids: list[str] = Field(min_length=1)


class ClaimState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    observed_period: str
    actual_value: str | None
    status: Literal["pending", "met", "missed", "partial", "unverifiable"]
    reason: str
    evidence_ids: list[str] = Field(min_length=1)


class RiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    severity: Literal["high", "medium", "low"]
    rationale: str
    evidence_ids: list[str] = Field(min_length=1)


class AdvancedReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str
    schema_version: Literal["event-specialist-report/v2"]
    policy_version: str
    evidence_version: str
    kind: Literal["earnings", "management_claims", "valuation", "management", "risk"]
    symbol: str
    period: str
    period_end: str
    summary: str
    rating: Literal["supported", "mixed", "provisional", "insufficient"]
    source_periods: list[str]
    limitations: list[str]
    input_report_ids: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    earnings_comparisons: list[EarningsComparison] = Field(default_factory=list)
    consensus: ConsensusState | None = None
    valuation_scenarios: list[ValuationScenario] = Field(default_factory=list)
    sensitivity: list[SensitivityPoint] = Field(default_factory=list)
    applicability: list[Applicability] = Field(default_factory=list)
    management_claims: list[ManagementClaim] = Field(default_factory=list)
    claim_states: list[ClaimState] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_payload(self):
        checks = {
            "earnings": bool(self.earnings_comparisons and self.consensus),
            "management_claims": bool(self.management_claims and self.claim_states),
            "valuation": bool(self.valuation_scenarios and self.sensitivity and self.applicability),
            "management": bool(self.claims and self.input_report_ids),
            "risk": bool(self.risks and self.claims and self.input_report_ids),
        }
        if not checks[self.kind]:
            raise ValueError(f"{self.kind} report is missing its required payload")
        return self


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _number(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _finish(payload: dict) -> dict:
    payload = {"schema_version": ADVANCED_SCHEMA_VERSION, **payload}
    payload["report_id"] = f"report:{payload['kind']}:{_hash(payload)[:20]}"
    try:
        return AdvancedReport.model_validate(payload).model_dump()
    except Exception as error:
        raise EventResearchError("Event research output does not match the versioned schema.") from error


def _fact(snapshot, key, period):
    try:
        return next(item for item in snapshot["facts"] if item["key"] == key and item["period"] == period)
    except StopIteration:
        raise EventResearchError(f"Required {key} fact is unavailable for {period}.") from None


def _comparison(snapshot, key, label):
    current, prior = _fact(snapshot, key, "FY2025"), _fact(snapshot, key, "FY2024")
    if current["scope"] != prior["scope"] or current["unit"] != prior["unit"] or current["period_end"] <= prior["period_end"]:
        raise EventResearchError(f"{label} periods are not comparable.")
    if current["value"] is None or prior["value"] in (None, "0", "0.00"):
        raise EventResearchError(f"{label} comparison has a missing or zero input.")
    growth = (Decimal(current["value"]) / Decimal(prior["value"]) - 1) * 100
    return {
        "metric": key, "current_period": current["period"], "prior_period": prior["period"],
        "current_value": current["value"], "prior_value": prior["value"], "unit": current["unit"],
        "growth_percent": _number(growth), "formula": "(current / prior - 1) × 100",
        "evidence_ids": [current["evidence_id"], prior["evidence_id"]],
    }


def build_earnings(snapshot: dict) -> dict:
    comparisons = [_comparison(snapshot, "revenue", "Revenue"),
                   _comparison(snapshot, "profit_after_tax", "Profit after tax")]
    return _finish({
        "policy_version": EARNINGS_POLICY_VERSION, "evidence_version": snapshot["extractor_version"],
        "kind": "earnings", "symbol": snapshot["source"]["symbol"], "period": snapshot["period"],
        "period_end": "2025-03-31", "summary": (
            f"FY2025 revenue grew {comparisons[0]['growth_percent']}% and profit after tax grew "
            f"{comparisons[1]['growth_percent']}% on compatible consolidated annual periods."
        ), "rating": "supported", "source_periods": ["S1 FY2025", "S1 FY2024"],
        "limitations": ["No consensus source is present, so earnings surprise is unavailable."],
        "earnings_comparisons": comparisons,
        "consensus": {"status": "unavailable", "reason": "missing-consensus-source", "source_period": None},
    })


def build_valuation(earnings: dict) -> dict:
    checked = AdvancedReport.model_validate(earnings)
    pat = next(item for item in checked.earnings_comparisons if item.metric == "profit_after_tax")
    value = Decimal(pat.current_value)
    valuation_evidence = list(dict.fromkeys(pat.evidence_ids))
    multiples = (("conservative", 20), ("base", 25), ("optimistic", 30))
    scenarios = [{
        "name": name, "earnings_value": pat.current_value, "earnings_period": pat.current_period,
        "earnings_unit": pat.unit, "pe_multiple": str(multiple),
        "implied_equity_value": _number(value * multiple), "output_unit": "INR crore",
        "formula": "profit after tax × P/E multiple", "evidence_ids": valuation_evidence,
    } for name, multiple in multiples]
    sensitivity = [{"earnings_change_percent": change, "pe_multiple": multiple,
                    "implied_equity_value": _number(value * (Decimal(100 + change) / 100) * multiple)}
                   for change in (-10, 0, 10) for multiple in (20, 25, 30)]
    return _finish({
        "policy_version": VALUATION_POLICY_VERSION, "evidence_version": earnings["evidence_version"],
        "kind": "valuation", "symbol": earnings["symbol"], "period": earnings["period"],
        "period_end": earnings["period_end"],
        "summary": "The bounded valuation applies explicit illustrative P/E multiples to reported FY2025 profit after tax; market-price upside and DCF remain unavailable.",
        "rating": "provisional", "source_periods": earnings["source_periods"],
        "limitations": ["Multiples are analyst assumptions, not market observations or target prices.",
                        "No forecast cash flows, discount rate, terminal growth, share count or current price are available."],
        "input_report_ids": [earnings["report_id"]], "valuation_scenarios": scenarios,
        "sensitivity": sensitivity, "applicability": [
            {"metric": "earnings-multiple equity value", "status": "applicable", "reason": "Reported profit after tax is positive."},
            {"metric": "per-share value/upside", "status": "not-applicable", "reason": "Current price and diluted share count are unavailable."},
            {"metric": "DCF", "status": "not-applicable", "reason": "Forecast cash flows and discount assumptions are unavailable."},
        ],
    })


def _period_number(period: str) -> int | None:
    if period.startswith("FY") and period[2:].isdigit():
        return int(period[2:])
    return None


def evaluate_claim(claim: dict, observation: dict | None, observed_period: str) -> dict:
    checked = ManagementClaim.model_validate(claim)
    evidence_ids = list(checked.evidence_ids)
    if observation and observation.get("evidence_id"):
        evidence_ids.append(observation["evidence_id"])
    target, observed = _period_number(checked.target_period), _period_number(observed_period)
    actual = None if not observation else observation.get("value")
    if target is None:
        status, reason = "unverifiable", "Management did not provide a dated target period."
    elif observed is not None and observed < target:
        status, reason = "pending", "The target period has not ended."
    elif checked.target_value is None or checked.direction == "qualitative":
        status, reason = "unverifiable", "The claim has no measurable target threshold."
    elif actual is None:
        status, reason = "unverifiable", "No later compatible observation is available."
    else:
        actual_value, target_value = Decimal(str(actual)), Decimal(checked.target_value)
        baseline = Decimal(checked.baseline_value) if checked.baseline_value is not None else None
        met = actual_value >= target_value if checked.direction == "increase" else actual_value <= target_value
        progressed = baseline is not None and (actual_value > baseline if checked.direction == "increase" else actual_value < baseline)
        status, reason = ("met", "The later observation meets the stated threshold.") if met else (
            ("partial", "The later observation improved from baseline but missed the threshold.") if progressed else
            ("missed", "The later observation did not meet the threshold or improve from baseline.")
        )
    return ClaimState.model_validate({"claim_id": checked.claim_id, "observed_period": observed_period,
        "actual_value": str(actual) if actual is not None else None, "status": status,
        "reason": reason, "evidence_ids": list(dict.fromkeys(evidence_ids))}).model_dump()


def build_management_claims(bundle: dict) -> dict:
    ids = {item["id"].split(":")[-1]: item["id"] for item in bundle["evidence"]}
    claims = [
        {"claim_id": "claim:BEL:FY2025:order-inflows", "text": "Management expects good order inflows over the next two to three years.",
         "made_period": "FY2025", "target_period": "FY2028", "metric": "order-inflow quality",
         "baseline_value": None, "target_value": None, "unit": None, "direction": "qualitative",
         "evidence_ids": [ids["order-book"]]},
        {"claim_id": "claim:BEL:FY2025:non-defence-share", "text": "Management aims for non-defence business to reach about 20% of turnover in coming years.",
         "made_period": "FY2025", "target_period": "unknown", "metric": "non-defence turnover share",
         "baseline_value": "5.74", "target_value": "20", "unit": "%", "direction": "increase",
         "evidence_ids": [ids["non-defence-target"]]},
    ]
    states = [evaluate_claim(claim, None, bundle["period"]) for claim in claims]
    return _finish({
        "policy_version": CLAIM_POLICY_VERSION, "evidence_version": bundle["version"],
        "kind": "management_claims", "symbol": bundle["symbol"], "period": bundle["period"],
        "period_end": bundle["period_end"],
        "summary": "One dated qualitative claim remains pending; the diversification target is unverifiable because management did not provide a target year.",
        "rating": "insufficient", "source_periods": [f"S1 {bundle['period']}"],
        "limitations": ["The current source set contains no later period with which to resolve either claim."],
        "management_claims": claims, "claim_states": states,
    })


def build_management(bundle: dict, tracker: dict) -> dict:
    ids = {item["id"].split(":")[-1]: item["id"] for item in bundle["evidence"]}
    return _finish({
        "policy_version": CLAIM_POLICY_VERSION, "evidence_version": bundle["version"],
        "kind": "management", "symbol": bundle["symbol"], "period": bundle["period"],
        "period_end": bundle["period_end"],
        "summary": "BEL describes Board-level enterprise-risk oversight, while the bounded claim record remains too early or too imprecise to score delivery.",
        "rating": "provisional", "source_periods": [f"S1 {bundle['period']}"],
        "limitations": ["No independent governance assessment or later claim-resolution period is present."],
        "input_report_ids": [tracker["report_id"]], "claims": [{
            "id": "management:1", "text": "The issuer reports Board oversight of significant enterprise risks and mitigation status.",
            "evidence_type": "fact_source_reported", "confidence": "high", "evidence_ids": [ids["risk-governance"]],
        }],
    })


def build_risk(bundle: dict, snapshot: dict, earnings: dict, valuation: dict) -> dict:
    ids = {item["id"].split(":")[-1]: item["id"] for item in bundle["evidence"]}
    metrics = {item["id"]: item for item in snapshot["metrics"]}
    cash, fcf = metrics["metric:cash-conversion"], metrics["metric:free-cash-flow"]
    risks = [
        {"id": "risk:defence-concentration", "title": "Defence concentration", "severity": "high",
         "rationale": "The disclosed turnover mix is heavily concentrated in defence.", "evidence_ids": [ids["business-mix"]]},
        {"id": "risk:technology-access", "title": "Technology and sourcing", "severity": "medium",
         "rationale": "Rapid technology change, critical technology sourcing and proprietary lock-in are issuer-disclosed challenges.", "evidence_ids": [ids["technology-risk"]]},
        {"id": "risk:cash-conversion", "title": "Cash conversion", "severity": "high",
         "rationale": f"FY2025 operating cash conversion was {cash['value']}% and free cash flow was INR {fcf['value']} crore.",
         "evidence_ids": list(dict.fromkeys(cash["evidence_ids"] + fcf["evidence_ids"]))},
        {"id": "risk:valuation-inputs", "title": "Valuation uncertainty", "severity": "high",
         "rationale": "The scenario range depends on assumed earnings multiples; current price, share count and DCF inputs are missing.",
         "evidence_ids": valuation["valuation_scenarios"][0]["evidence_ids"]},
    ]
    return _finish({
        "policy_version": RISK_POLICY_VERSION, "evidence_version": bundle["version"],
        "kind": "risk", "symbol": bundle["symbol"], "period": bundle["period"],
        "period_end": bundle["period_end"],
        "summary": "Defence concentration, weak FY2025 cash conversion, technology access and incomplete valuation inputs are the principal bounded risks.",
        "rating": "mixed", "source_periods": [f"S1 {bundle['period']}", "S1 FY2024"],
        "limitations": ["Risk severity is a versioned baseline classification, not a portfolio-sizing recommendation."],
        "input_report_ids": [earnings["report_id"], valuation["report_id"]], "risks": risks,
        "claims": [{"id": "risk:governance", "text": "The issuer reports an enterprise-risk framework with Board-level oversight.",
                    "evidence_type": "fact_source_reported", "confidence": "high", "evidence_ids": [ids["risk-governance"]]}],
    })


def validate_advanced_report(report: dict, evidence_ids: set[str]) -> dict:
    try:
        checked = AdvancedReport.model_validate(report)
    except Exception as error:
        raise EventResearchError("Event research output does not match the versioned schema.") from error
    cited = {item for claim in checked.claims for item in claim.evidence_ids}
    cited |= {item for comparison in checked.earnings_comparisons for item in comparison.evidence_ids}
    cited |= {item for scenario in checked.valuation_scenarios for item in scenario.evidence_ids}
    cited |= {item for claim in checked.management_claims for item in claim.evidence_ids}
    cited |= {item for state in checked.claim_states for item in state.evidence_ids}
    cited |= {item for risk in checked.risks for item in risk.evidence_ids}
    if not cited.issubset(evidence_ids):
        raise EventResearchError("Event research report contains an unsupported evidence reference.")
    return checked.model_dump()


def render_advanced_note(report: dict) -> str:
    lines = [f"# {report['symbol']} — {report['kind'].replace('_', ' ').title()}", "",
             f"**Period:** {report['period']}  ", f"**Assessment:** {report['rating']}  ",
             f"**Schema:** `{report['schema_version']}`  ", f"**Report ID:** `{report['report_id']}`", "",
             report["summary"], ""]
    if report["earnings_comparisons"]:
        lines += ["## Compatible-period earnings", ""]
        lines += [f"- {item['metric']}: {item['current_period']} {item['current_value']} vs {item['prior_period']} {item['prior_value']} {item['unit']}; growth {item['growth_percent']}%. Evidence: `{', '.join(item['evidence_ids'])}`." for item in report["earnings_comparisons"]]
        lines += ["", f"Consensus: **{report['consensus']['status']}** — {report['consensus']['reason']}.", ""]
    if report["valuation_scenarios"]:
        lines += ["## Valuation scenarios", ""] + [f"- {item['name']}: {item['pe_multiple']}x FY2025 profit after tax = INR {item['implied_equity_value']} crore. Evidence: `{', '.join(item['evidence_ids'])}`." for item in report["valuation_scenarios"]]
        lines += ["", "Sensitivity covers earnings changes of -10%, 0% and +10% across 20x, 25x and 30x P/E.", ""]
    if report["management_claims"]:
        lines += ["## Claim states", ""]
        states = {item["claim_id"]: item for item in report["claim_states"]}
        lines += [f"- {item['text']} Target: {item['target_period']}; status: **{states[item['claim_id']]['status']}** — {states[item['claim_id']]['reason']} Evidence: `{', '.join(states[item['claim_id']]['evidence_ids'])}`." for item in report["management_claims"]]
    if report["claims"]:
        lines += ["## Evidence-backed findings", ""] + [f"- {item['text']} ({item['evidence_type']}; {item['confidence']}; evidence: `{', '.join(item['evidence_ids'])}`)" for item in report["claims"]]
    if report["risks"]:
        lines += ["## Material risks", ""] + [f"- **{item['severity']} — {item['title']}:** {item['rationale']} Evidence: `{', '.join(item['evidence_ids'])}`." for item in report["risks"]]
    if report["applicability"]:
        lines += ["", "## Applicability", ""] + [f"- {item['metric']}: **{item['status']}** — {item['reason']}" for item in report["applicability"]]
    lines += ["", "## Limits", ""] + [f"- {item}" for item in report["limitations"]]
    if report["input_report_ids"]:
        lines += ["", "## Declared inputs", ""] + [f"- `{item}`" for item in report["input_report_ids"]]
    return "\n".join(lines) + "\n"


def condensed_advanced(report: dict, note: dict) -> dict:
    return {"report_id": report["report_id"], "kind": report["kind"], "rating": report["rating"],
            "summary": report["summary"], "source_periods": report["source_periods"],
            "limitations": report["limitations"], "note": note}
