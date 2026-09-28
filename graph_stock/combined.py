"""Separately capitalized combined paper portfolio with strategy attribution."""
from __future__ import annotations
import hashlib, json, sqlite3, uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from .vault import Vault

SCHEMA_VERSION="combined-paper-book/v1"
POLICY_VERSION="equal-allocation-exit-first/v1"

class CombinedError(Exception):
    def __init__(self,message,code="invalid"): self.message,self.code=message,code; super().__init__(message)
def _now(): return datetime.now(timezone.utc).isoformat()
def _hash(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _money(v): return Decimal(v).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
def _num(v,p="0.000001"): return format(Decimal(v).quantize(Decimal(p),rounding=ROUND_HALF_UP).normalize(),"f")

def _render(book):
    s=book["state"]
    lines=[f"## Combined Paper Book — {book['symbol']}","",f"Book: `{book['id']}`",f"Policy: `{s['policy_id']}`",
           f"Cash: `{s['cash']}`",f"Equity: `{s['equity']}`",f"Drawdown: `{s['drawdown_percent']}%`","","## Attribution",""]
    for member,pos in s["positions"].items(): lines.append(f"- `{member}`: `{pos['quantity']}` shares; cost basis `{pos['cost_basis']}`")
    lines += ["","## Ledger",""]+[f"- `{e['sequence']}` {e['session']} **{e['kind']}** — `{json.dumps(e['payload'],sort_keys=True)}`" for e in book["events"]]
    return "\n".join(lines)+"\n"

class CombinedService:
    def __init__(self,store,market_service,paper_service,vault_dir):
        self.store,self.market,self.paper,self.vault=store,market_service,paper_service,Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS combined_books(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,symbol TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS combined_events(event_id TEXT PRIMARY KEY,book_id TEXT NOT NULL,sequence INTEGER NOT NULL,session TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(book_id,sequence));
            CREATE TABLE IF NOT EXISTS combined_sessions(book_id TEXT NOT NULL,session TEXT NOT NULL,PRIMARY KEY(book_id,session));
            CREATE TABLE IF NOT EXISTS combined_requests(request_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
            """)
        self._reconcile_all()

    def _reconcile_all(self):
        """Compare each materialized state with the latest record in its own ledger."""
        with self.store.connect() as db:
            for book in db.execute("SELECT id,state FROM combined_books").fetchall():
                state=json.loads(book["state"])
                mark=db.execute(
                    "SELECT payload FROM combined_events WHERE book_id=? AND kind='mark' ORDER BY sequence DESC LIMIT 1",
                    (book["id"],),
                ).fetchone()
                matched=True
                if mark:
                    payload=json.loads(mark["payload"])
                    matched=(payload.get("cash_after")==state.get("cash") and payload.get("positions")==state.get("positions"))
                state["reconciliation"]={"status":"matched" if matched else "mismatch","checked_at":_now()}
                if not matched: state["status"]="paused"
                db.execute("UPDATE combined_books SET state=?,updated_at=? WHERE id=?",(json.dumps(state,sort_keys=True),_now(),book["id"]))

    def activate(self,symbol,member_ids,request_key,initial_cash="100000",allocations=None):
        symbol=symbol.upper(); member_ids=list(dict.fromkeys(member_ids))
        if len(member_ids)<2: raise CombinedError("At least two distinct independent paper books are required.")
        members=[]
        for mid in member_ids:
            try: m=self.paper.get(mid)
            except KeyError: raise CombinedError("Member paper book not found.","not-found") from None
            if m["symbol"]!=symbol: raise CombinedError("All member books must belong to the combined security.","conflict")
            members.append(m)
        cash=Decimal(str(initial_cash))
        if cash<=0: raise CombinedError("Initial cash must be positive.")
        if allocations is None: allocations={mid:_num(Decimal(100)/len(member_ids)) for mid in member_ids}
        if set(allocations)!=set(member_ids): raise CombinedError("Allocation must name every member book exactly once.")
        allocations={k:_num(Decimal(str(v))) for k,v in allocations.items()}
        if any(Decimal(v)<=0 for v in allocations.values()) or sum(map(Decimal,allocations.values()))>100:
            raise CombinedError("Allocations must be positive and cannot exceed 100% in total.")
        policy={"version":POLICY_VERSION,"initial_cash":_num(cash,"0.01"),"allocations_percent":allocations,
                "maximum_exposure_percent":"100","precedence":"risk-reducing exits before entries; any exit blocks same-symbol entries",
                "sizing":"whole shares within member allocation and shared available cash","broker_execution":False}
        policy_id=f"{POLICY_VERSION}/{_hash(policy)[:16]}"; fingerprint=_hash({"symbol":symbol,"members":member_ids,"policy":policy})
        with self.store.connect() as db:
            old=db.execute("SELECT id,fingerprint FROM combined_books WHERE request_key=?",(request_key,)).fetchone()
            if old:
                if old["fingerprint"]!=fingerprint: raise CombinedError("Request key already belongs to another combined book.","conflict")
                return self.get(old["id"]),False
        last=max(m["state"]["last_session"] for m in members); now=_now(); bid=str(uuid.uuid4())
        state={"schema_version":SCHEMA_VERSION,"status":"active","policy":policy,"policy_id":policy_id,"member_book_ids":member_ids,
               "cash":_num(cash,"0.01"),"positions":{m:{"quantity":"0","cost_basis":"0"} for m in member_ids},
               "pending_orders":[],"last_session":last,"equity":_num(cash,"0.01"),"peak_equity":_num(cash,"0.01"),"drawdown_percent":"0",
               "reconciliation":{"status":"matched","checked_at":now}}
        with self.store.connect() as db:
            db.execute("INSERT INTO combined_books VALUES (?,?,?,?,?,?,?)",(bid,request_key,fingerprint,symbol,now,now,json.dumps(state,sort_keys=True)))
        return self.get(bid),True

    def _member_decisions(self,db,state,session):
        out=[]
        for mid in state["member_book_ids"]:
            row=db.execute("SELECT event_id,payload FROM paper_events WHERE book_id=? AND session=? AND kind='decision' ORDER BY sequence DESC LIMIT 1",(mid,session)).fetchone()
            if row:
                payload=json.loads(row["payload"]); out.append((mid,payload.get("signal"),row["event_id"],payload.get("processing_mode")))
        return out

    def process(self,book_id,market_id,request_key,replay=False):
        fingerprint=_hash({"book":book_id,"market":market_id,**({"mode":"replay"} if replay else {})})
        with self.store.connect() as db:
            old=db.execute("SELECT fingerprint,result FROM combined_requests WHERE request_key=?",(request_key,)).fetchone()
            if old:
                if old["fingerprint"]!=fingerprint: raise CombinedError("Request key already belongs to another combined update.","conflict")
                return json.loads(old["result"]),False
        try: market=self.market.get(market_id)
        except KeyError: raise CombinedError("Market data run not found.","not-found") from None
        processed=0
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT * FROM combined_books WHERE id=?",(book_id,)).fetchone()
            if not row: raise CombinedError("Combined book not found.","not-found")
            book=dict(row); state=json.loads(row["state"])
            if market["symbol"]!=book["symbol"]: raise CombinedError("Market data belongs to another security.","conflict")
            sequence=db.execute("SELECT COALESCE(MAX(sequence),0) FROM combined_events WHERE book_id=?",(book_id,)).fetchone()[0]
            def emit(session,kind,key,payload):
                nonlocal sequence
                payload={**payload,"processing_mode":"replay" if replay else "live","market_run_id":market_id,
                         "market_source_hash":market["source"]["content_sha256"]}
                sequence+=1; eid=_hash({"book":book_id,"session":session,"kind":kind,"key":key})
                db.execute("INSERT INTO combined_events VALUES (?,?,?,?,?,?)",(eid,book_id,sequence,session,kind,json.dumps(payload,sort_keys=True)))
            for session in sorted(set(market["quality"]["expected_sessions"])):
                if replay and session>=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat(): continue
                if session<=state["last_session"] or db.execute("SELECT 1 FROM combined_sessions WHERE book_id=? AND session=?",(book_id,session)).fetchone(): continue
                rows=[r for r in market["raw_bars"] if r["session"]==session]
                row=rows[0] if len(rows)==1 and rows[0]["status"]=="regular" else None
                cash=Decimal(state["cash"])
                # Execute orders created by the prior processed close: exits first, then entries.
                pending=sorted(state["pending_orders"],key=lambda o:0 if o["side"]=="sell" else 1); state["pending_orders"]=[]
                for order in pending:
                    mid=order["member_book_id"]; pos=state["positions"][mid]; qty=Decimal(pos["quantity"])
                    if not row:
                        emit(session,"order-rejected",mid,{**order,"reason":"missing-or-stale-price"}); continue
                    slippage=Decimal("0.0005"); commission=Decimal("0.001")
                    if order["side"]=="sell" and qty>0:
                        price=_money(Decimal(row["open"])*(1-slippage)); gross=_money(qty*price); fee=_money(gross*commission); cash=_money(cash+gross-fee)
                        pos.update({"quantity":"0","cost_basis":"0"}); emit(session,"fill",f"sell:{mid}",{"member_book_id":mid,"side":"sell","quantity":_num(qty),"price":_num(price,"0.01"),"fee":_num(fee,"0.01"),"cash_after":_num(cash,"0.01")}); emit(session,"fee",f"sell:{mid}",{"member_book_id":mid,"side":"sell","amount":_num(fee,"0.01")})
                    elif order["side"]=="buy" and qty==0:
                        allocation=Decimal(state["policy"]["allocations_percent"][mid])/100; allocation_cap=Decimal(state["policy"]["initial_cash"])*allocation; budget=min(cash,allocation_cap); cash_before=cash
                        price=_money(Decimal(row["open"])*(1+slippage)); buy=(budget/(price*(1+commission))).to_integral_value(rounding=ROUND_DOWN)
                        if buy<=0: emit(session,"order-rejected",mid,{**order,"reason":"shared-cash-or-allocation-cap"}); continue
                        gross=_money(buy*price); fee=_money(gross*commission); cash=_money(cash-gross-fee)
                        pos.update({"quantity":_num(buy),"cost_basis":_num(gross+fee,"0.01")}); emit(session,"fill",f"buy:{mid}",{"member_book_id":mid,"side":"buy","quantity":_num(buy),"price":_num(price,"0.01"),"fee":_num(fee,"0.01"),"cash_after":_num(cash,"0.01"),"cash_before":_num(cash_before,"0.01"),"allocation_cap":_num(allocation_cap,"0.01"),"sizing_reason":"whole-shares-within-member-allocation-and-shared-cash"}); emit(session,"fee",f"buy:{mid}",{"member_book_id":mid,"side":"buy","amount":_num(fee,"0.01")})
                state["cash"]=_num(cash,"0.01")
                decisions=self._member_decisions(db,state,session); exits=[m for m,s,_,_ in decisions if s=="EXIT"]
                for mid,signal,event_id,member_mode in decisions:
                    emit(session,"decision",mid,{"member_book_id":mid,"signal":signal,"member_decision_event_id":event_id,
                                                 "member_processing_mode":member_mode})
                for mid in exits:
                    if Decimal(state["positions"][mid]["quantity"])>0: state["pending_orders"].append({"member_book_id":mid,"side":"sell","created_session":session})
                for mid,signal,_,_ in decisions:
                    if signal=="ENTRY":
                        if exits: emit(session,"order-rejected",f"conflict:{mid}",{"member_book_id":mid,"side":"buy","reason":"exit-precedence-conflict"})
                        elif Decimal(state["positions"][mid]["quantity"])==0: state["pending_orders"].append({"member_book_id":mid,"side":"buy","created_session":session})
                        else: emit(session,"order-rejected",f"position:{mid}",{"member_book_id":mid,"side":"buy","reason":"existing-attributed-position"})
                if row:
                    equity=cash+sum(Decimal(p["quantity"])*Decimal(row["close"]) for p in state["positions"].values()); peak=max(Decimal(state["peak_equity"]),equity)
                    state.update({"equity":_num(_money(equity),"0.01"),"peak_equity":_num(_money(peak),"0.01"),"drawdown_percent":_num((peak-equity)/peak*100 if peak else 0)})
                    emit(session,"mark","close",{"equity":state["equity"],"cash_after":state["cash"],"positions":state["positions"]})
                else: emit(session,"mark","unavailable",{"status":"unavailable","cash_after":state["cash"],"positions":state["positions"]})
                state["last_session"]=session; db.execute("INSERT INTO combined_sessions VALUES (?,?)",(book_id,session)); processed+=1
            state["reconciliation"]={"status":"matched","checked_at":_now()}
            db.execute("UPDATE combined_books SET state=?,updated_at=? WHERE id=?",(json.dumps(state,sort_keys=True),_now(),book_id))
        result=self.get(book_id)|{"process":{"market_run_id":market_id,"processed_sessions":processed,
                                              "mode":"replay" if replay else "live"}}
        content=_render(result); path=f"Graph Stock/Combined Paper/{result['symbol']}/{book_id}/{request_key}.md"; self.vault.publish(path,content)
        result["report"]={"path":path,"sha256":hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connect() as db: db.execute("INSERT INTO combined_requests VALUES (?,?,?)",(request_key,fingerprint,json.dumps(result,sort_keys=True)))
        return result,True

    def catch_up(self,book_id,market_id,request_key): return self.process(book_id,market_id,request_key,replay=True)

    def get(self,bid):
        with self.store.connect() as db:
            row=db.execute("SELECT * FROM combined_books WHERE id=?",(str(bid),)).fetchone()
            if not row: raise KeyError(bid)
            result=dict(row); result["state"]=json.loads(result["state"]); result["events"]=[{**dict(e),"payload":json.loads(e["payload"])} for e in db.execute("SELECT event_id,sequence,session,kind,payload FROM combined_events WHERE book_id=? ORDER BY sequence",(bid,))]; result.pop("request_key"); result.pop("fingerprint"); return result
    def recent(self):
        with self.store.connect() as db: ids=[r[0] for r in db.execute("SELECT id FROM combined_books ORDER BY created_at DESC LIMIT 30")]
        return [self.get(i) for i in ids]
    def read_report(self,bid): return _render(self.get(bid))
