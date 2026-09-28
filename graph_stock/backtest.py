"""Deterministic daily-bar backtest with an auditable cash and trade ledger."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from .vault import Vault

SCHEMA_VERSION = "backtest/v1"
ENGINE_VERSION = "graph-stock-daily-event-loop/v1"
STRATEGY_VERSION = "trend-following-close-above-sma/v1"
COST_POLICY_VERSION = "explicit-bps-assumption/v1"
DEFAULT_CONFIG = {
    "family": "trend-following",
    "lookback_sessions": 3,
    "initial_cash": "100000",
    "allocation_percent": "100",
    "stop_loss_percent": "5",
    "target_percent": "10",
    "commission_bps": "10",
    "slippage_bps": "5",
    "cost_effective_from": "2000-01-01",
    "cost_source": "Versioned simulation assumption; replace with dated broker and statutory rates before validation.",
}


class BacktestError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _decimal(value, label, *, zero=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BacktestError(f"{label} must be a decimal number.") from None
    if not result.is_finite() or result < 0 or (not zero and result == 0):
        raise BacktestError(f"{label} must be {'non-negative' if zero else 'positive'}.")
    return result


def _money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _number(value, places="0.000001"):
    if value is None:
        return None
    return format(Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP).normalize(), "f")


def _validated_config(config):
    merged = {**DEFAULT_CONFIG, **(config or {})}
    if set(merged) != set(DEFAULT_CONFIG) or merged["family"] != "trend-following":
        raise BacktestError("Only the approved trend-following template is supported in GS-13.")
    if isinstance(merged["lookback_sessions"], bool) or not isinstance(merged["lookback_sessions"], int) or not 1 <= merged["lookback_sessions"] <= 252:
        raise BacktestError("Lookback sessions must be an integer from 1 to 252.")
    for name in ("initial_cash", "allocation_percent", "stop_loss_percent", "target_percent"):
        merged[name] = _number(_decimal(merged[name], name))
    for name in ("commission_bps", "slippage_bps"):
        merged[name] = _number(_decimal(merged[name], name, zero=True))
    if Decimal(merged["allocation_percent"]) > 100 or Decimal(merged["stop_loss_percent"]) >= 100:
        raise BacktestError("Allocation cannot exceed 100% and stop loss must be below 100%.")
    try:
        datetime.fromisoformat(merged["cost_effective_from"])
    except (TypeError, ValueError):
        raise BacktestError("Cost policy effective date must be an ISO date.") from None
    if not isinstance(merged["cost_source"], str) or not merged["cost_source"].strip():
        raise BacktestError("Cost policy source is required.")
    return merged


def _event(kind, session, cash, quantity, **details):
    return {"sequence": None, "type": kind, "session": session, "cash": _number(cash, "0.01"),
            "quantity": _number(quantity), **details}


def _metrics(initial, equity_curve, trades, exposed, eligible, benchmark):
    ending = Decimal(equity_curve[-1]["equity"]) if equity_curve else initial
    peak, drawdown = initial, Decimal("0")
    returns, prior = [], initial
    for item in equity_curve:
        value = Decimal(item["equity"])
        peak = max(peak, value)
        if peak:
            drawdown = max(drawdown, (peak - value) / peak)
        if prior:
            returns.append(float(value / prior - 1))
        prior = value
    pnl = [Decimal(item["net_pnl"]) for item in trades]
    wins, losses = [v for v in pnl if v > 0], [v for v in pnl if v < 0]
    sharpe = None
    if len(returns) >= 2 and statistics.pstdev(returns) > 0:
        sharpe = Decimal(str(statistics.mean(returns) / statistics.pstdev(returns) * math.sqrt(252)))
    benchmark_return = benchmark.get("return_percent")
    total_return = (ending / initial - 1) * 100
    return {
        "starting_cash": _number(initial, "0.01"), "ending_equity": _number(ending, "0.01"),
        "total_return_percent": _number(total_return), "max_drawdown_percent": _number(drawdown * 100),
        "trade_count": len(trades),
        "win_rate_percent": _number(Decimal(len(wins)) / Decimal(len(trades)) * 100) if trades else None,
        "profit_factor": _number(sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0")))) if losses else None,
        "profit_factor_reason": None if losses else "undefined-without-losing-trades",
        "expectancy": _number(sum(pnl, Decimal("0")) / len(trades), "0.01") if trades else None,
        "exposure_percent": _number(Decimal(exposed) / Decimal(eligible) * 100) if eligible else None,
        "annualized_sharpe": _number(sharpe) if sharpe is not None else None,
        "sharpe_reason": None if sharpe is not None else "insufficient-or-zero-variance-daily-returns",
        "benchmark_return_percent": benchmark_return,
        "excess_return_percent": _number(total_return - Decimal(benchmark_return)) if benchmark_return is not None else None,
    }


def simulate_daily_trend(symbol, market, config=None):
    """Run after-close decisions and next-expected-session execution on raw OHLC."""
    config = _validated_config(config)
    raw = {row["session"]: row for row in market["raw_bars"] if row["session"] not in market["quality"]["duplicate_sessions"]}
    adjusted = {row["session"]: row for row in market["adjusted_bars"] if row["session"] not in market["quality"]["duplicate_sessions"]}
    expected = sorted(set(market["quality"]["expected_sessions"]))
    if not expected:
        raise BacktestError("Expected trading sessions are required.")
    unsupported = [a for a in market["actions"] if a["adjustment_status"] != "applicable" or a["type"] not in ("split", "bonus", "dividend")]
    if unsupported:
        raise BacktestError("The selected market run contains unsupported or incomplete corporate actions.", "coverage")

    initial = _decimal(config["initial_cash"], "initial cash")
    allocation = Decimal(config["allocation_percent"]) / 100
    commission = Decimal(config["commission_bps"]) / 10000
    slippage = Decimal(config["slippage_bps"]) / 10000
    stop_pct = Decimal(config["stop_loss_percent"]) / 100
    target_pct = Decimal(config["target_percent"]) / 100
    lookback = config["lookback_sessions"]
    cash, quantity = initial, Decimal("0")
    entry = None
    stop = target = None
    position_dividends = Decimal("0")
    pending = None
    ledger, trades, equity_curve, adjusted_history = [], [], [], []
    exposed = eligible = 0

    def add(kind, session, **details):
        item = _event(kind, session, cash, quantity, **details)
        item["sequence"] = len(ledger) + 1
        ledger.append(item)

    def buy(session, base_price, reason, signal_session):
        nonlocal cash, quantity, entry, stop, target, position_dividends
        price = _money(base_price * (1 + slippage))
        budget = cash * allocation
        qty = (budget / (price * (1 + commission))).to_integral_value(rounding=ROUND_DOWN)
        while qty > 0:
            gross, cost = _money(qty * price), _money(_money(qty * price) * commission)
            if gross + cost <= cash:
                break
            qty -= 1
        if qty <= 0:
            add("order-cancelled", session, side="buy", reason="insufficient-cash", signal_session=signal_session)
            return
        cash = _money(cash - gross - cost)
        quantity, entry = qty, {"session": session, "signal_session": signal_session, "price": price,
                                "quantity": qty, "gross": gross, "cost": cost, "reason": reason}
        stop, target = _money(price * (1 - stop_pct)), _money(price * (1 + target_pct))
        position_dividends = Decimal("0")
        add("fill", session, side="buy", reason=reason, signal_session=signal_session,
            price=_number(price, "0.01"), gross=_number(gross, "0.01"), cost=_number(cost, "0.01"),
            stop_price=_number(stop, "0.01"), target_price=_number(target, "0.01"))

    def sell(session, base_price, reason, ambiguity=False):
        nonlocal cash, quantity, entry, stop, target, position_dividends
        price = _money(base_price * (1 - slippage))
        qty = quantity
        gross, cost = _money(qty * price), _money(_money(qty * price) * commission)
        cash = _money(cash + gross - cost)
        net_pnl = gross - cost + position_dividends - entry["gross"] - entry["cost"]
        trade = {
            "trade_id": f"trade-{len(trades) + 1}", "entry_session": entry["session"],
            "entry_signal_session": entry["signal_session"], "entry_price": _number(entry["price"], "0.01"),
            "exit_session": session, "exit_price": _number(price, "0.01"), "quantity": _number(qty),
            "entry_cost": _number(entry["cost"], "0.01"), "exit_cost": _number(cost, "0.01"),
            "dividends": _number(position_dividends, "0.01"), "exit_reason": reason,
            "ambiguity": ambiguity, "net_pnl": _number(net_pnl, "0.01"),
            "return_percent": _number(net_pnl / (entry["gross"] + entry["cost"]) * 100),
            "cash_after_exit": _number(cash, "0.01"),
        }
        trades.append(trade)
        quantity = Decimal("0")
        add("fill", session, side="sell", reason=reason, price=_number(price, "0.01"),
            gross=_number(gross, "0.01"), cost=_number(cost, "0.01"), trade_id=trade["trade_id"], ambiguity=ambiguity)
        entry = stop = target = None
        position_dividends = Decimal("0")

    actions_by_day = {}
    for action in market["actions"]:
        actions_by_day.setdefault(action["ex_date"], []).append(action)

    for index, session in enumerate(expected):
        row, adj = raw.get(session), adjusted.get(session)
        valid = bool(row and adj and row["status"] == "regular" and adj["adjustment_status"] != "blocked")
        if valid:
            eligible += 1

        # Holders entering on the ex-date do not receive that action, so actions precede orders.
        for action in actions_by_day.get(session, []):
            if quantity <= 0:
                continue
            if action["type"] in ("split", "bonus"):
                factor = Decimal(action["share_factor"])
                quantity *= factor
                price_factor = Decimal(action["price_factor"])
                stop, target = _money(stop * price_factor), _money(target * price_factor)
                add("corporate-action", session, action_type=action["type"], action_id=action["action_id"],
                    share_factor=_number(factor), stop_price=_number(stop, "0.01"), target_price=_number(target, "0.01"))
            elif action["type"] == "dividend":
                credit = _money(quantity * Decimal(str(action["terms"]["cash_per_share"])))
                cash, position_dividends = _money(cash + credit), position_dividends + credit
                price_factor = Decimal(action["price_factor"])
                stop, target = _money(stop * price_factor), _money(target * price_factor)
                add("corporate-action", session, action_type="dividend", action_id=action["action_id"],
                    cash_credit=_number(credit, "0.01"), stop_price=_number(stop, "0.01"), target_price=_number(target, "0.01"))

        if pending and pending["due_session"] == session:
            if not valid:
                add("order-cancelled", session, side=pending["side"],
                    reason="missing-bar" if row is None else "suspended-or-unusable-bar", signal_session=pending["signal_session"])
            elif pending["side"] == "buy" and quantity == 0:
                buy(session, Decimal(row["open"]), "next-session-open", pending["signal_session"])
            elif pending["side"] == "sell" and quantity > 0:
                sell(session, Decimal(row["open"]), "signal-next-session-open")
            pending = None

        had_position = quantity > 0
        if valid and quantity > 0:
            opening, low, high = Decimal(row["open"]), Decimal(row["low"]), Decimal(row["high"])
            if opening <= stop:
                sell(session, opening, "stop-gap-open")
            elif opening >= target:
                sell(session, opening, "target-gap-open")
            elif low <= stop and high >= target:
                sell(session, stop, "stop-before-target-conservative", True)
            elif low <= stop:
                sell(session, stop, "stop-touch")
            elif high >= target:
                sell(session, target, "target-touch")

        if had_position or quantity > 0:
            exposed += 1
        close = Decimal(row["close"]) if valid else None
        prior_equity = Decimal(equity_curve[-1]["equity"]) if equity_curve else initial
        equity = _money(cash + quantity * close) if close is not None else prior_equity
        equity_curve.append({"session": session, "equity": _number(equity, "0.01"),
                             "status": "marked" if close is not None else "carried-missing-or-unusable"})

        if valid:
            adjusted_close = Decimal(adj["adjusted_close"])
            desired_long = len(adjusted_history) >= lookback and adjusted_close > sum(adjusted_history[-lookback:]) / lookback
            adjusted_history.append(adjusted_close)
            next_session = expected[index + 1] if index + 1 < len(expected) else None
            if next_session and pending is None:
                if quantity == 0 and desired_long:
                    pending = {"side": "buy", "signal_session": session, "due_session": next_session}
                    add("signal", session, side="buy", reason="adjusted-close-above-prior-sma",
                        due_session=next_session, lookback_sessions=lookback)
                elif quantity > 0 and not desired_long:
                    pending = {"side": "sell", "signal_session": session, "due_session": next_session}
                    add("signal", session, side="sell", reason="adjusted-close-not-above-prior-sma",
                        due_session=next_session, lookback_sessions=lookback)

    benchmark = {"symbol": market["benchmark"]["symbol"], "basis": "close-to-close price return", "return_percent": None,
                 "reason": None}
    if any(action["type"] == "dividend" for action in market["actions"]):
        benchmark["reason"] = "security-includes-dividend-cash-but-benchmark-total-return-series-is-unavailable"
    else:
        bench = {row["session"]: row for row in market["benchmark"]["bars"] if row["status"] == "regular"}
        common = [day for day in expected if day in bench]
        if len(common) >= 2:
            first, last = Decimal(bench[common[0]]["close"]), Decimal(bench[common[-1]]["close"])
            benchmark.update({"first_session": common[0], "last_session": common[-1],
                              "return_percent": _number((last / first - 1) * 100)})
        else:
            benchmark["reason"] = "fewer-than-two-comparable-benchmark-bars"

    manifest = {
        "market_run_id": market["id"], "market_source_id": market["source"]["source_id"],
        "market_source_hash": market["source"]["content_sha256"], "adjustment_version": market["adjustment_version"],
        "strategy_version": STRATEGY_VERSION, "engine_version": ENGINE_VERSION,
        "cost_policy_version": COST_POLICY_VERSION, "config": config,
        "sessions": expected, "bars": market["raw_bars"], "actions": market["actions"],
        "benchmark": market["benchmark"],
    }
    ending_quantity = quantity
    result = {
        "schema_version": SCHEMA_VERSION, "engine": {
            "version": ENGINE_VERSION, "implementation": "in-project deterministic event loop",
            "license": "No third-party simulation engine or license is introduced; the repository currently declares no distribution license.",
            "vectorbt": "Not selected for GS-13: its vectorized execution does not define this project's ambiguity and ledger policies.",
        },
        "strategy": {"version": STRATEGY_VERSION, "family": "trend-following",
                     "rule": "After each close, go long when adjusted close is above the prior N eligible-session SMA; otherwise exit.",
                     "parameter_search_history": [], "config": config},
        "timing_policy": "decide after close; fill only at the immediately next expected eligible session open",
        "ambiguity_policy": "gap fills use the open; if stop and target both trade intraday, the stop is applied first",
        "missing_bar_policy": "an order due on a missing, suspended or unusable bar is cancelled and never shifted forward",
        "corporate_action_policy": "raw execution; split/bonus changes shares and anchors; dividends credit cash; adjusted closes drive signals",
        "symbol": symbol, "period": {"start": expected[0], "end": expected[-1]},
        "universe": market["quality"]["listing_coverage"] | {
            "scope": "one currently known NSE security",
            "limitation": "No NSE-wide, delisted-security or survivorship-safe claim is made.",
        },
        "data_manifest": {"hash": _hash(manifest), **manifest}, "ledger": ledger, "trades": trades,
        "equity_curve": equity_curve, "ending_position": {"quantity": _number(ending_quantity),
            "last_mark": equity_curve[-1]["equity"] if equity_curve else _number(initial, "0.01")},
        "benchmark": benchmark,
    }
    result["metrics"] = _metrics(initial, equity_curve, trades, exposed, eligible, benchmark)
    return result


def _render(result):
    m = result["metrics"]
    lines = [f"# Backtest — {result['symbol']}", "", f"Run: `{result['id']}`",
             f"Strategy: `{result['strategy']['version']}`", f"Engine: `{result['engine']['version']}`",
             f"Data manifest: `{result['data_manifest']['hash']}`", "", "## Assumptions", "",
             f"- {result['timing_policy']}", f"- {result['ambiguity_policy']}", f"- {result['missing_bar_policy']}",
             f"- {result['corporate_action_policy']}", f"- Cost source: {result['strategy']['config']['cost_source']}",
             f"- Universe: {result['universe']['limitation']}", "", "## Performance", "",
             f"- Return: `{m['total_return_percent']}%`", f"- Ending equity: `{m['ending_equity']}`",
             f"- Maximum drawdown: `{m['max_drawdown_percent']}%`", f"- Trades: `{m['trade_count']}`",
             f"- Win rate: `{m['win_rate_percent']}`", f"- Profit factor: `{m['profit_factor']}`",
             f"- Expectancy: `{m['expectancy']}`", f"- Exposure: `{m['exposure_percent']}%`",
             f"- Annualized Sharpe: `{m['annualized_sharpe']}`", f"- Benchmark return: `{m['benchmark_return_percent']}`",
             f"- Excess return: `{m['excess_return_percent']}`", "", "## Trades", ""]
    lines += ["- None"] if not result["trades"] else [
        f"- **{t['trade_id']}** {t['entry_session']} → {t['exit_session']}; {t['quantity']} shares; net `{t['net_pnl']}`; exit `{t['exit_reason']}`"
        for t in result["trades"]]
    lines += ["", "## Cash and position ledger", ""]
    lines += ["- None"] if not result["ledger"] else [
        f"- `{e['sequence']}` {e['session']} **{e['type']}** — cash `{e['cash']}`; quantity `{e['quantity']}`; {e.get('reason', e.get('action_type', ''))}"
        for e in result["ledger"]]
    lines += ["", "## Engine and license", "", result["engine"]["license"], "", result["engine"]["vectorbt"], ""]
    return "\n".join(lines)


class BacktestService:
    def __init__(self, store, market_service, vault_dir):
        self.store, self.market_service, self.vault = store, market_service, Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS backtests (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    symbol TEXT NOT NULL, market_run_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    result TEXT NOT NULL
                );
            """)

    def submit(self, symbol, market_run_id, request_key):
        symbol = symbol.strip().upper()
        try:
            market = self.market_service.get(market_run_id)
        except KeyError:
            raise BacktestError("Market data run not found.", "not-found") from None
        if market["symbol"] != symbol:
            raise BacktestError("Market data run belongs to another security.", "conflict")
        fingerprint = _hash({"symbol": symbol, "market_run_id": market_run_id,
                             "strategy": STRATEGY_VERSION, "config": DEFAULT_CONFIG})
        with self.store.connect() as db:
            prior = db.execute("SELECT id,fingerprint FROM backtests WHERE request_key=?", (request_key,)).fetchone()
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise BacktestError("Request key already belongs to another backtest.", "conflict")
            return self.get(prior["id"]), False
        result = simulate_daily_trend(symbol, market)
        result.update({"id": str(uuid.uuid4()), "created_at": _now(), "report": None})
        content = _render(result)
        path = f"Graph Stock/Backtests/{symbol}/{result['id']}.md"
        self.vault.publish(path, content)
        result["report"] = {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connect() as db:
            try:
                db.execute("INSERT INTO backtests VALUES (?,?,?,?,?,?,?)", (
                    result["id"], request_key, fingerprint, symbol, market_run_id,
                    result["created_at"], json.dumps(result, sort_keys=True)))
            except sqlite3.IntegrityError:
                raise BacktestError("Request key already belongs to another backtest.", "conflict") from None
        return result, True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT result FROM backtests WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["result"])

    def recent(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM backtests ORDER BY created_at DESC LIMIT 30").fetchall()
        return [json.loads(row["result"]) for row in rows]

    def read_report(self, run_id):
        return self.vault.read(self.get(run_id)["report"]["path"])
