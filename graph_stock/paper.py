"""Independent paper book with idempotent daily-session accounting."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from .vault import Vault

SCHEMA_VERSION = "paper-book/v1"
POLICY_VERSION = "independent-paper-book/v1"
POLICY = {
    "initial_cash": "100000", "maximum_positions": 1, "maximum_exposure_percent": "100",
    "sizing": "whole shares using available cash after modeled costs",
    "decision_timing": "after close", "fill_timing": "next processed eligible regular-session open",
    "missing_price": "cancel pending order; record unavailable mark",
    "uncertain_corporate_action": "pause book before affected fill",
    "broker_execution": False,
}
DEGRADATION_POLICY_VERSION = "paper-degradation/v1"
DEGRADATION_POLICY = {
    "version": DEGRADATION_POLICY_VERSION,
    "minimum_observed_sessions": 3,
    "maximum_paper_drawdown_percent": "10",
    "maximum_return_shortfall_percentage_points": "15",
    "degraded_action": "pause-new-entries-and-queue-revalidation",
    "existing_position_action": "continue-risk-reducing-exits",
    "justification": "Small V1 monitoring thresholds; comparison is diagnostic and does not establish live profitability.",
}


class PaperError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now(): return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _money(value): return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _number(value, places="0.000001"):
    return format(Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP).normalize(), "f")


def _render(book):
    state, events = book["state"], book["events"]
    lines = [f"# Paper Book — {book['symbol']}", "", f"Book: `{book['id']}`",
             f"Validation: `{book['validation_id']}`", f"Candidate: `{state['candidate_version']}`",
             f"Policy: `{POLICY_VERSION}`", f"Status: **{state['status']}**", "", "## Account", "",
             f"- Cash: `{state['cash']}`", f"- Quantity: `{state['quantity']}`",
             f"- Last session: `{state['last_session']}`", f"- Pending order: `{state['pending_order']}`",
             f"- Reconciliation: `{state['reconciliation']['status']}`", "", "## Ledger", ""]
    lines += ["- None"] if not events else [
        f"- `{item['sequence']}` {item['session']} **{item['kind']}** — `{json.dumps(item['payload'], sort_keys=True)}`"
        for item in events]
    lines += ["", "## Limits", "", *[f"- **{key}:** `{value}`" for key, value in state["policy"].items()], ""]
    if book.get("monitoring"):
        monitor = book["monitoring"]
        lines += ["", "## Degradation monitoring", "", f"- Status: `{monitor['status']}`",
                  f"- Paper sessions: `{monitor['paper']['sample_sessions']}`",
                  f"- Paper return: `{monitor['paper']['total_return_percent']}%`",
                  f"- Paper maximum drawdown: `{monitor['paper']['max_drawdown_percent']}%`",
                  f"- Validation return: `{monitor['backtest']['total_return_percent']}%`",
                  f"- Reasons: `{monitor['reasons']}`", ""]
    return "\n".join(lines)


class PaperService:
    def __init__(self, store, market_service, validation_service, vault_dir):
        self.store, self.market_service, self.validation_service = store, market_service, validation_service
        self.vault = Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS paper_books (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    symbol TEXT NOT NULL, validation_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_events (
                    event_id TEXT PRIMARY KEY, book_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    session TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(book_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS paper_sessions (
                    book_id TEXT NOT NULL, session TEXT NOT NULL, source_hash TEXT NOT NULL,
                    PRIMARY KEY(book_id, session)
                );
                CREATE TABLE IF NOT EXISTS paper_process_requests (
                    request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, book_id TEXT NOT NULL,
                    result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_monitor_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    book_id TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_revalidation_queue (
                    book_id TEXT PRIMARY KEY, candidate_version TEXT NOT NULL, reason TEXT NOT NULL,
                    status TEXT NOT NULL, source_monitor_id TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
        self.reconcile_all()

    def _events(self, db, book_id):
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in db.execute(
            "SELECT event_id,sequence,session,kind,payload FROM paper_events WHERE book_id=? ORDER BY sequence", (book_id,))]

    def _reconcile(self, db, state, book_id):
        cash, quantity = Decimal(state["policy"]["initial_cash"]), Decimal("0")
        for event in self._events(db, book_id):
            payload = event["payload"]
            if "cash_after" in payload: cash = Decimal(payload["cash_after"])
            if "quantity_after" in payload: quantity = Decimal(payload["quantity_after"])
        matched = cash == Decimal(state["cash"]) and quantity == Decimal(state["quantity"])
        state["reconciliation"] = {"status": "matched" if matched else "mismatch", "checked_at": _now(),
                                   "ledger_cash": _number(cash, "0.01"), "ledger_quantity": _number(quantity)}
        if not matched:
            state["status"], state["pause_reason"] = "paused", "ledger-state-mismatch"
        return state

    def reconcile_all(self):
        with self.store.connect() as db:
            for row in db.execute("SELECT id,state FROM paper_books").fetchall():
                state = self._reconcile(db, json.loads(row["state"]), row["id"])
                db.execute("UPDATE paper_books SET state=?,updated_at=? WHERE id=?", (json.dumps(state, sort_keys=True), _now(), row["id"]))

    def activate(self, symbol, validation_id, request_key):
        symbol = symbol.strip().upper()
        try: validation = self.validation_service.get(validation_id)
        except KeyError: raise PaperError("Validation run not found.", "not-found") from None
        if validation["symbol"] != symbol:
            raise PaperError("Validation belongs to another security.", "conflict")
        if not validation["promotion"]["paper_eligible"] or validation["promotion"]["status"] != "passed":
            raise PaperError("Only a frozen candidate that passed every validation gate can activate.", "not-eligible")
        candidate = validation["search"]["selected_candidate_version"]
        config = validation["search"]["selected_config"]
        fingerprint = _hash({"validation_id": validation_id, "candidate": candidate,
                             "validation_manifest": validation["validation_manifest"]["hash"], "policy": POLICY_VERSION})
        with self.store.connect() as db:
            prior = db.execute("SELECT id,fingerprint FROM paper_books WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint: raise PaperError("Request key already belongs to another paper book.", "conflict")
                return self.get(prior["id"]), False
        market_id = validation["validation_manifest"]["market_run_id"].split(":")[0]
        try: market = self.market_service.get(market_id)
        except KeyError: raise PaperError("Validation market history is unavailable.", "not-found") from None
        lookback = config["lookback_sessions"]
        history = [row["adjusted_close"] for row in sorted(market["adjusted_bars"], key=lambda r: r["session"])
                   if row["status"] == "regular" and row["adjusted_close"] is not None][-lookback:]
        activation_session = validation["windows"]["untouched_oos"]["end"] or market["quality"]["listing_coverage"]["last_session"]
        book_id, timestamp = str(uuid.uuid4()), _now()
        state = {"schema_version": SCHEMA_VERSION, "status": "active", "pause_reason": None,
                 "candidate_version": candidate, "strategy_config": config,
                 "validation_manifest_hash": validation["validation_manifest"]["hash"],
                 "policy_version": POLICY_VERSION, "policy": POLICY, "cash": POLICY["initial_cash"],
                 "quantity": "0", "entry_price": None, "stop_price": None, "target_price": None,
                 "pending_order": None, "last_session": activation_session, "adjusted_closes": history,
                 "new_entries_paused": False, "revalidation": {"status": "not-required", "reasons": []},
                 "reconciliation": {"status": "matched", "checked_at": timestamp,
                                    "ledger_cash": POLICY["initial_cash"], "ledger_quantity": "0"}}
        with self.store.connect() as db:
            try: db.execute("INSERT INTO paper_books VALUES (?,?,?,?,?,?,?,?)", (
                book_id, request_key, fingerprint, symbol, validation_id, timestamp, timestamp, json.dumps(state, sort_keys=True)))
            except sqlite3.IntegrityError: raise PaperError("Paper book activation conflicted with another request.", "conflict") from None
        book = self.get(book_id)
        content = _render(book)
        path = f"Graph Stock/Paper/{symbol}/{book_id}/activation.md"
        self.vault.publish(path, content)
        return book | {"report": {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}}, True

    def _process_session(self, db, book, state, market, session, fail_after_events=None, replay=False):
        raw_rows = [r for r in market["raw_bars"] if r["session"] == session]
        adj_rows = [r for r in market["adjusted_bars"] if r["session"] == session]
        row = raw_rows[0] if len(raw_rows) == 1 else None
        adj = adj_rows[0] if len(adj_rows) == 1 else None
        valid = bool(row and adj and row["status"] == "regular" and adj["adjustment_status"] != "blocked")
        events = []
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0) FROM paper_events WHERE book_id=?", (book["id"],)).fetchone()[0]

        def emit(kind, key, payload):
            nonlocal sequence
            sequence += 1
            event_id = _hash({"book_id": book["id"], "session": session, "kind": kind, "key": key})
            payload = {**payload, "processing_mode": "replay" if replay else "live",
                       "market_run_id": market["id"], "market_source_hash": market["source"]["content_sha256"],
                       "input_scope": "frozen-strategy-market-session"}
            event = {"event_id": event_id, "sequence": sequence, "session": session, "kind": kind, "payload": payload}
            db.execute("INSERT OR IGNORE INTO paper_events VALUES (?,?,?,?,?,?)", (
                event_id, book["id"], sequence, session, kind, json.dumps(payload, sort_keys=True)))
            events.append(event)
            if fail_after_events and len(events) >= fail_after_events:
                raise RuntimeError("injected-paper-session-crash")

        cash, quantity = Decimal(state["cash"]), Decimal(state["quantity"])
        config = state["strategy_config"]
        commission, slippage = Decimal(config["commission_bps"]) / 10000, Decimal(config["slippage_bps"]) / 10000

        actions = [a for a in market["actions"] if a["ex_date"] == session]
        if any(a["adjustment_status"] != "applicable" or a["type"] not in ("split", "bonus", "dividend") for a in actions):
            state["status"], state["pause_reason"] = "paused", "uncertain-corporate-action"
            emit("pause", "uncertain-action", {"reason": state["pause_reason"], "action_ids": [a["action_id"] for a in actions]})
        for action in actions:
            if state["status"] != "active" or action["adjustment_status"] != "applicable": continue
            price_factor = Decimal(action["price_factor"])
            state["adjusted_closes"] = [_number(Decimal(v) * price_factor) for v in state["adjusted_closes"]]
            if action["type"] in ("split", "bonus") and quantity:
                quantity *= Decimal(action["share_factor"])
                state["entry_price"] = _number(_money(Decimal(state["entry_price"]) * price_factor), "0.01")
                state["stop_price"] = _number(_money(Decimal(state["stop_price"]) * price_factor), "0.01")
                state["target_price"] = _number(_money(Decimal(state["target_price"]) * price_factor), "0.01")
            elif action["type"] == "dividend" and quantity:
                credit = _money(quantity * Decimal(str(action["terms"]["cash_per_share"])))
                cash += credit
                state["stop_price"] = _number(_money(Decimal(state["stop_price"]) * price_factor), "0.01")
                state["target_price"] = _number(_money(Decimal(state["target_price"]) * price_factor), "0.01")
                emit("cash", f"dividend:{action['action_id']}", {"reason": "dividend", "amount": _number(credit, "0.01"),
                     "cash_after": _number(cash, "0.01"), "quantity_after": _number(quantity)})
            emit("corporate-action", action["action_id"], {"action_id": action["action_id"], "type": action["type"],
                 "cash_after": _number(cash, "0.01"), "quantity_after": _number(quantity)})

        pending = state["pending_order"]
        if pending and state["status"] == "active":
            if not valid:
                emit("pending-order", f"cancel:{pending['created_session']}", {"side": pending["side"], "status": "cancelled",
                     "reason": "missing-or-stale-price"})
                state["pending_order"] = None
            elif pending["side"] == "buy" and quantity == 0:
                price = _money(Decimal(row["open"]) * (1 + slippage))
                allocation = min(Decimal(config["allocation_percent"]), Decimal(state["policy"]["maximum_exposure_percent"])) / 100
                budget = cash * allocation
                qty = (budget / (price * (1 + commission))).to_integral_value(rounding=ROUND_DOWN)
                if qty <= 0:
                    emit("pending-order", f"reject:{pending['created_session']}", {"side": "buy", "status": "rejected", "reason": "insufficient-cash"})
                else:
                    gross, fee = _money(qty * price), _money(_money(qty * price) * commission)
                    while qty > 0 and gross + fee > cash:
                        qty -= 1; gross, fee = _money(qty * price), _money(_money(qty * price) * commission)
                    cash, quantity = _money(cash - gross - fee), qty
                    state["entry_price"] = _number(price, "0.01")
                    state["stop_price"] = _number(_money(price * (1 - Decimal(config["stop_loss_percent"]) / 100)), "0.01")
                    state["target_price"] = _number(_money(price * (1 + Decimal(config["target_percent"]) / 100)), "0.01")
                    emit("fill", f"buy:{pending['created_session']}", {"side": "buy", "price": _number(price, "0.01"),
                         "quantity": _number(qty), "quantity_after": _number(quantity), "cash_after": _number(cash, "0.01")})
                    emit("fee", f"buy:{pending['created_session']}", {"side": "buy", "amount": _number(fee, "0.01"),
                         "cash_after": _number(cash, "0.01"), "quantity_after": _number(quantity)})
                    emit("cash", f"buy:{pending['created_session']}", {"reason": "buy-fill", "amount": _number(-(gross + fee), "0.01"),
                         "cash_after": _number(cash, "0.01"), "quantity_after": _number(quantity)})
                state["pending_order"] = None
            elif pending["side"] == "sell" and quantity > 0:
                price = _money(Decimal(row["open"]) * (1 - slippage)); qty = quantity
                gross, fee = _money(qty * price), _money(_money(qty * price) * commission)
                cash, quantity = _money(cash + gross - fee), Decimal("0")
                emit("fill", f"sell:{pending['created_session']}", {"side": "sell", "price": _number(price, "0.01"),
                     "quantity": _number(qty), "quantity_after": "0", "cash_after": _number(cash, "0.01")})
                emit("fee", f"sell:{pending['created_session']}", {"side": "sell", "amount": _number(fee, "0.01"),
                     "cash_after": _number(cash, "0.01"), "quantity_after": "0"})
                emit("cash", f"sell:{pending['created_session']}", {"reason": "sell-fill", "amount": _number(gross - fee, "0.01"),
                     "cash_after": _number(cash, "0.01"), "quantity_after": "0"})
                state.update({"pending_order": None, "entry_price": None, "stop_price": None, "target_price": None})

        if valid and quantity and state["status"] == "active":
            opening, low, high = Decimal(row["open"]), Decimal(row["low"]), Decimal(row["high"])
            stop, target = Decimal(state["stop_price"]), Decimal(state["target_price"])
            trigger = None
            if opening <= stop: trigger = (opening, "stop-gap-open")
            elif opening >= target: trigger = (opening, "target-gap-open")
            elif low <= stop and high >= target: trigger = (stop, "stop-before-target-conservative")
            elif low <= stop: trigger = (stop, "stop-touch")
            elif high >= target: trigger = (target, "target-touch")
            if trigger:
                price = _money(trigger[0] * (1 - slippage)); qty = quantity
                gross, fee = _money(qty * price), _money(_money(qty * price) * commission)
                cash, quantity = _money(cash + gross - fee), Decimal("0")
                emit("fill", f"protective:{trigger[1]}", {"side": "sell", "reason": trigger[1], "price": _number(price, "0.01"),
                     "quantity": _number(qty), "cash_after": _number(cash, "0.01"), "quantity_after": "0"})
                emit("fee", f"protective:{trigger[1]}", {"side": "sell", "amount": _number(fee, "0.01"),
                     "cash_after": _number(cash, "0.01"), "quantity_after": "0"})
                emit("cash", f"protective:{trigger[1]}", {"reason": trigger[1], "amount": _number(gross - fee, "0.01"),
                     "cash_after": _number(cash, "0.01"), "quantity_after": "0"})
                state.update({"entry_price": None, "stop_price": None, "target_price": None})

        state["cash"], state["quantity"] = _number(cash, "0.01"), _number(quantity)
        if valid:
            close, lookback = Decimal(adj["adjusted_close"]), config["lookback_sessions"]
            history = [Decimal(v) for v in state["adjusted_closes"]]
            desired = len(history) >= lookback and close > sum(history[-lookback:]) / lookback
            signal = "ENTRY" if quantity == 0 and desired else "EXIT" if quantity > 0 and not desired else "HOLD" if quantity > 0 else "WATCH"
            emit("decision", "close", {"signal": signal, "adjusted_close": _number(close), "history_count": len(history),
                 "history": [_number(value) for value in history[-lookback:]],
                 "candidate_version": state["candidate_version"]})
            if state["status"] == "active" and state["pending_order"] is None and signal in ("ENTRY", "EXIT"):
                if signal == "ENTRY" and state.get("new_entries_paused", False):
                    emit("pending-order", "reject:degradation", {"side": "buy", "status": "rejected",
                         "reason": "paper-degradation-entry-pause"})
                else:
                    state["pending_order"] = {"side": "buy" if signal == "ENTRY" else "sell", "created_session": session}
                    emit("pending-order", f"create:{signal}", {**state["pending_order"], "status": "pending"})
            state["adjusted_closes"] = (history + [close])[-lookback:]
            state["adjusted_closes"] = [_number(v) for v in state["adjusted_closes"]]
            mark = _money(cash + quantity * Decimal(row["close"]))
            emit("mark", "close", {"status": "available", "close": row["close"], "equity": _number(mark, "0.01"),
                 "cash_after": state["cash"], "quantity_after": state["quantity"]})
        else:
            emit("decision", "unavailable", {"signal": "UNAVAILABLE", "reason": "missing-stale-suspended-or-intraday-price"})
            emit("mark", "unavailable", {"status": "unavailable", "cash_after": state["cash"], "quantity_after": state["quantity"]})
        state["last_session"] = session
        state["reconciliation"] = {"status": "matched", "checked_at": _now(),
                                   "ledger_cash": state["cash"], "ledger_quantity": state["quantity"]}
        return state, events

    def process(self, book_id, market_run_id, request_key, fail_after_events=None, replay=False):
        try: market = self.market_service.get(market_run_id)
        except KeyError: raise PaperError("Market data run not found.", "not-found") from None
        fingerprint = _hash({"book_id": book_id, "market_run_id": market_run_id,
                             **({"mode": "replay"} if replay else {})})
        with self.store.connect() as db:
            prior = db.execute("SELECT fingerprint,result FROM paper_process_requests WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint: raise PaperError("Request key already belongs to another paper update.", "conflict")
                return json.loads(prior["result"]), False
        processed, skipped, deferred = 0, 0, 0
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM paper_books WHERE id=?", (book_id,)).fetchone()
            if not row: raise PaperError("Paper book not found.", "not-found")
            book, state = dict(row), json.loads(row["state"])
            if market["symbol"] != book["symbol"]: raise PaperError("Market data belongs to another security.", "conflict")
            for session in sorted(set(market["quality"]["expected_sessions"])):
                if replay and session >= datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat():
                    deferred += 1; continue
                if session <= state["last_session"] or db.execute("SELECT 1 FROM paper_sessions WHERE book_id=? AND session=?", (book_id, session)).fetchone():
                    skipped += 1; continue
                state, _ = self._process_session(db, book, state, market, session, fail_after_events, replay)
                db.execute("INSERT INTO paper_sessions VALUES (?,?,?)", (book_id, session, market["source"]["content_sha256"]))
                processed += 1
            db.execute("UPDATE paper_books SET state=?,updated_at=? WHERE id=?", (json.dumps(state, sort_keys=True), _now(), book_id))
        result = self.get(book_id) | {"process": {"market_run_id": market_run_id, "processed_sessions": processed,
                                                   "skipped_sessions": skipped, "deferred_sessions": deferred,
                                                   "mode": "replay" if replay else "live", "request_key": request_key}}
        content = _render(result)
        path = f"Graph Stock/Paper/{result['symbol']}/{book_id}/{request_key}.md"
        self.vault.publish(path, content)
        result["report"] = {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connect() as db:
            db.execute("INSERT INTO paper_process_requests VALUES (?,?,?,?)", (
                request_key, fingerprint, book_id, json.dumps(result, sort_keys=True)))
        return result, True

    def monitor(self, book_id, request_key):
        try: book = self.get(book_id)
        except KeyError: raise PaperError("Paper book not found.", "not-found") from None
        fingerprint = _hash({"book_id": book_id, "last_session": book["state"]["last_session"],
                             "event_ids": [event["event_id"] for event in book["events"] if event["kind"] != "monitoring"],
                             "policy": DEGRADATION_POLICY})
        with self.store.connect() as db:
            prior = db.execute("SELECT fingerprint,result FROM paper_monitor_runs WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint: raise PaperError("Request key already belongs to another paper monitor.", "conflict")
                return json.loads(prior["result"]), False

        marks = [event["payload"] for event in book["events"]
                 if event["kind"] == "mark" and event["payload"].get("status") == "available"]
        initial = Decimal(book["state"]["policy"]["initial_cash"])
        equities = [Decimal(mark["equity"]) for mark in marks]
        ending, peak, drawdown = (equities[-1] if equities else initial), initial, Decimal("0")
        for equity in equities:
            peak = max(peak, equity)
            if peak: drawdown = max(drawdown, (peak - equity) / peak * 100)
        paper_return = (ending / initial - 1) * 100
        closed_trades = len([event for event in book["events"]
                             if event["kind"] == "fill" and event["payload"].get("side") == "sell"])
        try: validation = self.validation_service.get(book["validation_id"])
        except KeyError: validation = {}
        baseline = (validation.get("oos_result") or {}).get("metrics") or {}
        backtest_return = Decimal(str(baseline["total_return_percent"])) if baseline.get("total_return_percent") is not None else None
        shortfall = backtest_return - paper_return if backtest_return is not None else None
        enough = len(marks) >= DEGRADATION_POLICY["minimum_observed_sessions"]
        reasons = []
        if enough and drawdown > Decimal(DEGRADATION_POLICY["maximum_paper_drawdown_percent"]):
            reasons.append("paper-drawdown-threshold-exceeded")
        if enough and shortfall is not None and shortfall > Decimal(DEGRADATION_POLICY["maximum_return_shortfall_percentage_points"]):
            reasons.append("backtest-return-shortfall-threshold-exceeded")
        status = "degraded" if reasons else "insufficient-sample" if not enough else "insufficient-baseline" if backtest_return is None else "within-thresholds"
        monitor_id, created_at = str(uuid.uuid4()), _now()
        result = {
            "id": monitor_id, "book_id": book_id, "created_at": created_at, "status": status,
            "policy_version": DEGRADATION_POLICY_VERSION, "policy": DEGRADATION_POLICY,
            "paper": {"sample_sessions": len(marks), "closed_trades": closed_trades,
                      "total_return_percent": _number(paper_return), "max_drawdown_percent": _number(drawdown)},
            "backtest": {"sample_sessions": (validation.get("windows") or {}).get("untouched_oos", {}).get("sessions"),
                         "closed_trades": baseline.get("trade_count"),
                         "total_return_percent": baseline.get("total_return_percent"),
                         "max_drawdown_percent": baseline.get("max_drawdown_percent"),
                         "validation_id": book["validation_id"]},
            "return_shortfall_percentage_points": _number(shortfall) if shortfall is not None else None,
            "reasons": reasons,
            "action": DEGRADATION_POLICY["degraded_action"] if reasons else "observe",
            "cancelled_pending_entry": False,
        }
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM paper_books WHERE id=?", (book_id,)).fetchone()
            state = json.loads(row["state"])
            if reasons:
                state["new_entries_paused"] = True
                state["revalidation"] = {"status": "queued", "reasons": reasons, "source_monitor_id": monitor_id}
                if state.get("pending_order", {}).get("side") == "buy":
                    state["pending_order"] = None
                    result["cancelled_pending_entry"] = True
                    sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM paper_events WHERE book_id=?", (book_id,)).fetchone()[0]
                    db.execute("INSERT INTO paper_events VALUES (?,?,?,?,?,?)", (
                        _hash({"book_id": book_id, "monitor_id": monitor_id, "kind": "monitoring"}), book_id,
                        sequence, state["last_session"], "monitoring", json.dumps({
                            "action": "cancel-pending-entry", "reason": "paper-degradation-entry-pause",
                            "monitor_id": monitor_id, "policy_version": DEGRADATION_POLICY_VERSION
                        }, sort_keys=True)))
                db.execute("INSERT OR IGNORE INTO paper_revalidation_queue VALUES (?,?,?,?,?,?)", (
                    book_id, state["candidate_version"], ",".join(reasons), "queued", monitor_id, created_at))
            else:
                state.setdefault("new_entries_paused", False)
                state.setdefault("revalidation", {"status": "not-required", "reasons": []})
            db.execute("UPDATE paper_books SET state=?,updated_at=? WHERE id=?", (json.dumps(state, sort_keys=True), created_at, book_id))
            db.execute("INSERT INTO paper_monitor_runs VALUES (?,?,?,?,?,?)", (
                monitor_id, request_key, fingerprint, book_id, created_at, json.dumps(result, sort_keys=True)))
        return result, True

    def catch_up(self, book_id, market_run_id, request_key):
        book, created = self.process(book_id, market_run_id, request_key, replay=True)
        monitoring, monitor_created = self.monitor(book_id, request_key)
        return {"book": self.get(book_id), "catch_up": book["process"], "monitoring": monitoring}, created or monitor_created

    def monitoring(self, book_id):
        try: self.get(book_id)
        except KeyError: raise PaperError("Paper book not found.", "not-found") from None
        with self.store.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT result FROM paper_monitor_runs WHERE book_id=? ORDER BY created_at DESC", (book_id,))]

    def get(self, book_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM paper_books WHERE id=?", (str(book_id),)).fetchone()
            if not row: raise KeyError(book_id)
            result = dict(row); result["state"] = json.loads(result["state"]); result["events"] = self._events(db, book_id)
            result["state"].setdefault("new_entries_paused", False)
            result["state"].setdefault("revalidation", {"status": "not-required", "reasons": []})
            monitor = db.execute("SELECT result FROM paper_monitor_runs WHERE book_id=? ORDER BY created_at DESC LIMIT 1", (book_id,)).fetchone()
            result["monitoring"] = json.loads(monitor[0]) if monitor else None
            result.pop("request_key"); result.pop("fingerprint")
            return result

    def recent(self):
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM paper_books ORDER BY created_at DESC LIMIT 30")]
        return [self.get(book_id) for book_id in ids]

    def read_report(self, book_id): return _render(self.get(book_id))
