import React, {useEffect, useRef, useState} from 'react';
const active = r => ['queued', 'running'].includes(r?.status);
const time = v => new Date(v).toLocaleString('en-IN', {timeZone: 'Asia/Kolkata'});
const publication = item => item.publication_precision === 'month' ?
  `${new Date(item.published_at).toLocaleDateString('en-IN', {month: 'short', year: 'numeric', timeZone: 'UTC'})} · month precision` : time(item.published_at);
async function api(path, options = {}) {
  const response = await fetch('/api/v1/filings' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the ticker, date and PDF inputs.');
  return data;
}
async function financialApi(path, options = {}) {
  const response = await fetch('/api/v1/financials' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Financial analysis could not be completed.');
  return data;
}
async function updateApi(path, options = {}) {
  const response = await fetch('/api/v1/updates' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Research update could not be completed.');
  return data;
}
async function ownershipApi(path, options = {}) {
  const response = await fetch('/api/v1/ownership' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Ownership history could not be completed.');
  return data;
}
async function newsApi(path, options = {}) {
  const response = await fetch('/api/v1/news' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'News coverage could not be completed.');
  return data;
}
async function marketApi(path, options = {}) {
  const response = await fetch('/api/v1/market-data' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Market data could not be completed.');
  return data;
}
async function featureApi(path, options = {}) {
  const response = await fetch('/api/v1/features' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Point-in-time snapshot could not be completed.');
  return data;
}
async function backtestApi(path, options = {}) {
  const response = await fetch('/api/v1/backtests' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Backtest could not be completed.');
  return data;
}
async function validationApi(path, options = {}) {
  const response = await fetch('/api/v1/validations' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Strategy validation could not be completed.');
  return data;
}
async function paperApi(path, options = {}) {
  const response = await fetch('/api/v1/paper-books' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Paper book action could not be completed.');
  return data;
}
async function combinedApi(path, options = {}) {
  const response = await fetch('/api/v1/combined-books' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Combined paper book action could not be completed.');
  return data;
}
async function schedulerApi(path, options = {}) {
  const response = await fetch('/api/v1/scheduler' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Scheduled work could not be completed.');
  return data;
}
async function startupApi() {
  const response = await fetch('/api/v1/startup');
  const data = await response.json();
  if (!response.ok) throw new Error('Startup status could not be read.');
  return data;
}
async function alertApi(path, options = {}) {
  const response = await fetch('/api/v1/alerts' + path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Material alerts could not be completed.');
  return data;
}
async function historyApi(path, options = {}) {
  const response = await fetch('/api/v1/history' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Research history could not be completed.');
  return data;
}
async function improvementApi(path, options = {}) {
  const response = await fetch('/api/v1/improvements' + path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Improvement review could not be completed.');
  return data;
}
const displayMetric = metric => metric.value === null ? `Unavailable · ${metric.reason.replaceAll('-', ' ')}` :
  `${metric.unit === 'INR crore' ? '₹' : ''}${Number(metric.value).toLocaleString('en-IN', {maximumFractionDigits: 2})} ${metric.unit === 'INR crore' ? 'crore' : metric.unit}`;

function Ownership({source}) {
  const [run, setRun] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    ownershipApi('').then(rows => live && setRun(rows.find(item => item.sources.some(s => s.source_id === source.id)) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.id]);
  async function build() {
    setBusy(true); setError('');
    request.current ||= {source_id: source.id, request_key: crypto.randomUUID()};
    try {
      setRun(await ownershipApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(request.current)}));
      request.current = null;
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  const rows = run?.comparison.comparisons || [];
  return <div className="ownership-panel">
    <p className="eyebrow">DATED INSTITUTIONAL ACTIVITY</p><h3>Compare disclosed ownership</h3>
    <p>Uses issuer disclosure dates and raw shares. Observed changes do not identify exact trades.</p>
    {!run && <button className="secondary" onClick={build} disabled={busy}>{busy ? 'Building history…' : 'Build ownership history locally'}</button>}
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run && <><p><strong>{run.comparison.prior_period}</strong> → <strong>{run.comparison.current_period}</strong> · comparable denominator</p>
      <div className="ownership-grid">{rows.map(row => <article key={row.holder_id}>
        <span>{row.kind}{row.fund_house ? ` · ${row.fund_house}` : ''}</span><strong>{row.name}</strong>
        <p>{row.prior ? `${Number(row.prior.shares).toLocaleString('en-IN')} · ${row.prior.percent}%` : 'Prior: unavailable'}<br/>{row.current ? `${Number(row.current.shares).toLocaleString('en-IN')} · ${row.current.percent}%` : 'Current: unavailable'}</p>
        <small>{row.status}{row.reason ? ` · ${row.reason.replaceAll('-', ' ')}` : ''}</small>
      </article>)}</div>
      <p className="note-warning">Pledge disclosure: unavailable in both bounded source records.</p>
      <div className="note-links"><a href={`/api/v1/ownership/${run.id}/reports/shareholding`} target="_blank" rel="noreferrer">Read Shareholding report</a><a href={`/api/v1/ownership/${run.id}/reports/institutional-flow`} target="_blank" rel="noreferrer">Read Institutional Flow report</a></div>
      <details><summary>Source coverage and publication dates</summary>{run.sources.map(item => <p key={item.source_id}><strong>{item.period}</strong> · published {publication(item)}<br/>{item.title} · aggregate {item.coverage.aggregate}, named holders {item.coverage.named_holders}, pledge {item.coverage.pledge}</p>)}</details>
    </>}
  </div>;
}

function NewsCatalysts({source}) {
  const [run, setRun] = useState(null), [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    newsApi('').then(rows => live && setRun(rows.find(item => item.source_id === source.id) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.id]);
  async function collect(records = null) {
    setBusy(true); setError('');
    const mode = records ? 'manual' : 'automatic';
    if (request.current?.mode !== mode) request.current = {mode, request_key: crypto.randomUUID()};
    try {
      const payload = {source_id: source.id, request_key: request.current.request_key, ...(records ? {records} : {})};
      setRun(await newsApi(records ? '/import' : '', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(payload)}));
      request.current = null; setFile(null);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function importFile() {
    try {
      const value = JSON.parse(await file.text());
      const records = Array.isArray(value) ? value : value.records;
      if (!Array.isArray(records) || records.length === 0) throw new Error('invalid-event-file');
      await collect(records);
    } catch(e) {setError(e.message === 'News coverage could not be completed.' ? e.message : 'Choose a valid event JSON file.');}
  }
  return <div className="news-panel">
    <p className="eyebrow">NEWS & CATALYSTS</p><h3>Dated material events</h3>
    <p>Primary filings lead; supporting sources are linked. Facts, source assertions and research inference remain separate.</p>
    <div className="financial-actions"><button className="secondary" onClick={() => collect()} disabled={busy}>Load measured events locally</button>
      <label className="file-action">Manual event JSON<input type="file" accept="application/json,.json" onChange={e => setFile(e.target.files[0])}/></label>
      {file && <button className="text-button" onClick={importFile} disabled={busy}>Import fallback</button>}</div>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run?.gaps.map(gap => <p className="note-warning" key={gap}>Coverage gap: {gap}</p>)}
    {run && <><p>Primary filings: <strong>{run.coverage.primary_filings}</strong> · supporting news: <strong>{run.coverage.supporting_news}</strong></p>
      <div className="news-list">{run.events.map(event => <article key={event.version_id}>
        <div><span className={`severity ${event.severity}`}>{event.severity}</span><small>{event.event_date} · first public {time(event.first_available_at)}</small></div>
        <h4>{event.event_type.replaceAll('-', ' ')}</h4>
        <p><strong>Fact:</strong> {event.facts[0].text}</p>
        <p><strong>Source assertion:</strong> {event.source_assertions[0].text}</p>
        <p><strong>Reported relevance:</strong> {event.source_assertions[1].text}</p>
        <p><strong>Inference · {event.inferences[0].confidence}:</strong> {event.inferences[0].text}</p>
        <div className="note-links">{event.sources.map(item => <a key={item.source_id} href={item.url} target="_blank" rel="noreferrer">{item.source_kind.replaceAll('-', ' ')} ↗</a>)}</div>
      </article>)}</div>
      <div className="note-links"><a href={`/api/v1/news/${run.id}/report`} target="_blank" rel="noreferrer">Read News & Catalyst report</a><a href={`/api/v1/news/${run.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function MarketData({source}) {
  const [run, setRun] = useState(null), [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    marketApi('').then(rows => live && setRun(rows.find(item => item.symbol === source.symbol) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function collect(bundle = null) {
    setBusy(true); setError('');
    const mode = bundle ? 'manual' : 'automatic';
    if (request.current?.mode !== mode) request.current = {mode, request_key: crypto.randomUUID()};
    try {
      const payload = {symbol: source.symbol, request_key: request.current.request_key, ...(bundle ? {bundle} : {})};
      setRun(await marketApi(bundle ? '/import' : '', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(payload)}));
      request.current = null; setFile(null);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function importFile() {
    try {
      const value = JSON.parse(await file.text());
      await collect(value.bundle || value);
    } catch(e) {setError(e.message === 'Market data could not be completed.' ? e.message : 'Choose a valid market-data JSON file.');}
  }
  const q = run?.quality;
  return <div className="market-panel">
    <p className="eyebrow">MARKET DATA & CORPORATE ACTIONS</p><h3>Inspect raw and adjusted daily bars</h3>
    <p>Uses official NSE current-session data or a validated manual bundle. Raw values stay unchanged beside versioned adjustments.</p>
    <div className="financial-actions"><button className="secondary" onClick={() => collect()} disabled={busy}>{busy ? 'Collecting…' : 'Collect latest NSE session'}</button>
      <label className="file-action">Manual market JSON<input type="file" accept="application/json,.json" onChange={e => setFile(e.target.files[0])}/></label>
      {file && <button className="text-button" onClick={importFile} disabled={busy}>Import fallback</button>}</div>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run && <><div className="market-quality"><span><strong>{q.status}</strong>quality</span><span><strong>{q.listing_coverage.bar_count}</strong>raw bars</span><span><strong>{run.benchmark.symbol}</strong>benchmark</span><span><strong>{run.actions.length}</strong>actions</span></div>
      <p className="market-gaps">Missing sessions: {q.missing_sessions.length ? q.missing_sessions.join(', ') : 'none'} · benchmark gaps: {q.benchmark_missing_sessions.length ? q.benchmark_missing_sessions.join(', ') : 'none'} · duplicates: {q.duplicate_sessions.length ? q.duplicate_sessions.join(', ') : 'none'} · suspensions: {q.suspensions.length ? q.suspensions.join(', ') : 'none'} · provisional: {q.provisional_sessions.length ? q.provisional_sessions.join(', ') : 'none'}</p>
      {q.blocked_segments.map(item => <p className="note-warning" key={item}>Blocked adjustment segment: {item}</p>)}
      {run.identity_conflicts.map(item => <p className="note-warning" key={item.field}>Identity conflict: market source {item.market_source_value}; NSE directory {item.directory_value}. {item.selection}.</p>)}
      <div className="market-table"><table><thead><tr><th>Session</th><th>Raw OHLC</th><th>Adjusted close</th><th>Factor</th><th>Raw / adjusted volume</th><th>State</th></tr></thead><tbody>{run.adjusted_bars.map(row => <tr key={`${row.session}-${row.row}`}><td>{row.session}</td><td>{row.open} / {row.high} / {row.low} / {row.close}</td><td>{row.adjusted_close ?? 'Blocked'}</td><td>{row.price_factor ?? '—'}</td><td>{Number(row.volume).toLocaleString('en-IN')} / {row.adjusted_volume === null ? '—' : Number(row.adjusted_volume).toLocaleString('en-IN')}</td><td>{row.adjustment_status}<small>{row.reason?.replaceAll('-', ' ')}</small></td></tr>)}</tbody></table></div>
      <div className="action-grid">{run.actions.map(item => <article key={item.action_id}><span>{item.ex_date}</span><strong>{item.type}</strong><code>{JSON.stringify(item.terms)}</code><small>{item.adjustment_status}{item.reason ? ` · ${item.reason.replaceAll('-', ' ')}` : ` · price factor ${item.price_factor}`}</small></article>)}</div>
      <details><summary>Security identity and raw-source evidence</summary><p>{run.name} · {run.symbol} · {run.isin} · {run.exchange}</p>{run.aliases.map(item => <p key={item.symbol + item.effective_from}>Alias {item.symbol} · effective {item.effective_from} → {item.effective_to || 'current'}</p>)}<p><a href={run.source.url} target="_blank" rel="noreferrer">{run.source.title} ↗</a><br/>Retrieved {time(run.source.retrieved_at)} · SHA-256 <code>{run.source.content_sha256}</code></p><p>{run.normalization_scope}</p></details>
      <div className="note-links"><a href={`/api/v1/market-data/${run.id}/report`} target="_blank" rel="noreferrer">Read market-data report</a><a href={`/api/v1/market-data/${run.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function FeatureSnapshots({source}) {
  const [run, setRun] = useState(null), [decision, setDecision] = useState(() => new Date(Date.now() + 330 * 60000).toISOString().slice(0, 16));
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    featureApi('').then(rows => live && setRun(rows.find(item => item.symbol === source.symbol) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function build() {
    setBusy(true); setError('');
    const decisionTime = decision + ':00+05:30';
    if (request.current?.decision_time !== decisionTime) request.current = {symbol: source.symbol, decision_time: decisionTime, request_key: crypto.randomUUID()};
    try {
      setRun(await featureApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(request.current)}));
      request.current = null;
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  return <div className="feature-panel">
    <p className="eyebrow">POINT-IN-TIME FEATURES</p><h3>Reconstruct what was publicly available</h3>
    <p>Historical joins use publication time. Ingestion stays visible, and retrospective reasoning cannot become a past feature.</p>
    <div className="feature-controls"><label>Decision time · Asia/Kolkata<input type="datetime-local" value={decision} onChange={e => {setDecision(e.target.value); request.current = null;}}/></label><button className="secondary" onClick={build} disabled={busy || !decision}>{busy ? 'Building…' : 'Build feature snapshot'}</button></div>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run && <><p><strong>{run.included.length}</strong> included · <strong>{run.excluded.length}</strong> excluded · decision {time(run.decision_time)}</p>
      <div className="feature-coverage">{Object.entries(run.coverage).map(([family, value]) => <span key={family}><strong>{family}</strong>{value.included} in · {value.excluded} out</span>)}</div>
      <p className="manifest-line">Dataset manifest <code>{run.dataset_manifest.hash}</code></p>
      <div className="feature-columns"><section><h4>Included at cutoff</h4>{run.included.length === 0 && <p>None</p>}{run.included.slice(0, 40).map(item => <article key={item.feature_id}><strong>{item.family} · {item.name}</strong><span>{typeof item.value === 'object' ? JSON.stringify(item.value) : `${item.value} ${item.unit}`}</span><small>effective {time(item.data_vintage.effective_time)} · public {time(item.data_vintage.public_available_at)}<br/>source {item.source_id}</small></article>)}</section>
        <section><h4>Excluded with reason</h4>{run.excluded.length === 0 && <p>None</p>}{run.excluded.slice(0, 40).map(item => <article key={item.feature_id}><strong>{item.family} · {item.name}</strong><span className="exclusion-reason">{item.exclusion_reason.replaceAll('-', ' ')}</span><small>effective {time(item.data_vintage.effective_time)} · public {item.data_vintage.public_available_at ? time(item.data_vintage.public_available_at) : 'unknown'}</small></article>)}</section></div>
      <details><summary>Precision and universe policy</summary><p>{run.knowledge_basis}</p>{Object.entries(run.precision_policy).map(([key, value]) => <p key={key}><strong>{key}:</strong> {value}</p>)}<p>{run.universe.limitation}</p><p>Listing state at cutoff: {run.universe.status} · aliases {run.universe.active_aliases.map(item => item.symbol).join(', ') || 'unknown'}</p></details>
      <div className="note-links"><a href={`/api/v1/features/${run.id}/report`} target="_blank" rel="noreferrer">Read feature report</a><a href={`/api/v1/features/${run.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function Backtests({source}) {
  const [run, setRun] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    backtestApi('').then(rows => live && setRun(rows.find(item => item.symbol === source.symbol) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function build() {
    setBusy(true); setError('');
    try {
      const markets = await marketApi('');
      const market = markets.find(item => item.symbol === source.symbol);
      if (!market) throw new Error('Build or import daily market data before running a backtest.');
      if (request.current?.market_run_id !== market.id) request.current = {
        symbol: source.symbol, market_run_id: market.id, request_key: crypto.randomUUID()
      };
      setRun(await backtestApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(request.current)}));
      request.current = null;
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  const m = run?.metrics;
  return <div className="backtest-panel">
    <p className="eyebrow">REPRODUCIBLE BACKTEST</p><h3>Trend-following cash ledger</h3>
    <p>Decisions occur after close and orders use only the next expected eligible session. The ledger exposes gaps, costs, actions, stops and ambiguous bars.</p>
    <button className="secondary" onClick={build} disabled={busy}>{busy ? 'Simulating…' : 'Run approved strategy'}</button>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run && <><div className="backtest-metrics">
      <span><strong>{m.total_return_percent}%</strong>return</span><span><strong>{m.max_drawdown_percent}%</strong>max drawdown</span>
      <span><strong>{m.trade_count}</strong>closed trades</span><span><strong>{m.win_rate_percent ?? '—'}{m.win_rate_percent !== null ? '%' : ''}</strong>win rate</span>
      <span><strong>{m.exposure_percent ?? '—'}{m.exposure_percent !== null ? '%' : ''}</strong>exposure</span><span><strong>{m.benchmark_return_percent ?? '—'}{m.benchmark_return_percent !== null ? '%' : ''}</strong>benchmark</span>
    </div>
      <p className="manifest-line">Strategy <code>{run.strategy.version}</code> · data <code>{run.data_manifest.hash}</code></p>
      {run.benchmark.reason && <p className="note-warning">Benchmark comparison unavailable: {run.benchmark.reason.replaceAll('-', ' ')}</p>}
      <div className="backtest-table"><table><thead><tr><th>Trade</th><th>Entry</th><th>Exit</th><th>Quantity</th><th>Net P&amp;L</th><th>Reason</th></tr></thead><tbody>
        {run.trades.length === 0 && <tr><td colSpan="6">No closed trades in this bounded sample.</td></tr>}
        {run.trades.map(item => <tr key={item.trade_id}><td>{item.trade_id}</td><td>{item.entry_session}<small>₹{item.entry_price}</small></td><td>{item.exit_session}<small>₹{item.exit_price}</small></td><td>{item.quantity}</td><td>₹{item.net_pnl}</td><td>{item.exit_reason.replaceAll('-', ' ')}{item.ambiguity ? ' · conservative ambiguity' : ''}</td></tr>)}
      </tbody></table></div>
      <details><summary>Execution and cost assumptions</summary><p>{run.strategy.rule}</p><p>{run.timing_policy}</p><p>{run.ambiguity_policy}</p><p>{run.missing_bar_policy}</p><p>{run.corporate_action_policy}</p><p>{run.strategy.config.commission_bps} bps commission + {run.strategy.config.slippage_bps} bps slippage. {run.strategy.config.cost_source}</p><p>{run.universe.limitation}</p></details>
      <div className="note-links"><a href={`/api/v1/backtests/${run.id}/report`} target="_blank" rel="noreferrer">Read backtest report</a><a href={`/api/v1/backtests/${run.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function StrategyValidation({source}) {
  const [run, setRun] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    validationApi('').then(rows => live && setRun(rows.find(item => item.symbol === source.symbol) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function build() {
    setBusy(true); setError('');
    try {
      const markets = await marketApi('');
      const market = markets.find(item => item.symbol === source.symbol);
      if (!market) throw new Error('Build or import daily market data before validating strategies.');
      if (request.current?.market_run_id !== market.id) request.current = {
        symbol: source.symbol, market_run_id: market.id, request_key: crypto.randomUUID()
      };
      setRun(await validationApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(request.current)}));
      request.current = null;
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  return <div className="validation-panel">
    <p className="eyebrow">STRATEGY VALIDATION</p><h3>Bounded search with an untouched holdout</h3>
    <p>Every allowlisted experiment is retained. Paper eligibility requires every sample, holdout, benchmark, drawdown, cost, sensitivity and walk-forward gate to pass.</p>
    <button className="secondary" onClick={build} disabled={busy}>{busy ? 'Validating…' : 'Validate bounded candidates'}</button>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run && <><div className={`validation-outcome ${run.promotion.status}`}><strong>{run.promotion.status.replaceAll('-', ' ')}</strong><span>{run.promotion.paper_eligible ? 'Paper eligible under this versioned policy' : 'Not eligible for paper trading'}</span></div>
      <p className="manifest-line">Policy <code>{run.policy_version}</code> · validation manifest <code>{run.validation_manifest.hash}</code></p>
      <div className="gate-grid">{run.gates.map(item => <article key={item.name} className={item.status}><span>{item.status}</span><strong>{item.name.replaceAll('-', ' ')}</strong><small>{item.detail}</small></article>)}</div>
      <details><summary>Candidate search and untouched windows</summary><p>Budget {run.search.budget} · used {run.search.used} · selected {run.search.selected_candidate_version || 'none'}</p><p>{run.search.selection_basis}</p>{Object.entries(run.windows).map(([name, value]) => <p key={name}><strong>{name.replaceAll('_', ' ')}</strong>: {value.start || '—'} → {value.end || '—'} · {value.sessions} sessions · <code>{value.hash}</code></p>)}</details>
      <details><summary>Approved family registry</summary><div className="family-grid">{Object.entries(run.family_registry).map(([name, value]) => <article key={name}><strong>{name}</strong><span>{value.eligible ? 'eligible' : value.reason.replaceAll('-', ' ')}</span><small>Requires {value.required_features.join(', ')}{value.missing_features.length ? ` · missing ${value.missing_features.join(', ')}` : ''}</small></article>)}</div></details>
      <details><summary>All persisted experiments</summary>{run.search.experiments.map(item => <p key={item.experiment_id}><strong>{item.experiment_id}</strong> · {item.candidate_version} · tuning return {item.selection_score ?? 'unavailable'}% · holdout accessed {String(item.holdout_accessed)}</p>)}</details>
      <div className="note-links"><a href={`/api/v1/validations/${run.id}/report`} target="_blank" rel="noreferrer">Read validation report</a><a href={`/api/v1/validations/${run.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function PaperBook({source}) {
  const [book, setBook] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    paperApi('').then(rows => live && setBook(rows.find(item => item.symbol === source.symbol) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function activateBook() {
    setBusy(true); setError('');
    try {
      const validations = await validationApi('');
      const validation = validations.find(item => item.symbol === source.symbol && item.promotion.paper_eligible);
      if (!validation) throw new Error('No all-gates-passed validation is available for paper activation.');
      if (request.current?.validation_id !== validation.id) request.current = {
        symbol: source.symbol, validation_id: validation.id, request_key: crypto.randomUUID()
      };
      setBook(await paperApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(request.current)}));
      request.current = null;
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function processMarket() {
    setBusy(true); setError('');
    try {
      const markets = await marketApi('');
      const market = markets.find(item => item.symbol === source.symbol);
      if (!market) throw new Error('No market session is available for this paper book.');
      setBook(await paperApi(`/${book.id}/process`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({market_run_id: market.id, request_key: crypto.randomUUID()})}));
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function catchUp() {
    setBusy(true); setError('');
    try {
      const markets = await marketApi('');
      const market = markets.find(item => item.symbol === source.symbol);
      if (!market) throw new Error('No saved market history is available for catch-up.');
      const result = await paperApi(`/${book.id}/catch-up`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({market_run_id: market.id, request_key: crypto.randomUUID()})});
      setBook(result.book);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  const state = book?.state;
  return <div className="paper-panel">
    <p className="eyebrow">PAPER PORTFOLIO</p><h3>Independent validated-strategy book</h3>
    <p>Local simulated accounting only. Stable session events protect decisions and fills from duplication across retries and restarts.</p>
    {!book && <button className="secondary" onClick={activateBook} disabled={busy}>{busy ? 'Activating…' : 'Activate passed strategy'}</button>}
    {book && <div className="paper-actions"><button className="secondary" onClick={processMarket} disabled={busy || state.status !== 'active'}>{busy ? 'Processing…' : 'Process latest saved session'}</button><button className="secondary" onClick={catchUp} disabled={busy || state.status !== 'active'}>Replay missed sessions</button></div>}
    {error && <p role="alert" className="note-warning">{error}</p>}
    {book && <><div className={`paper-status ${state.status}`}><span><strong>₹{Number(state.cash).toLocaleString('en-IN')}</strong>cash</span><span><strong>{Number(state.quantity).toLocaleString('en-IN')}</strong>shares</span><span><strong>{state.pending_order?.side || 'none'}</strong>pending</span><span><strong>{state.status}</strong>book state</span></div>
      {state.pause_reason && <p className="note-warning">Paused: {state.pause_reason.replaceAll('-', ' ')}</p>}
      <p>Last processed session: <strong>{state.last_session}</strong> · reconciliation <strong>{state.reconciliation.status}</strong></p>
      {book.monitoring && <div className={`degradation ${book.monitoring.status}`}><strong>{book.monitoring.status.replaceAll('-', ' ')}</strong><span>Paper {book.monitoring.paper.total_return_percent}% across {book.monitoring.paper.sample_sessions} sessions / {book.monitoring.paper.closed_trades} closed trades</span><span>Validation {book.monitoring.backtest.total_return_percent ?? 'unavailable'}% across {book.monitoring.backtest.sample_sessions ?? 'unknown'} sessions / {book.monitoring.backtest.closed_trades ?? 'unknown'} closed trades</span>{book.monitoring.reasons.map(reason => <small key={reason}>{reason.replaceAll('-', ' ')}</small>)}</div>}
      {state.new_entries_paused && <p className="note-warning">New entries paused · revalidation {state.revalidation.status}. Existing risk-reducing exits continue.</p>}
      <div className="paper-ledger"><table><thead><tr><th>#</th><th>Session</th><th>Record</th><th>Detail</th></tr></thead><tbody>{book.events.slice(-30).map(item => <tr key={item.event_id}><td>{item.sequence}</td><td>{item.session}</td><td>{item.kind.replaceAll('-', ' ')}</td><td><code>{JSON.stringify(item.payload)}</code></td></tr>)}</tbody></table></div>
      <details><summary>Frozen strategy and risk limits</summary><p>Candidate <code>{state.candidate_version}</code></p><p>Validation manifest <code>{state.validation_manifest_hash}</code></p>{Object.entries(state.policy).map(([key, value]) => <p key={key}><strong>{key.replaceAll('_', ' ')}:</strong> {String(value)}</p>)}</details>
      <div className="note-links"><a href={`/api/v1/paper-books/${book.id}/report`} target="_blank" rel="noreferrer">Read reconciled ledger</a><a href={`/api/v1/paper-books/${book.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function CombinedBook({source}) {
  const [book, setBook] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    combinedApi('').then(rows => live && setBook(rows.find(item => item.symbol === source.symbol) || null))
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function activateBook() {
    setBusy(true); setError('');
    try {
      const members = (await paperApi('')).filter(item => item.symbol === source.symbol && item.state.status === 'active');
      if (members.length < 2) throw new Error('Activate at least two independent paper books for this security first.');
      setBook(await combinedApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({
        symbol: source.symbol, member_book_ids: members.slice(0, 2).map(item => item.id), request_key: crypto.randomUUID(), initial_cash: '100000'
      })}));
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function processMarket() {
    setBusy(true); setError('');
    try {
      const market = (await marketApi('')).find(item => item.symbol === source.symbol);
      if (!market) throw new Error('No saved market session is available for this combined book.');
      setBook(await combinedApi(`/${book.id}/process`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({market_run_id: market.id, request_key: crypto.randomUUID()})}));
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function catchUp() {
    setBusy(true); setError('');
    try {
      const market = (await marketApi('')).find(item => item.symbol === source.symbol);
      if (!market) throw new Error('No saved market history is available for combined catch-up.');
      setBook(await combinedApi(`/${book.id}/catch-up`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({market_run_id: market.id, request_key: crypto.randomUUID()})}));
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  const state = book?.state;
  const holdings = state ? Object.entries(state.positions).filter(([, item]) => Number(item.quantity) > 0) : [];
  return <div className="paper-panel combined-panel">
    <p className="eyebrow">COMBINED PAPER PORTFOLIO</p><h3>Shared-capital strategy book</h3>
    <p>This separately funded ledger applies risk-reducing exits before entries and attributes every simulated fill and fee to its member strategy.</p>
    {!book && <button className="secondary" onClick={activateBook} disabled={busy}>{busy ? 'Activating…' : 'Combine two active books'}</button>}
    {book && <div className="paper-actions"><button className="secondary" onClick={processMarket} disabled={busy || state.status !== 'active'}>{busy ? 'Processing…' : 'Process latest saved session'}</button><button className="secondary" onClick={catchUp} disabled={busy || state.status !== 'active'}>Replay missed sessions</button></div>}
    {error && <p role="alert" className="note-warning">{error}</p>}
    {book && <><div className={`paper-status ${state.status}`}><span><strong>₹{Number(state.cash).toLocaleString('en-IN')}</strong>cash</span><span><strong>₹{Number(state.equity).toLocaleString('en-IN')}</strong>equity</span><span><strong>{Number(state.drawdown_percent).toFixed(2)}%</strong>drawdown</span><span><strong>{holdings.length}</strong>attributed holdings</span></div>
      <p>Last processed session: <strong>{state.last_session}</strong> · reconciliation <strong>{state.reconciliation.status}</strong></p>
      <div className="attribution-grid">{Object.entries(state.positions).map(([member, position]) => <article key={member}><strong>{Number(position.quantity).toLocaleString('en-IN')} shares</strong><span>Member {member.slice(0, 8)}</span><small>Cost basis ₹{Number(position.cost_basis).toLocaleString('en-IN')}</small></article>)}</div>
      <div className="paper-ledger"><table><thead><tr><th>#</th><th>Session</th><th>Record</th><th>Attributed detail</th></tr></thead><tbody>{book.events.slice(-30).map(item => <tr key={item.event_id}><td>{item.sequence}</td><td>{item.session}</td><td>{item.kind.replaceAll('-', ' ')}</td><td><code>{JSON.stringify(item.payload)}</code></td></tr>)}</tbody></table></div>
      <details><summary>Versioned shared-capital policy</summary><p>Policy <code>{state.policy_id}</code></p>{Object.entries(state.policy).map(([key, value]) => <p key={key}><strong>{key.replaceAll('_', ' ')}:</strong> {typeof value === 'object' ? JSON.stringify(value) : String(value)}</p>)}</details>
      <div className="note-links"><a href={`/api/v1/combined-books/${book.id}/report`} target="_blank" rel="noreferrer">Read combined ledger</a><a href={`/api/v1/combined-books/${book.id}/report?download=true`}>Download .md ↓</a></div>
    </>}
  </div>;
}

function ScheduleStatus({source}) {
  const [jobs, setJobs] = useState([]), [startup, setStartup] = useState(null), [busy, setBusy] = useState(''), [error, setError] = useState('');
  async function refresh(sync = false) {
    const rows = await schedulerApi(sync ? '/sync' : '/jobs', sync ? {method: 'POST', headers: {'X-Graph-Stock': 'local-research'}} : {});
    setJobs(rows.filter(item => item.symbol === source.symbol));
  }
  useEffect(() => {
    let live = true;
    Promise.all([schedulerApi('/jobs'), startupApi()]).then(async ([rows, startupStatus]) => {
      if (!live) return;
      setStartup(startupStatus);
      const matching = rows.filter(item => item.symbol === source.symbol);
      if (matching.length) setJobs(matching);
      else await refresh(true);
    }).catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function run(job) {
    setBusy(job.id); setError('');
    try {
      await schedulerApi(`/jobs/${job.id}/run`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({request_key: crypto.randomUUID()})});
      await refresh();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  return <div className="paper-panel schedule-panel">
    <p className="eyebrow">PERSISTED LOCAL SCHEDULE</p><h3>Research and paper refresh</h3>
    <p>Times are stored with timezone offsets and shown in Asia/Kolkata. Missed work coalesces on restart; unavailable disclosures retry without blocking other jobs.</p>
    {startup && <div className={`startup-status ${startup.installed && startup.definition_valid ? 'enabled' : 'disabled'}`}>
      <div><strong>Login startup {startup.installed && startup.definition_valid ? 'enabled' : 'optional'}</strong><span>This process was started {startup.current_process_started_by === 'launchd' ? 'automatically by macOS' : 'manually'}.</span></div>
      <div><code>{startup.installed ? startup.remove_command : startup.install_command}</code><small>{startup.sleep_limit}</small></div>
    </div>}
    {error && <p role="alert" className="note-warning">{error}</p>}
    {!jobs.length && <p className="muted">No schedule is registered for this security yet.</p>}
    <div className="schedule-grid">{jobs.map(job => <article key={job.id} className={job.status}><div><strong>{job.kind.replaceAll('-', ' ')}</strong><span>{job.cadence} · next {time(job.next_due)}</span>{job.waiting_reason && <small>{job.waiting_reason}</small>}</div><div><em>{job.status.replaceAll('-', ' ')}</em><button className="text-button" onClick={() => run(job)} disabled={Boolean(busy)}>{busy === job.id ? 'Running…' : 'Run now'}</button></div></article>)}</div>
  </div>;
}

function AlertCenter({source}) {
  const [alerts, setAlerts] = useState([]), [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [scanResult, setScanResult] = useState(null);
  async function refresh() {
    const [items, policy] = await Promise.all([alertApi('?symbol=' + encodeURIComponent(source.symbol)), alertApi('/config')]);
    setAlerts(items); setConfig(policy);
  }
  useEffect(() => {
    let live = true;
    Promise.all([alertApi('?symbol=' + encodeURIComponent(source.symbol)), alertApi('/config')])
      .then(([items, policy]) => {if (live) {setAlerts(items); setConfig(policy);}})
      .catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  async function scan() {
    setBusy('scan'); setError('');
    try {
      setScanResult(await alertApi('/scan', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({symbol: source.symbol, request_key: crypto.randomUUID()})}));
      await refresh();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function configure(next) {
    setBusy('config'); setError('');
    try {
      setConfig(await alertApi('/config', {method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(next)}));
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function acknowledge(id) {
    setBusy(id); setError('');
    try {
      await alertApi(`/${id}/acknowledge`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({note: null})});
      await refresh();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  const unread = alerts.filter(item => !item.acknowledged_at).length;
  return <div className="paper-panel alert-panel">
    <p className="eyebrow">MATERIAL CHANGE ALERTS</p><h3>{unread} alert{unread === 1 ? '' : 's'} need review</h3>
    <p>Saved thesis, disclosed ownership and paper-risk changes appear here and in immutable Obsidian notes.</p>
    {config && <div className="alert-controls"><label>Minimum severity<select value={config.minimum_severity} disabled={Boolean(busy)} onChange={e => configure({minimum_severity: e.target.value, material_only: config.material_only})}>{['low','medium','high','critical'].map(value => <option key={value}>{value}</option>)}</select></label><label className="check-control"><input type="checkbox" checked={config.material_only} disabled={Boolean(busy)} onChange={e => configure({minimum_severity: config.minimum_severity, material_only: e.target.checked})}/> Material events only</label><button className="secondary" disabled={Boolean(busy)} onClick={scan}>{busy === 'scan' ? 'Checking…' : 'Check saved changes'}</button></div>}
    {config && <small>Rule set <code>{config.policy_version}</code> · default delivery filters by materiality and severity.</small>}
    {scanResult && <p role="status" className="alert-scan">Latest check: {scanResult.created.length} new · {scanResult.deduplicated.length} already delivered · {scanResult.filtered.length} filtered</p>}
    {error && <p role="alert" className="note-warning">{error}</p>}
    {!alerts.length && <p className="muted">No saved material changes for {source.symbol}.</p>}
    <div className="alert-list">{alerts.map(item => <article key={item.id} className={item.acknowledged_at ? 'acknowledged' : ''}>
      <div className="alert-head"><span className={`severity ${item.severity}`}>{item.severity}</span><strong>{item.category.replaceAll('-', ' ')}</strong><time>{time(item.as_of)}</time></div>
      <p>{item.summary}</p><details><summary>Evidence and comparison</summary><p>Source: <code>{item.source.type}:{item.source.id}</code></p><p>Evidence: {item.source.evidence_ids.join(' · ')}</p><pre>{JSON.stringify(item.comparison, null, 2)}</pre></details>
      <p className="next-action"><strong>Next action:</strong> {item.next_action}</p>
      <div className="alert-actions"><a href={`/api/v1/alerts/${item.id}/note`} target="_blank" rel="noreferrer">Read Obsidian note</a>{item.acknowledged_at ? <span>Reviewed {time(item.acknowledged_at)}</span> : <button className="text-button" disabled={Boolean(busy)} onClick={() => acknowledge(item.id)}>{busy === item.id ? 'Saving…' : 'Mark reviewed'}</button>}</div>
      {item.publication_status !== 'published' && <small>Obsidian: {item.publication_status.replaceAll('-', ' ')}</small>}
    </article>)}</div>
  </div>;
}

function ResearchHistory({source}) {
  const [run, setRun] = useState(null), [corrections, setCorrections] = useState([]), [backups, setBackups] = useState([]);
  const [factId, setFactId] = useState(''), [value, setValue] = useState(''), [evidence, setEvidence] = useState(''), [reason, setReason] = useState('');
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [restore, setRestore] = useState(null);
  async function refresh() {
    const [financials, saved, archives] = await Promise.all([financialApi(''), historyApi('/corrections?symbol=' + encodeURIComponent(source.symbol)), historyApi('/backups')]);
    const selected = financials.find(item => item.source_id === source.id && item.snapshot);
    setRun(selected || null); setCorrections(saved); setBackups(archives);
    if (!factId && selected?.snapshot.facts[0]) setFactId(selected.snapshot.facts[0].id);
  }
  useEffect(() => {
    let live = true;
    Promise.all([financialApi(''), historyApi('/corrections?symbol=' + encodeURIComponent(source.symbol)), historyApi('/backups')]).then(([financials, saved, archives]) => {
      if (!live) return;
      const selected = financials.find(item => item.source_id === source.id && item.snapshot);
      setRun(selected || null); setCorrections(saved); setBackups(archives); setFactId(selected?.snapshot.facts[0]?.id || '');
    }).catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.id, source.symbol]);
  const fact = run?.snapshot.facts.find(item => item.id === factId);
  async function correct() {
    if (!fact || !value || !evidence || !reason) return;
    setBusy('correction'); setError('');
    try {
      await historyApi('/corrections', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify({target_id: fact.id, corrected_value: value, evidence_id: evidence, reason, request_key: crypto.randomUUID()})});
      setValue(''); setEvidence(''); setReason(''); await refresh();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function backup() {
    setBusy('backup'); setError('');
    try {await historyApi('/backups', {method: 'POST', headers: {'X-Graph-Stock': 'local-research'}}); await refresh();}
    catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function verifyRestore(id) {
    setBusy(id); setError(''); setRestore(null);
    try {setRestore(await historyApi(`/backups/${id}/restore`, {method: 'POST', headers: {'X-Graph-Stock': 'local-research'}}));}
    catch(e) {setError(e.message);} finally {setBusy('');}
  }
  return <div className="paper-panel history-panel">
    <p className="eyebrow">CORRECTIONS & RECOVERY</p><h3>Reconstructable research history</h3>
    <p>Corrections supersede current facts without changing earlier reports, feature vintages or simulated fills. Backups contain a consistent SQLite snapshot and every referenced vault artifact.</p>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {run ? <details><summary>Correct a located financial fact</summary><div className="history-form">
      <label>Fact<select value={factId} onChange={e => setFactId(e.target.value)}>{run.snapshot.facts.map(item => <option value={item.id} key={item.id}>{item.label} · {item.period} · {item.value ?? 'missing'} {item.unit}</option>)}</select></label>
      {fact && <p>Original evidence <code>{fact.evidence_id}</code> · PDF page {fact.locator.pdf_page}. The original remains available.</p>}
      <label>Corrected value in {fact?.unit || 'the recorded unit'}<input value={value} maxLength={80} onChange={e => setValue(e.target.value)} placeholder="Enter checked value"/></label>
      <label>Correction evidence ID<input value={evidence} maxLength={240} onChange={e => setEvidence(e.target.value)} placeholder="Example: manual-review:page-189"/></label>
      <label>Reason<input value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} placeholder="What was wrong and how it was checked"/></label>
      <button className="secondary" disabled={busy || !value || !evidence || reason.length < 3} onClick={correct}>{busy === 'correction' ? 'Recording…' : 'Record superseding correction'}</button>
    </div></details> : <p className="muted">Calculate financials first to make located facts available for correction.</p>}
    <div className="correction-list">{corrections.map(item => <article key={item.id}><div><strong>{item.corrected.label} · {item.corrected.period}</strong><span>Version {item.version} · {time(item.created_at)}</span></div><p><code>{item.previous.value}</code> → <code>{item.corrected.value} {item.corrected.unit}</code></p><p>{item.reason}</p><small>{item.impacts.filter(x => x.disposition === 'stale').length} current artifact(s) marked stale · earlier records preserved</small><a href={`/api/v1/history/corrections/${item.id}/note`} target="_blank" rel="noreferrer">Read correction note</a></article>)}</div>
    <div className="backup-head"><div><h4>Verified local backups</h4><p>Create a ZIP with database snapshots, referenced notes and SHA-256 manifest.</p></div><button className="secondary" onClick={backup} disabled={Boolean(busy)}>{busy === 'backup' ? 'Backing up…' : 'Create verified backup'}</button></div>
    {restore && <p role="status" className="alert-scan">Restore verified in an isolated folder: {restore.database_count} database(s), {restore.artifact_count} artifact(s).</p>}
    <div className="backup-list">{backups.map(item => <article key={item.id}><div><strong>{time(item.created_at)}</strong><span>{item.manifest.databases.length} DB · {item.manifest.artifacts.length} artifacts · {item.status}</span></div><div><a href={`/api/v1/history/backups/${item.id}/download`}>Download ZIP</a><button className="text-button" disabled={Boolean(busy)} onClick={() => verifyRestore(item.id)}>{busy === item.id ? 'Verifying…' : 'Rehearse restore'}</button></div></article>)}</div>
  </div>;
}

function ImprovementReview() {
  const blank = {repository_url:'', revision:'', release:'', license:'', relevance:'', change_summary:'', compatibility:'', expected_benefit:'', source_link:'', change_sha256:''};
  const [items, setItems] = useState([]), [config, setConfig] = useState(null), [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [reason, setReason] = useState('');
  async function refresh() {
    const [saved, policy] = await Promise.all([improvementApi(''), improvementApi('/config')]);
    setItems(saved); setConfig(policy);
  }
  useEffect(() => {let live = true; Promise.all([improvementApi(''), improvementApi('/config')]).then(([saved, policy]) => {if (live) {setItems(saved); setConfig(policy);}}).catch(e => live && setError(e.message)); return () => {live = false;};}, []);
  async function submit() {
    setBusy('submit'); setError('');
    try {
      const candidate = {...form, source_links:[form.source_link]}; delete candidate.source_link;
      await improvementApi('/monitor', {method:'POST', headers:{'Content-Type':'application/json','X-Graph-Stock':'local-research'}, body:JSON.stringify({candidates:[candidate]})});
      setForm(blank); await refresh();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function action(item, name, body) {
    setBusy(item.id + name); setError('');
    try {
      await improvementApi(`/${item.id}/${name}`, {method:'POST', headers:{'Content-Type':'application/json','X-Graph-Stock':'local-research'}, body:body ? JSON.stringify(body) : undefined});
      if (name === 'decision') setReason('');
      await refresh();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  const complete = form.repository_url && form.revision && form.license && form.relevance && form.change_summary && form.compatibility && form.expected_benefit && form.source_link && form.change_sha256.length === 64;
  return <div className="paper-panel improvement-panel">
    <p className="eyebrow">UPSTREAM IMPROVEMENT REVIEW</p><h3>Review ideas without applying code</h3>
    <p>Every proposal keeps its repository, commit, license, expected benefit and exact change fingerprint. A changed fingerprint cancels any earlier approval.</p>
    {config && <p className="manifest-line">Policy <code>{config.policy_version}</code> · discovery capped at {config.discovery_limit} candidates per check · {config.whitelist.length} allowlisted repositories.</p>}
    {error && <p role="alert" className="note-warning">{error}</p>}
    <details><summary>Add a monitored or discovered candidate</summary><div className="improvement-form">
      <label>GitHub repository<input type="url" value={form.repository_url} onChange={e => setForm({...form,repository_url:e.target.value})} placeholder="https://github.com/owner/repository"/></label>
      <label>Exact commit ID<input value={form.revision} maxLength={64} onChange={e => setForm({...form,revision:e.target.value})}/></label>
      <label>Release, if any<input value={form.release} maxLength={100} onChange={e => setForm({...form,release:e.target.value})}/></label>
      <label>License<input value={form.license} maxLength={100} onChange={e => setForm({...form,license:e.target.value})} placeholder="Example: MIT"/></label>
      <label>Relevant change<input value={form.change_summary} maxLength={2000} onChange={e => setForm({...form,change_summary:e.target.value})}/></label>
      <label>Why it matters<input value={form.relevance} maxLength={1000} onChange={e => setForm({...form,relevance:e.target.value})}/></label>
      <label>Compatibility implications<input value={form.compatibility} maxLength={1000} onChange={e => setForm({...form,compatibility:e.target.value})}/></label>
      <label>Expected benefit<input value={form.expected_benefit} maxLength={1000} onChange={e => setForm({...form,expected_benefit:e.target.value})}/></label>
      <label>Source or commit link<input type="url" value={form.source_link} onChange={e => setForm({...form,source_link:e.target.value})}/></label>
      <label>SHA-256 of the exact change<input value={form.change_sha256} maxLength={64} onChange={e => setForm({...form,change_sha256:e.target.value})}/></label>
      <button className="secondary" disabled={!complete || Boolean(busy)} onClick={submit}>{busy === 'submit' ? 'Recording…' : 'Record candidate'}</button>
    </div></details>
    {!items.length && <p className="muted">No upstream proposals have been recorded.</p>}
    <div className="improvement-list">{items.map(item => <article key={item.id} className={item.state}>
      <div className="improvement-head"><strong>{item.repository_url.replace('https://github.com/','')}</strong><span>{item.state.replaceAll('-',' ')}</span></div>
      <p>{item.change_summary}</p><small>{item.license} · commit <code>{item.revision.slice(0,12)}</code> · {item.source_kind}</small>
      <details><summary>Evidence and exact identity</summary><p>{item.relevance}</p><p><strong>Compatibility:</strong> {item.compatibility}</p><p><strong>Benefit:</strong> {item.expected_benefit}</p><code>{item.fingerprint}</code>{item.tests.map(test => <p key={test.id}>{test.passed ? 'Passed' : 'Failed'} · {test.summary}</p>)}{item.decisions.map(decision => <p key={decision.id}>{decision.decision} · {decision.reason}{decision.invalidated_at ? ' · invalidated by changed content' : ''}</p>)}</details>
      <div className="improvement-actions"><a href={`/api/v1/improvements/${item.id}/report`} target="_blank" rel="noreferrer">Read local report</a>
        {item.state === 'discovered' && <button className="text-button" disabled={Boolean(busy)} onClick={() => action(item,'assess')}>Assess metadata</button>}
        {item.state === 'assessed' && <button className="text-button" disabled={Boolean(busy)} onClick={() => action(item,'test',{profile:'isolated-regression'})}>Run isolated test</button>}
      </div>
      {item.state === 'awaiting-approval' && <div className="approval-row"><label>Decision reason<input value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} placeholder="Record why the exact tested change is accepted or rejected"/></label><button className="secondary" disabled={reason.length < 3 || Boolean(busy)} onClick={() => action(item,'decision',{fingerprint:item.fingerprint,decision:'approved',reason})}>Approve exact change</button><button className="text-button" disabled={reason.length < 3 || Boolean(busy)} onClick={() => action(item,'decision',{fingerprint:item.fingerprint,decision:'rejected',reason})}>Reject</button></div>}
    </article>)}</div>
  </div>;
}

function UpdateGraph({source}) {
  const [runs, setRuns] = useState([]), [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef(null);
  async function refresh(id = run?.id) {
    if (id) setRun(await updateApi('/' + id));
    const rows = (await updateApi('')).filter(item => item.symbol === source.symbol);
    setRuns(rows);
    if (!id && rows[0]) setRun(rows[0]);
  }
  useEffect(() => {
    let live = true;
    updateApi('').then(rows => {
      if (!live) return;
      const matching = rows.filter(item => item.symbol === source.symbol);
      setRuns(matching); setRun(matching[0] || null);
    }).catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.symbol]);
  useEffect(() => {
    if (!active(run)) return;
    const timer = setTimeout(() => refresh(run.id).catch(e => setError(e.message)), 700);
    return () => clearTimeout(timer);
  }, [run]);
  async function start() {
    setBusy(true); setError('');
    if (request.current?.source_id !== source.id) request.current = {source_id: source.id, request_key: crypto.randomUUID()};
    try {
      const value = await updateApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(request.current)});
      request.current = null; setRun(value);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function action(name) {
    setBusy(true); setError('');
    try {setRun(await updateApi('/' + run.id + '/' + name, {method: 'POST', headers: {'X-Graph-Stock': 'local-research'}}));}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  return <div className="update-panel">
    <p className="eyebrow">DEPENDENCY-AWARE REFRESH</p><h3>Refresh only what changed</h3>
    <p>The graph checkpoints each step in SQLite. Matching evidence and version fingerprints reuse accepted work.</p>
    <div className="financial-actions"><button className="secondary" onClick={start} disabled={busy || active(run)}>Run research refresh</button>
      {run?.status === 'running' && <button className="text-button" onClick={() => action('cancel')} disabled={busy}>Cancel after the current step</button>}
      {['failed','partial','cancelled'].includes(run?.status) && <button className="text-button" onClick={() => action('resume')} disabled={busy}>Resume from checkpoint</button>}</div>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {runs.length > 1 && <label>Update history<select value={run?.id || ''} onChange={e => setRun(runs.find(item => item.id === e.target.value))}>{runs.map(item => <option key={item.id} value={item.id}>{time(item.created_at)} · {item.status}</option>)}</select></label>}
    {run && <><p role="status"><strong>{run.status}</strong> · {run.message}</p>
      {run.predecessor_id && <p className="successor">Successor to <code>{run.predecessor_id}</code></p>}
      <div className="node-list">{run.nodes.map(node => <div key={node.name}><span className={'node-dot ' + node.status}/><strong>{node.name.replaceAll('_', ' ')}</strong><small>{node.status}{node.reused_from ? ` · reused from ${node.reused_from.slice(0, 8)}` : ''}</small>{node.fingerprint && <code>{node.fingerprint.slice(0, 12)}</code>}</div>)}</div>
      {run.result?.report && <div className="note-links"><a href={'/api/v1/updates/' + run.id + '/report'} target="_blank" rel="noreferrer">Read refresh report</a><a href={'/api/v1/updates/' + run.id + '/report?download=true'}>Download .md ↓</a></div>}
      {run.result?.snapshot?.specialists && <><h4>Business and moat research</h4><div className="specialist-grid">{run.result.snapshot.specialists.map(item => <article key={item.kind}>
        <span>{item.kind.replaceAll('_', ' ')}</span><strong>{item.rating}</strong><p>{item.summary}</p>
        <small>{item.source_periods.join(' · ')}</small>
        <a href={'/api/v1/updates/' + run.id + '/specialists/' + item.kind} target="_blank" rel="noreferrer">Read evidence report</a>
      </article>)}</div></>}
      {run.result?.snapshot?.event_research && <><h4>Earnings, management, valuation and risk</h4><div className="specialist-grid">{run.result.snapshot.event_research.map(item => <article key={item.kind}>
        <span>{item.kind.replaceAll('_', ' ')}</span><strong>{item.rating}</strong><p>{item.summary}</p>
        <small>{item.source_periods.join(' · ')}</small>
        <a href={'/api/v1/updates/' + run.id + '/research/' + item.kind} target="_blank" rel="noreferrer">Read research report</a>
      </article>)}</div></>}
      {run.result?.complete_snapshot && <div className="complete-snapshot">
        <p className="eyebrow">COMPLETE RESEARCH SNAPSHOT</p>
        <div className="score-head"><div><strong>{run.result.complete_snapshot.overall_score}</strong><span>overall score / 100</span></div><div><strong>{run.result.complete_snapshot.evidence_completeness_percent}%</strong><span>evidence completeness</span></div><div><strong>{run.result.complete_snapshot.research_confidence}</strong><span>research confidence</span></div></div>
        <p>{run.result.complete_snapshot.fundamental_view}</p>
        <div className="score-grid">{run.result.complete_snapshot.category_scores.map(item => <article key={item.name} className={item.status === 'unscored' ? 'unscored' : ''}>
          <span>{item.name.replaceAll('_', ' ')}</span><strong>{item.score === null ? 'Unscored' : item.score}</strong><small>{item.weight_percent}% weight · {item.rationale}</small>
        </article>)}</div>
        <div className="debate-grid"><article><h4>Bull case</h4>{run.result.debate.bull.claims.map(item => <p key={item.claim_id}>+ {item.text}</p>)}</article><article><h4>Bear case</h4>{run.result.debate.bear.claims.map(item => <p key={item.claim_id}>− {item.text}</p>)}</article></div>
        <p><strong>Judge:</strong> {run.result.debate.judge.adjudication}</p>
        <h4>Investment thesis</h4>{run.result.complete_snapshot.thesis_points.map(item => <p key={item}>• {item}</p>)}
        <div className="trading-state"><span>Swing status: <strong>{run.result.complete_snapshot.swing_status.state}</strong><small>{run.result.complete_snapshot.swing_status.reason}</small></span><span>Validation: <strong>{run.result.complete_snapshot.validation_status.state}</strong><small>{run.result.complete_snapshot.validation_status.reason}</small></span></div>
        <p className="missing-line">Missing evidence: {run.result.complete_snapshot.missing_evidence.join(' · ').replaceAll('_', ' ')}</p>
        <div className="note-links">{['bull','bear','judge','investment_thesis','scorecard'].map(kind => <a key={kind} href={`/api/v1/updates/${run.id}/synthesis/${kind}`} target="_blank" rel="noreferrer">{kind.replaceAll('_', ' ')} report</a>)}</div>
        <small>{run.result.complete_snapshot.confidence_meaning}</small>
      </div>}
      {run.result?.management_claim_history?.length > 0 && <details><summary>Management claim history</summary>{run.result.management_claim_history.slice(-6).map((item, index) => <p key={item.run_id + item.claim.claim_id + index}><strong>{item.state.status}</strong> · {item.claim.text}<small>{item.state.observed_period} · target {item.claim.target_period}</small></p>)}</details>}
      {run.result?.snapshot && <p className="partial-result">Partial/final result: {run.result.snapshot.metrics.length} deterministic metrics remain available.</p>}
    </>}
  </div>;
}

function Financials({source}) {
  const [runs, setRuns] = useState([]), [run, setRun] = useState(null);
  const [error, setError] = useState(''), [note, setNote] = useState(null), [busy, setBusy] = useState(false);
  const request = useRef(null);
  useEffect(() => {
    let live = true;
    financialApi('').then(rows => {
      if (!live) return;
      const matching = rows.filter(item => item.source_id === source.id);
      setRuns(matching); setRun(matching[0] || null);
    }).catch(e => live && setError(e.message));
    return () => {live = false;};
  }, [source.id]);
  useEffect(() => {
    if (!active(run)) return;
    const timer = setTimeout(async () => {
      try {
        const value = await financialApi('/' + run.id);
        setRun(value);
        if (!active(value)) setRuns((await financialApi('')).filter(item => item.source_id === source.id));
      } catch(e) {setError(e.message);}
    }, 700);
    return () => clearTimeout(timer);
  }, [run, source.id]);
  async function start(useReasoning) {
    setBusy(true); setError(''); setNote(null);
    const mode = useReasoning ? 'reasoning' : 'local';
    if (request.current?.mode !== mode) request.current = {mode, request_key: crypto.randomUUID()};
    try {
      const value = await financialApi('', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'},
        body: JSON.stringify({source_id: source.id, request_key: request.current.request_key, use_reasoning: useReasoning})});
      request.current = null; setRun(value);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  const snapshot = run?.snapshot;
  return <div className="financial-panel">
    <p className="eyebrow">TRACEABLE FINANCIALS</p><h3>Located facts and checked calculations</h3>
    <p>Extraction and formulas run locally. The default action uses no reasoning allowance.</p>
    <div className="financial-actions"><button className="secondary" disabled={busy || active(run)} onClick={() => start(false)}>Calculate financials locally</button>
      {snapshot && <button className="text-button" disabled={busy || active(run)} onClick={() => start(true)}>Add optional AI interpretation · uses signed-in allowance</button>}</div>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {runs.length > 1 && <label>Saved financial runs<select value={run?.id || ''} onChange={e => {setRun(runs.find(item => item.id === e.target.value)); setNote(null);}}>{runs.map(item => <option value={item.id} key={item.id}>{time(item.created_at)} · {item.use_reasoning ? 'with interpretation' : 'local only'}</option>)}</select></label>}
    {run && <p role="status"><strong>{run.status}</strong> · {run.message}</p>}
    {snapshot && <>
      <div className="financial-metrics">{snapshot.metrics.map(metric => <article key={metric.id} className={metric.value === null ? 'unavailable' : ''}><span>{metric.label}</span><strong>{displayMetric(metric)}</strong><small>{metric.period} · {metric.scope}</small></article>)}</div>
      <p className="interpretation-state"><strong>AI interpretation:</strong> {run.interpretation.message}</p>
      {run.interpretation.status === 'completed' && <div className="interpretation"><p>{run.interpretation.result.summary}</p>{run.interpretation.result.observations.map((item, index) => <p key={index}>• {item.text} <code>{item.metric_ids.join(', ')}</code></p>)}</div>}
      <details><summary>Inspect facts, locations and formulas</summary>
        <table><thead><tr><th>Fact</th><th>Period</th><th>Value</th><th>Evidence location</th></tr></thead><tbody>{snapshot.facts.map(fact => <tr key={fact.id}><td>{fact.label}</td><td>{fact.period}</td><td>{fact.value === null ? `Unavailable · ${fact.missing_reason}` : `₹${Number(fact.value).toLocaleString('en-IN')} crore`}<small>Reported: {fact.reported_value} lakh</small></td><td>PDF p. {fact.locator.pdf_page}<small>{fact.scope} · {fact.locator.statement}</small></td></tr>)}</tbody></table>
        <h4>Formula lineage</h4>{snapshot.metrics.map(metric => <p key={metric.id}><strong>{metric.label}</strong>: {metric.formula}<br/><code>{metric.input_fact_ids.join(' · ')}</code></p>)}</details>
      {run.note.available && <div className="note-links"><button className="text-button" onClick={async () => {try {const response = await fetch('/api/v1/financials/' + run.id + '/note'); if (!response.ok) throw new Error('Financial note is unavailable.'); setNote(await response.text());} catch(e) {setError(e.message);}}}>Read financial note</button><a href={'/api/v1/financials/' + run.id + '/note?download=true'}>Download .md ↓</a></div>}
      {note && <pre>{note}</pre>}
    </>}
  </div>;
}
export default function Filings() {
  const [symbol, setSymbol] = useState('BEL'), [name, setName] = useState('');
  const [file, setFile] = useState(null), [available, setAvailable] = useState('');
  const [jobs, setJobs] = useState([]), [run, setRun] = useState(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [note, setNote] = useState(null);
  const key = useRef(null);
  useEffect(() => {
    let live = true;
    api('').then(rows => {if (live) {setJobs(rows); setRun(rows[0] || null);}}).catch(e => live && setError(e.message));
    return () => {live = false;};
  }, []);
  useEffect(() => {
    if (!active(run)) return;
    const timer = setTimeout(async () => {
      try {setRun(await api('/' + run.id)); setJobs(await api(''));}
      catch(e) {setError(e.message);}
    }, 1000);
    return () => clearTimeout(timer);
  }, [run]);
  function changed(setter, value) {setter(value); key.current = null;}
  async function submit(manual = false) {
    setBusy(true); setError(''); setNote(null);
    const mode = manual ? 'manual' : 'automatic';
    if (key.current?.mode !== mode) key.current = {mode, id: crypto.randomUUID()};
    try {
      let path = '', body, headers = {'X-Graph-Stock': 'local-research'};
      if (manual) {
        if (!file || file.size > 25000000) throw new Error('Choose a PDF no larger than 25 MB.');
        const params = new URLSearchParams({symbol, name, filename: file.name, request_key: key.current.id});
        if (available) params.set('available_date', available);
        path = '/import?' + params; body = file; headers['Content-Type'] = 'application/pdf';
      } else {body = JSON.stringify({symbol, request_key: key.current.id}); headers['Content-Type'] = 'application/json';}
      setRun(await api(path, {method: 'POST', headers, body}));
      key.current = null; setJobs(await api(''));
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function retry() {
    setBusy(true); setError('');
    try {setRun(await api('/' + run.id + '/retry', {method: 'POST', headers: {'X-Graph-Stock': 'local-research'}}));}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  const source = run?.source;
  return <section className="card filings" aria-label="Real public filings">
    <p className="eyebrow">REAL PUBLIC SOURCES</p><h2>Collect a company filing</h2>
    <p>Automatic coverage: BEL annual report 2024–25, a historical sample. Other NSE equity tickers support identity lookup and manual PDF import.</p>
    <form onSubmit={e => {e.preventDefault(); submit();}}>
      <label>NSE ticker <input required maxLength={30} value={symbol} onChange={e => changed(setSymbol, e.target.value.toUpperCase())}/></label>
      <button className="secondary" disabled={busy || active(run)}>Fetch filing</button>
    </form>
    <details><summary>Import a PDF when a source is missing</summary>
      <p>Use the correct company’s public filing. If NSE is unavailable, the company identity remains explicitly unverified. A supplied public date is recorded as your assertion.</p>
      <label>Company name (for offline identification)<input maxLength={200} value={name} onChange={e => changed(setName, e.target.value)}/></label>
      <label>Public availability date, if known<input type="date" value={available} onChange={e => changed(setAvailable, e.target.value)}/></label>
      <label>PDF, up to 25 MB<input type="file" accept="application/pdf,.pdf" onChange={e => changed(setFile, e.target.files[0])}/></label>
      <button className="secondary" disabled={!file || busy || active(run)} onClick={() => submit(true)}>Import PDF</button>
    </details>
    {error && <p role="alert" className="note-warning">{error}</p>}
    {busy && <p role="status">Submitting filing request…</p>}
    {jobs.length > 0 && <label>Recent filing requests<select value={run?.id || ''} onChange={e => {setRun(jobs.find(j => j.id === e.target.value)); setNote(null);}}>{jobs.map(j => <option key={j.id} value={j.id}>{j.request.symbol} · {time(j.created_at)} · {j.status}</option>)}</select></label>}
    {run && <div role="status"><p><strong>{run.status}</strong> · {run.result.message || 'Retrieving the public source…'}</p>
      {run.result.security && <p>{run.result.security.name} · {run.result.security.isin || 'ISIN unknown'} · {run.result.security.verification}</p>}
      {!active(run) && !['success','unchanged'].includes(run.status) && <button className="secondary" disabled={busy} onClick={retry}>Retry acquisition / publication</button>}
      {run.result.missing?.map(gap => <p key={gap}>○ {gap.includes('Financial extraction pending GS-04') ? 'Financial extraction is a separate explicit action below' : gap.includes('Historical feature eligibility deferred until GS-04') ? 'Historical feature eligibility remains deferred until point-in-time features are built' : gap}</p>)}
      {run.result.attempts?.length > 0 && <details><summary>Source attempts</summary>{run.result.attempts.map((a,i) => <p key={i}>{a.status} · {a.url}</p>)}</details>}
    </div>}
    {source && <div className="filing-evidence"><h3>{source.title}</h3><p>{source.pages} pages · Source parser: PDF validated</p>
      <p>Origin: {source.origin.startsWith('https://') ? <a href={source.origin} target="_blank" rel="noreferrer">{source.origin}</a> : source.origin}</p>
      <p>Retrieved: {time(source.retrieved_at)} IST · Public availability: {source.public_available_at ? time(source.public_available_at) + ' IST' : 'unknown'} ({source.availability_basis})</p>
      <p>Evidence location: original PDF, pages 1–{source.pages}. Financial facts keep their exact statement-page locations.</p>
      <code>SHA-256: {source.sha256}</code>
      <div className="note-links"><a href={'/api/v1/filings/sources/' + source.id + '/pdf'}>Download original PDF ↓</a>
      <button className="text-button" onClick={async () => {try {const r = await fetch('/api/v1/filings/sources/' + source.id + '/note'); if (!r.ok) throw new Error('Evidence note unavailable. Check the vault and retry.'); setNote(await r.text());} catch(e) {setError(e.message);}}}>Read evidence note</button></div>
      <p>Obsidian vault: {source.note_path}</p>{note && <pre>{note}</pre>}
      <Financials source={source}/>
      <Ownership source={source}/>
      <NewsCatalysts source={source}/>
      <MarketData source={source}/>
      <FeatureSnapshots source={source}/>
      <Backtests source={source}/>
      <StrategyValidation source={source}/>
      <PaperBook source={source}/>
      <CombinedBook source={source}/>
      <ScheduleStatus source={source}/>
      <AlertCenter source={source}/>
      <ResearchHistory source={source}/>
      <UpdateGraph source={source}/>
    </div>}
    <ImprovementReview/>
  </section>;
}
