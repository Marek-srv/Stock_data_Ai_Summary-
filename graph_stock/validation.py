"""Bounded strategy exploration and all-gates-must-pass validation."""

from __future__ import annotations

import hashlib
import itertools
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from .backtest import BacktestError, DEFAULT_CONFIG, simulate_daily_trend
from .vault import Vault

SCHEMA_VERSION = "strategy-validation/v1"
REGISTRY_VERSION = "approved-strategy-families/v1"
POLICY_VERSION = "candidate-acceptance/v1"
SEARCH_VERSION = "bounded-grid/v1"
FAMILY_REGISTRY = {
    "momentum": {"required_features": ["market"], "parameters": {"lookback_sessions": [20, 60, 120], "minimum_return_percent": [0, 5]}},
    "breakout": {"required_features": ["market"], "parameters": {"lookback_sessions": [20, 55], "buffer_percent": [0, 1]}},
    "pullback": {"required_features": ["market"], "parameters": {"trend_sessions": [50, 200], "pullback_percent": [3, 8]}},
    "relative-strength": {"required_features": ["market", "benchmark"], "parameters": {"lookback_sessions": [20, 60]}},
    "volume-expansion": {"required_features": ["market"], "parameters": {"volume_sessions": [20, 50], "multiplier": [1.5, 2]}},
    "earnings-momentum": {"required_features": ["market", "financial"], "parameters": {"quarters": [1, 2], "minimum_growth_percent": [5, 10]}},
    "institutional-accumulation": {"required_features": ["market", "ownership"], "parameters": {"periods": [2, 3], "minimum_change_percent": [0.25, 0.5]}},
    "trend-following": {"required_features": ["market"], "parameters": {"lookback_sessions": [2, 3, 5], "stop_loss_percent": [5, 8], "target_percent": [10, 15]}},
}
POLICY = {
    "minimum_total_sessions": 40,
    "minimum_oos_sessions": 10,
    "minimum_oos_closed_trades": 1,
    "maximum_oos_drawdown_percent": "35",
    "cost_stress_multiplier": "2",
    "minimum_profitable_sensitivity_fraction": "0.5",
    "minimum_profitable_walk_forward_fraction": "0.5",
    "maximum_experiments": 6,
    "split": {"train": "50%", "tuning": "25%", "untouched_oos": "25%"},
    "justification": "Small proof threshold for accounting and leakage controls; it is not evidence of production robustness or NSE-wide validity.",
}


class ValidationError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _number(value):
    return format(Decimal(str(value)).quantize(Decimal("0.000001")).normalize(), "f")


def _subset(market, sessions, name):
    chosen = set(sessions)
    raw = [row for row in market["raw_bars"] if row["session"] in chosen]
    adjusted = [row for row in market["adjusted_bars"] if row["session"] in chosen]
    benchmark = [row for row in market["benchmark"]["bars"] if row["session"] in chosen]
    actions = [row for row in market["actions"] if row["ex_date"] in chosen]
    result = {**market, "id": f"{market['id']}:{name}", "raw_bars": raw, "adjusted_bars": adjusted,
              "actions": actions, "benchmark": {**market["benchmark"], "bars": benchmark},
              "quality": {**market["quality"], "expected_sessions": list(sessions),
                          "duplicate_sessions": [day for day in market["quality"]["duplicate_sessions"] if day in chosen],
                          "listing_coverage": {**market["quality"]["listing_coverage"], "bar_count": len(raw),
                                               "first_session": sessions[0] if sessions else None,
                                               "last_session": sessions[-1] if sessions else None}}}
    return result


def _experiment_config(lookback, stop, target):
    return {**DEFAULT_CONFIG, "lookback_sessions": lookback, "stop_loss_percent": str(stop), "target_percent": str(target)}


def _run(simulator, symbol, market, config):
    try:
        return simulator(symbol, market, config), None
    except BacktestError as error:
        return None, error.message


def _metric(result, name):
    if not result:
        return None
    value = result["metrics"].get(name)
    return Decimal(value) if value is not None else None


