"""Traceable financial extraction and deterministic baseline metrics."""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from pypdf import PdfReader

from .store import now
from .vault import NoteConflict, Vault, digest

EXTRACTOR_VERSION = "bel-annual-report/v1"
FORMULA_VERSION = "baseline-financials/v1"
SCHEMA_VERSION = "financial-snapshot/v1"
MONEY_UNIT = "INR crore"
REPORTING_UNIT = "INR lakh"


class FinancialError(Exception):
    def __init__(self, status: str, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def _decimal_text(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(value, "f")


def parse_amount(value: str, unit: str = REPORTING_UNIT) -> tuple[str | None, str | None]:
    """Return crore-normalized text and a visible missing reason."""
    cleaned = value.strip().replace("₹", "").replace("`", "")
    if cleaned in {"-", "–", "—", ""}:
        return None, "reported-dash"
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()").replace(",", "").strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        raise FinancialError("unsupported", "A located financial value could not be normalized.") from None
    if negative:
        number = -number
    scales = {"INR lakh": Decimal("0.01"), "INR crore": Decimal("1")}
    if unit not in scales:
        raise FinancialError("unsupported", "The statement uses an unsupported reporting unit.")
    return _decimal_text(number * scales[unit]), None


def _clean(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


PAIR = r"(\(?[\d,]+(?:\.\d+)?\)?|[-–—])\s+(\(?[\d,]+(?:\.\d+)?\)?|[-–—])"


def _pair(text: str, label_pattern: str, occurrence: int = 0) -> tuple[str, str]:
    matches = list(re.finditer(label_pattern + r"\s+" + PAIR, text, re.I))
    if len(matches) <= occurrence:
        raise FinancialError("unsupported", "The filing layout is outside the measured extraction coverage.")
    match = matches[occurrence]
    return match.group(1), match.group(2)


def _fact(source: dict, *, key: str, label: str, raw: str, period: str,
          period_end: str, statement: str, row: str, pdf_page: int,
          restated: bool = False, restatement_note: str | None = None) -> dict:
    value, missing = parse_amount(raw)
    fact_id = "fact:" + hashlib.sha256(
        f"{source['id']}|{key}|{period_end}|consolidated|{EXTRACTOR_VERSION}".encode()
    ).hexdigest()[:20]
    return {
        "id": fact_id,
        "key": key,
        "label": label,
        "value": value,
        "unit": MONEY_UNIT,
        "reported_value": raw,
        "reported_unit": REPORTING_UNIT,
        "currency": "INR",
        "period": period,
        "period_kind": "annual",
        "period_end": period_end,
        "scope": "consolidated",
        "restated": restated,
        "restatement_note": restatement_note,
        "missing_reason": missing,
        "source_id": source["id"],
        "evidence_id": f"evidence:{source['id'][:12]}:pdf-{pdf_page}:{key}",
        "locator": {"pdf_page": pdf_page, "statement": statement, "row": row},
        "extractor_version": EXTRACTOR_VERSION,
    }


def extract_page_texts(source: dict, pages: dict[str, tuple[int, str]]) -> list[dict]:
    """Parse already-located statement pages; separated for small golden tests."""
    balance_page, balance = pages["balance_sheet"]
    profit_page, profit = pages["profit_loss"]
    cash_page, cash = pages["cash_flow"]
    balance, profit, cash = map(_clean, (balance, profit, cash))

    rows = [
        ("balance_sheet", balance_page, balance, "total_assets", "Total assets", r"TOTAL ASSETS", 0),
        ("balance_sheet", balance_page, balance, "total_equity", "Total equity", r"Total equity(?! attributable)", 0),
        ("balance_sheet", balance_page, balance, "borrowings_non_current", "Non-current borrowings", r"Borr\s*owings\s+18", 0),
        ("balance_sheet", balance_page, balance, "borrowings_current", "Current borrowings", r"Borr\s*owings\s+18", 1),
        ("profit_loss", profit_page, profit, "revenue", "Revenue from operations", r"Revenue from operations\s+23", 0),
        ("profit_loss", profit_page, profit, "other_income", "Other income", r"Other income\s+24", 0),
        ("profit_loss", profit_page, profit, "finance_cost", "Finance costs", r"Finance costs\s+27", 0),
        ("profit_loss", profit_page, profit, "profit_before_tax", "Profit before tax", r"tax \(III - IV\)", 0),
        ("profit_loss", profit_page, profit, "profit_after_tax", "Profit for the year", r"Profit for the year \(IX\+X\)", 0),
        ("cash_flow", cash_page, cash, "cash_from_operations", "Net cash from operating activities", r"Net Cash from / \(used in\) Operating Activities", 0),
        ("cash_flow", cash_page, cash, "capital_expenditure", "Purchase of property, plant, equipment and intangibles", r"Purchase of property, plant and equipment and other intangible assets", 0),
    ]
    facts = []
    for statement, page, text, key, label, pattern, occurrence in rows:
        current, prior = _pair(text, pattern, occurrence)
        facts.extend([
            _fact(source, key=key, label=label, raw=current, period="FY2025", period_end="2025-03-31",
                  statement=statement, row=label, pdf_page=page),
            _fact(source, key=key, label=label, raw=prior, period="FY2024", period_end="2024-03-31",
                  statement=statement, row=label, pdf_page=page,
                  restated=statement == "cash_flow",
                  restatement_note="Prior cash-flow figures were reported as regrouped or reclassified where necessary."
                  if statement == "cash_flow" else None),
        ])
    return facts


def extract_pdf(source: dict, content: bytes) -> list[dict]:
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        located: dict[str, tuple[int, str]] = {}
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            normalized = _clean(text)
            if "balance_sheet" not in located and "Consolidated Balance Sheet" in normalized and "TOTAL ASSETS" in normalized:
                located["balance_sheet"] = (index, text)
            if "profit_loss" not in located and "Consolidated Statement of Profit and Loss" in normalized and "Revenue from operations" in normalized:
                located["profit_loss"] = (index, text)
            if "cash_flow" not in located and "Consolidated Statement of Cash Flows" in normalized and "Net Cash from / (used in) Operating Activities" in normalized:
                located["cash_flow"] = (index, text)
            if len(located) == 3:
                break
        if len(located) != 3:
            missing = ", ".join(sorted({"balance_sheet", "profit_loss", "cash_flow"} - set(located)))
            raise FinancialError("unsupported", f"Consolidated statement pages were not located: {missing}.")
        return extract_page_texts(source, located)
    except FinancialError:
        raise
    except Exception:
        raise FinancialError("unsupported", "The saved PDF could not be read by the financial extractor.") from None


def _metric(metric_id: str, label: str, value: Decimal | None, unit: str, formula: str,
            inputs: list[dict], reason: str | None = None) -> dict:
    return {
        "id": "metric:" + metric_id,
        "label": label,
        "value": _decimal_text(value) if value is not None else None,
        "unit": unit,
        "availability": "available" if value is not None else "unavailable",
        "reason": reason,
        "period": "FY2025",
        "period_end": "2025-03-31",
        "scope": inputs[0]["scope"] if inputs else "consolidated",
        "formula": formula,
        "formula_version": FORMULA_VERSION,
        "input_fact_ids": [item["id"] for item in inputs],
        "evidence_ids": [item["evidence_id"] for item in inputs],
        "input_restated": any(item.get("restated") for item in inputs),
    }


def ratio_metric(metric_id: str, label: str, numerator: dict, denominator: dict,
                 *, multiplier: Decimal = Decimal("100"), unit: str = "%", formula: str) -> dict:
    inputs = [numerator, denominator]
    if numerator["scope"] != denominator["scope"]:
        return _metric(metric_id, label, None, unit, formula, inputs, "incompatible-account-scope")
    if numerator["period_end"] != denominator["period_end"]:
        return _metric(metric_id, label, None, unit, formula, inputs, "incompatible-periods")
    if numerator["unit"] != denominator["unit"]:
        return _metric(metric_id, label, None, unit, formula, inputs, "incompatible-units")
    if numerator["value"] is None or denominator["value"] is None:
        return _metric(metric_id, label, None, unit, formula, inputs, "missing-input")
    divisor = Decimal(denominator["value"])
    if divisor == 0:
        return _metric(metric_id, label, None, unit, formula, inputs, "zero-denominator")
    return _metric(metric_id, label, Decimal(numerator["value"]) / divisor * multiplier, unit, formula, inputs)


def growth_metric(metric_id: str, label: str, current: dict, prior: dict) -> dict:
    inputs = [current, prior]
    formula = "(current / prior - 1) × 100"
    if current["scope"] != prior["scope"]:
        return _metric(metric_id, label, None, "%", formula, inputs, "incompatible-account-scope")
    if current["key"] != prior["key"] or current["unit"] != prior["unit"]:
        return _metric(metric_id, label, None, "%", formula, inputs, "incompatible-series")
    if current["period_end"] <= prior["period_end"]:
        return _metric(metric_id, label, None, "%", formula, inputs, "incompatible-periods")
    if current["value"] is None or prior["value"] is None:
        return _metric(metric_id, label, None, "%", formula, inputs, "missing-input")
    base = Decimal(prior["value"])
    if base == 0:
        return _metric(metric_id, label, None, "%", formula, inputs, "zero-denominator")
    return _metric(metric_id, label, (Decimal(current["value"]) / base - 1) * 100, "%", formula, inputs)


def calculate_metrics(facts: list[dict]) -> list[dict]:
    indexed = {(fact["key"], fact["period"]): fact for fact in facts}
    current = lambda key: indexed[(key, "FY2025")]
    prior = lambda key: indexed[(key, "FY2024")]
    metrics = [growth_metric("revenue-growth", "Revenue growth", current("revenue"), prior("revenue"))]
    revenue, pbt, finance, other = map(current, ("revenue", "profit_before_tax", "finance_cost", "other_income"))
    derived = dict(pbt)
    if all(item["value"] is not None for item in (pbt, finance, other)):
        derived["value"] = _decimal_text(Decimal(pbt["value"]) + Decimal(finance["value"]) - Decimal(other["value"]))
        derived["id"] = "derived:operating-profit"
        derived["evidence_id"] = pbt["evidence_id"]
    else:
        derived["value"] = None
    operating = ratio_metric("operating-margin", "Operating margin (derived)", derived, revenue,
                             formula="(profit before tax + finance cost - other income) / revenue × 100")
    operating["input_fact_ids"] = [pbt["id"], finance["id"], other["id"], revenue["id"]]
    operating["evidence_ids"] = list(dict.fromkeys([pbt["evidence_id"], finance["evidence_id"], other["evidence_id"], revenue["evidence_id"]]))
    operating["input_restated"] = any(item["restated"] for item in (pbt, finance, other, revenue))
    metrics.append(operating)
    metrics.append(ratio_metric("net-profit-margin", "Net profit margin", current("profit_after_tax"), revenue,
                                formula="profit for the year / revenue × 100"))
    debt_inputs = [current("borrowings_non_current"), current("borrowings_current")]
    debt = dict(debt_inputs[0])
    debt["value"] = (_decimal_text(sum((Decimal(item["value"]) for item in debt_inputs), Decimal("0")))
                     if all(item["value"] is not None for item in debt_inputs) else None)
    debt["id"], debt["evidence_id"] = "derived:total-borrowings", debt_inputs[0]["evidence_id"]
    leverage = ratio_metric("debt-to-equity", "Total borrowings to equity", debt, current("total_equity"),
                            multiplier=Decimal("1"), unit="x", formula="(current + non-current borrowings) / total equity")
    leverage["input_fact_ids"] = [item["id"] for item in debt_inputs] + [current("total_equity")["id"]]
    leverage["evidence_ids"] = list(dict.fromkeys([item["evidence_id"] for item in debt_inputs] + [current("total_equity")["evidence_id"]]))
    metrics.append(leverage)
    metrics.append(ratio_metric("cash-conversion", "Operating cash conversion", current("cash_from_operations"), current("profit_after_tax"),
                                formula="net operating cash flow / profit for the year × 100"))
    cfo, capex = current("cash_from_operations"), current("capital_expenditure")
    if cfo["value"] is None or capex["value"] is None:
        fcf = _metric("free-cash-flow", "Free cash flow", None, MONEY_UNIT,
                      "net operating cash flow + reported capital expenditure outflow", [cfo, capex], "missing-input")
    else:
        fcf = _metric("free-cash-flow", "Free cash flow", Decimal(cfo["value"]) + Decimal(capex["value"]), MONEY_UNIT,
                      "net operating cash flow + reported capital expenditure outflow", [cfo, capex])
    metrics.append(fcf)
    return metrics


def build_snapshot(source: dict, content: bytes, extractor=extract_pdf) -> dict:
    facts = extractor(source, content)
    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "formula_version": FORMULA_VERSION,
        "created_at": now(),
        "source": {key: source.get(key) for key in ("id", "symbol", "title", "sha256", "origin", "retrieved_at")},
        "scope": "consolidated",
        "period": "FY2025",
        "facts": facts,
        "metrics": calculate_metrics(facts),
        "limitations": [
            "Measured extraction coverage is limited to BEL-style consolidated annual statements.",
            "A reported dash remains missing; it is not converted to zero.",
            "Operating margin is a transparent derived proxy, not a company-reported subtotal.",
            "Borrowings to equity covers reported current and non-current borrowings and excludes lease liabilities.",
        ],
    }


def render_note(snapshot: dict, interpretation: dict) -> str:
    source = snapshot["source"]
    lines = [f"# {source['symbol']} — traceable financial snapshot", "",
             f"Source: `{source['id']}` · scope: **consolidated** · period: **FY2025**", "",
             "## Deterministic metrics", ""]
    for metric in snapshot["metrics"]:
        display = f"{metric['value']} {metric['unit']}" if metric["value"] is not None else f"Unavailable ({metric['reason']})"
        lines += [f"### {metric['label']}", "", display, "", f"Formula: `{metric['formula']}`",
                  f"Inputs: {', '.join(metric['input_fact_ids'])}", ""]
    lines += ["## Located facts", "",
              "| Fact | Period | Value | Reported | Locator |", "|---|---:|---:|---:|---|"]
    for fact in snapshot["facts"]:
        value = f"{fact['value']} crore" if fact["value"] is not None else f"Unavailable ({fact['missing_reason']})"
        loc = fact["locator"]
        lines.append(f"| {fact['label']} | {fact['period']} | {value} | {fact['reported_value']} lakh | PDF p. {loc['pdf_page']}, {loc['statement']}, {loc['row']} |")
    lines += ["", "## Financial Analysis interpretation", ""]
    if interpretation.get("status") == "completed":
        result = interpretation["result"]
        lines += [result["summary"], ""]
        for observation in result["observations"]:
            lines += [f"- {observation['text']} ({', '.join(observation['metric_ids'])})"]
    else:
        lines += [interpretation.get("message", "Interpretation was not requested."), ""]
    lines += ["## Limits", ""] + [f"- {item}" for item in snapshot["limitations"]]
    lines += ["", f"Schema `{snapshot['schema_version']}` · extractor `{snapshot['extractor_version']}` · formulas `{snapshot['formula_version']}`", ""]
    return "\n".join(lines)


class FinancialService:
    def __init__(self, store, filings, vault_dir, *, extractor=extract_pdf, analyst=None):
        self.store, self.filings, self.vault = store, filings, Vault(vault_dir)
        self.extractor, self.analyst = extractor, analyst
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS financial_jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    fingerprint TEXT NOT NULL, source_id TEXT NOT NULL, use_reasoning INTEGER NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    snapshot TEXT, interpretation TEXT NOT NULL DEFAULT '{}',
                    note TEXT, note_path TEXT, note_hash TEXT, vault_root TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS financial_facts (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS financial_metrics (
                    run_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id,id)
                );
            """)
            db.execute("UPDATE financial_jobs SET status='queued' WHERE status='running'")

    def submit(self, source_id: str, key: str, use_reasoning: bool = False):
        try:
            self.filings.source(source_id)
        except KeyError:
            raise FinancialError("not-found", "Saved filing source not found.") from None
        fingerprint = hashlib.sha256(f"{source_id}|{bool(use_reasoning)}|{EXTRACTOR_VERSION}|{FORMULA_VERSION}".encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id,fingerprint FROM financial_jobs WHERE request_key=?", (key,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise FinancialError("conflict", "This request key belongs to different financial inputs.")
                return old["id"], False
            count = db.execute("SELECT COUNT(*) FROM financial_jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 8:
                raise FinancialError("queue-full", "Financial analysis queue is full.")
            run_id, timestamp = str(uuid.uuid4()), now()
            db.execute("""INSERT INTO financial_jobs
                (id,request_key,fingerprint,source_id,use_reasoning,status,created_at,updated_at,vault_root)
                VALUES (?,?,?,?,?,'queued',?,?,?)""",
                (run_id, key, fingerprint, source_id, int(use_reasoning), timestamp, timestamp, str(self.vault.root)))
        return run_id, True

    def pending(self):
        with self.store.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM financial_jobs WHERE status='queued'")]

    def execute(self, run_id: str):
        with self.store.connect() as db:
            changed = db.execute("UPDATE financial_jobs SET status='running',updated_at=? WHERE id=? AND status='queued'", (now(), run_id)).rowcount
            row = db.execute("SELECT * FROM financial_jobs WHERE id=?", (run_id,)).fetchone()
        if not changed:
            return
        try:
            if row["vault_root"] != str(self.vault.root):
                raise FinancialError("publication-failed", "Restore the original vault configuration before retrying.")
            if row["snapshot"]:
                snapshot, interpretation = json.loads(row["snapshot"]), json.loads(row["interpretation"])
            else:
                source, content = self.filings.source(row["source_id"])
                snapshot = build_snapshot(source, content, self.extractor)
                interpretation = {"status": "skipped", "message": "Optional AI interpretation was not requested; no reasoning allowance was used."}
                if row["use_reasoning"]:
                    if self.analyst is None:
                        interpretation = {"status": "unavailable", "message": "Financial Analysis adapter is unavailable."}
                    else:
                        interpretation = self.analyst.run(snapshot)
                with self.store.connect() as db:
                    for fact in snapshot["facts"]:
                        db.execute("INSERT OR IGNORE INTO financial_facts VALUES (?,?,?)", (fact["id"], row["source_id"], json.dumps(fact)))
                    for metric in snapshot["metrics"]:
                        db.execute("INSERT OR REPLACE INTO financial_metrics VALUES (?,?,?)", (run_id, metric["id"], json.dumps(metric)))
                    db.execute("UPDATE financial_jobs SET snapshot=?,interpretation=?,updated_at=? WHERE id=?",
                               (json.dumps(snapshot), json.dumps(interpretation), now(), run_id))
            note = render_note(snapshot, interpretation)
            path = f"Graph Stock/Financials/{snapshot['source']['symbol']}/{run_id}.md"
            self.vault.publish(path, note)
            status, note_hash = "completed", digest(note)
            with self.store.connect() as db:
                db.execute("UPDATE financial_jobs SET status=?,updated_at=?,note=?,note_path=?,note_hash=? WHERE id=?",
                           (status, now(), note, path, note_hash, run_id))
        except FinancialError as error:
            with self.store.connect() as db:
                db.execute("UPDATE financial_jobs SET status=?,updated_at=?,interpretation=? WHERE id=?",
                           (error.status, now(), json.dumps({"status": error.status, "message": error.message}), run_id))
        except NoteConflict:
            with self.store.connect() as db:
                db.execute("UPDATE financial_jobs SET status='publication-failed',updated_at=? WHERE id=?", (now(), run_id))
        except Exception:
            with self.store.connect() as db:
                db.execute("UPDATE financial_jobs SET status='failed',updated_at=? WHERE id=?", (now(), run_id))

    def retry(self, run_id: str):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM financial_jobs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] in ("queued", "running", "completed", "unsupported"):
                return False
            db.execute("UPDATE financial_jobs SET status='queued',updated_at=? WHERE id=?", (now(), run_id))
            return True

    def get(self, run_id: str):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM financial_jobs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        result = dict(row)
        result.pop("request_key")
        result.pop("fingerprint")
        result.pop("vault_root")
        result["use_reasoning"] = bool(result["use_reasoning"])
        result["snapshot"] = json.loads(result["snapshot"]) if result["snapshot"] else None
        result["interpretation"] = json.loads(result["interpretation"])
        note_content = result.pop("note")
        result["note"] = {
            "path": result.pop("note_path"),
            "sha256": result.pop("note_hash"),
            "available": note_content is not None,
        }
        messages = {
            "queued": "Waiting to extract financial statements.", "running": "Extracting and calculating locally.",
            "completed": "Financial facts and deterministic metrics are saved.",
            "unsupported": result["interpretation"].get("message", "The filing layout is unsupported."),
            "publication-failed": "Metrics are saved, but the note could not be published. Retry publication.",
            "failed": "Financial extraction did not complete. Retry this run.",
        }
        result["message"] = messages.get(result["status"], "Financial run needs attention.")
        return result

    def recent(self):
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM financial_jobs ORDER BY created_at DESC LIMIT 30")]
        return [self.get(run_id) for run_id in ids]

    def read_note(self, run_id: str):
        result = self.get(run_id)
        if not result["note"]["path"]:
            raise KeyError(run_id)
        return self.vault.read(result["note"]["path"])