def validate_market(symbol, market, available_features=None, simulator=simulate_daily_trend):
    available = set(available_features or ["market", "benchmark"])
    registry = {}
    for family, spec in FAMILY_REGISTRY.items():
        missing = sorted(set(spec["required_features"]) - available)
        implemented = family == "trend-following"
        registry[family] = {**spec, "eligible": not missing and implemented,
                            "missing_features": missing,
                            "reason": ("missing-required-features" if missing else
                                       None if implemented else "simulation-template-not-implemented")}

    sessions = sorted(set(market["quality"]["expected_sessions"]))
    n = len(sessions)
    train_end, tuning_end = n // 2, (n * 3) // 4
    train, tuning, oos = sessions[:train_end], sessions[train_end:tuning_end], sessions[tuning_end:]
    windows = {"train": train, "tuning": tuning, "untouched_oos": oos}
    window_manifest = {name: {"start": rows[0] if rows else None, "end": rows[-1] if rows else None,
                              "sessions": len(rows), "hash": _hash(rows)} for name, rows in windows.items()}

    configs = []
    for lookback, (stop, target) in itertools.product([2, 3, 5], [(5, 10), (8, 15)]):
        configs.append(_experiment_config(lookback, stop, target))
    configs = configs[:POLICY["maximum_experiments"]]
    experiments = []
    pre_oos = train + tuning
    for index, config in enumerate(configs, 1):
        train_result, train_error = _run(simulator, symbol, _subset(market, train, "train"), config)
        tuning_result, tuning_error = _run(simulator, symbol, _subset(market, tuning, "tuning"), config)
        score = _metric(tuning_result, "total_return_percent")
        experiments.append({
            "experiment_id": f"experiment-{index}", "family": "trend-following", "config": config,
            "candidate_version": f"trend-following/{_hash(config)[:16]}",
            "train_window_hash": window_manifest["train"]["hash"],
            "tuning_window_hash": window_manifest["tuning"]["hash"],
            "holdout_accessed": False, "selection_score": _number(score) if score is not None else None,
            "train_metrics": train_result["metrics"] if train_result else None,
            "tuning_metrics": tuning_result["metrics"] if tuning_result else None,
            "error": train_error or tuning_error,
        })
    selectable = [item for item in experiments if item["selection_score"] is not None]
    selected = max(selectable, key=lambda item: (Decimal(item["selection_score"]), item["candidate_version"])) if selectable else None

    oos_result = stress_result = None
    sensitivities, walk_forward = [], []
    if selected and oos:
        oos_result, _ = _run(simulator, symbol, _subset(market, oos, "untouched-oos"), selected["config"])
        stress = dict(selected["config"])
        multiplier = Decimal(POLICY["cost_stress_multiplier"])
        stress["commission_bps"] = _number(Decimal(stress["commission_bps"]) * multiplier)
        stress["slippage_bps"] = _number(Decimal(stress["slippage_bps"]) * multiplier)
        stress_result, _ = _run(simulator, symbol, _subset(market, oos, "cost-stress-oos"), stress)
        for lookback in FAMILY_REGISTRY["trend-following"]["parameters"]["lookback_sessions"]:
            neighbor = {**selected["config"], "lookback_sessions": lookback}
            result, error = _run(simulator, symbol, _subset(market, oos, f"sensitivity-{lookback}"), neighbor)
            sensitivities.append({"lookback_sessions": lookback,
                                  "return_percent": _number(_metric(result, "total_return_percent")) if result else None,
                                  "error": error})
        midpoint = max(1, len(pre_oos) // 2)
        for index, rows in enumerate((pre_oos[:midpoint], pre_oos[midpoint:]), 1):
            result, error = _run(simulator, symbol, _subset(market, rows, f"walk-forward-{index}"), selected["config"])
            walk_forward.append({"fold": index, "start": rows[0] if rows else None, "end": rows[-1] if rows else None,
                                 "return_percent": _number(_metric(result, "total_return_percent")) if result else None,
                                 "error": error})

    oos_return = _metric(oos_result, "total_return_percent")
    oos_drawdown = _metric(oos_result, "max_drawdown_percent")
    oos_trades = oos_result["metrics"]["trade_count"] if oos_result else 0
    excess = _metric(oos_result, "excess_return_percent")
    stress_return = _metric(stress_result, "total_return_percent")
    sensitive_values = [Decimal(item["return_percent"]) for item in sensitivities if item["return_percent"] is not None]
    walk_values = [Decimal(item["return_percent"]) for item in walk_forward if item["return_percent"] is not None]
    sensitivity_fraction = Decimal(sum(value >= 0 for value in sensitive_values)) / len(sensitive_values) if sensitive_values else None
    walk_fraction = Decimal(sum(value >= 0 for value in walk_values)) / len(walk_values) if walk_values else None
    checks = [
        ("required-feature-support", registry["trend-following"]["eligible"], "market history supports the selected family"),
        ("minimum-sample", n >= POLICY["minimum_total_sessions"] and len(oos) >= POLICY["minimum_oos_sessions"],
         f"requires {POLICY['minimum_total_sessions']} total and {POLICY['minimum_oos_sessions']} untouched sessions"),
        ("holdout-isolation", bool(oos) and all(not item["holdout_accessed"] for item in experiments),
         "candidate selection used train/tuning records only"),
        ("search-budget", len(experiments) <= POLICY["maximum_experiments"], "bounded allowlisted grid"),
        ("minimum-trades", oos_trades >= POLICY["minimum_oos_closed_trades"], "untouched closed-trade minimum"),
        ("positive-oos-return", oos_return is not None and oos_return > 0, "untouched return must be positive"),
        ("benchmark", excess is not None and excess >= 0, "untouched return must match or exceed benchmark"),
        ("drawdown", oos_drawdown is not None and oos_drawdown <= Decimal(POLICY["maximum_oos_drawdown_percent"]),
         "untouched maximum drawdown limit"),
        ("cost-stress", stress_return is not None and stress_return > 0, "return must remain positive at doubled modeled costs"),
        ("parameter-sensitivity", sensitivity_fraction is not None and sensitivity_fraction >= Decimal(POLICY["minimum_profitable_sensitivity_fraction"]),
         "at least half of allowlisted neighboring lookbacks must be non-negative"),
        ("walk-forward", walk_fraction is not None and walk_fraction >= Decimal(POLICY["minimum_profitable_walk_forward_fraction"]),
         "at least half of two pre-holdout chronological folds must be non-negative"),
    ]
    gates = [{"name": name, "status": "pass" if passed else "fail", "detail": detail} for name, passed, detail in checks]
    passed = bool(selected) and all(item["status"] == "pass" for item in gates)
    status = "passed" if passed else "insufficient-evidence" if n < POLICY["minimum_total_sessions"] else "rejected"
    promotion = {"status": status, "paper_eligible": passed,
                 "reason": "all-required-gates-passed" if passed else "one-or-more-required-gates-did-not-pass",
                 "invalidated_by_rule_change": True,
                 "scope": "single-security validation only; no NSE-wide performance claim"}
    manifest = {"market_run_id": market["id"], "market_source_hash": market["source"]["content_sha256"],
                "registry_version": REGISTRY_VERSION, "policy_version": POLICY_VERSION,
                "search_version": SEARCH_VERSION, "policy": POLICY, "windows": window_manifest,
                "candidate_versions": [item["candidate_version"] for item in experiments]}
    return {"schema_version": SCHEMA_VERSION, "symbol": symbol, "registry_version": REGISTRY_VERSION,
            "family_registry": registry, "policy_version": POLICY_VERSION, "policy": POLICY,
            "search": {"version": SEARCH_VERSION, "budget": POLICY["maximum_experiments"],
                       "used": len(experiments), "breadth": len(configs), "experiments": experiments,
                       "selected_candidate_version": selected["candidate_version"] if selected else None,
                       "selected_config": selected["config"] if selected else None,
                       "selection_basis": "highest tuning return; untouched OOS was inaccessible during selection"},
            "windows": window_manifest, "oos_result": oos_result, "cost_stress_result": stress_result,
            "sensitivity": sensitivities, "walk_forward": walk_forward, "gates": gates,
            "promotion": promotion, "validation_manifest": {"hash": _hash(manifest), **manifest}}


def _render(result):
    lines = [f"# Strategy Validation — {result['symbol']}", "", f"Run: `{result['id']}`",
             f"Policy: `{result['policy_version']}`", f"Manifest: `{result['validation_manifest']['hash']}`",
             f"Outcome: **{result['promotion']['status']}**", "", "## Search", "",
             f"- Budget: `{result['search']['budget']}`; used: `{result['search']['used']}`",
             f"- Selected: `{result['search']['selected_candidate_version']}`",
             f"- {result['search']['selection_basis']}", "", "## Required gates", ""]
    lines += [f"- **{item['name']}**: `{item['status']}` — {item['detail']}" for item in result["gates"]]
    lines += ["", "## Experiments", ""]
    lines += [f"- `{item['experiment_id']}` / `{item['candidate_version']}` — tuning return `{item['selection_score']}`; holdout accessed `{item['holdout_accessed']}`"
              for item in result["search"]["experiments"]]
    lines += ["", "## Scope", "", result["promotion"]["scope"], "", result["policy"]["justification"], ""]
    return "\n".join(lines)


class ValidationService:
    def __init__(self, store, market_service, vault_dir):
        self.store, self.market_service, self.vault = store, market_service, Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS validation_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    symbol TEXT NOT NULL, market_run_id TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS validation_experiments (
                    run_id TEXT NOT NULL, experiment_id TEXT NOT NULL, candidate_version TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY(run_id, experiment_id)
                );
            """)

    def submit(self, symbol, market_run_id, request_key):
        symbol = symbol.strip().upper()
        try:
            market = self.market_service.get(market_run_id)
        except KeyError:
            raise ValidationError("Market data run not found.", "not-found") from None
        if market["symbol"] != symbol:
            raise ValidationError("Market data run belongs to another security.", "conflict")
        fingerprint = _hash({"symbol": symbol, "market_run_id": market_run_id,
                             "policy": POLICY_VERSION, "registry": REGISTRY_VERSION, "search": SEARCH_VERSION})
        with self.store.connect() as db:
            prior = db.execute("SELECT id,fingerprint FROM validation_runs WHERE request_key=?", (request_key,)).fetchone()
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise ValidationError("Request key already belongs to another validation.", "conflict")
            return self.get(prior["id"]), False
        result = validate_market(symbol, market)
        result.update({"id": str(uuid.uuid4()), "created_at": _now(), "report": None})
        content = _render(result)
        path = f"Graph Stock/Validation/{symbol}/{result['id']}.md"
        self.vault.publish(path, content)
        result["report"] = {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connect() as db:
            try:
                db.execute("INSERT INTO validation_runs VALUES (?,?,?,?,?,?,?)", (
                    result["id"], request_key, fingerprint, symbol, market_run_id,
                    result["created_at"], json.dumps(result, sort_keys=True)))
                for item in result["search"]["experiments"]:
                    db.execute("INSERT INTO validation_experiments VALUES (?,?,?,?)", (
                        result["id"], item["experiment_id"], item["candidate_version"], json.dumps(item, sort_keys=True)))
            except sqlite3.IntegrityError:
                raise ValidationError("Request key already belongs to another validation.", "conflict") from None
        return result, True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT result FROM validation_runs WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["result"])

    def recent(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM validation_runs ORDER BY created_at DESC LIMIT 30").fetchall()
        return [json.loads(row["result"]) for row in rows]

    def read_report(self, run_id):
        return self.vault.read(self.get(run_id)["report"]["path"])
