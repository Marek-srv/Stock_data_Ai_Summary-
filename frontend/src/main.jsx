import React, {useCallback, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import Filings from './Filings';
import Discovery from './Discovery';

async function api(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || 'The request could not be completed.');
    error.candidates = detail?.candidates || [];
    throw error;
  }
  return data;
}
const post = body => ({method: 'POST', headers: {'Content-Type': 'application/json', 'X-Graph-Stock': 'local-research'}, body: JSON.stringify(body)});
const date = value => new Date(value).toLocaleString('en-IN', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata'});
const money = value => Number(value).toLocaleString('en-IN', {maximumFractionDigits: 2});

function Icon({name, size = 20}) {
  const paths = {
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
    book: <><path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4zM13 7a3 3 0 0 1 3-3h5v15h-5a4 4 0 0 0-3 2"/></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    leaf: <><path d="M19 4C8 2 3 7 5 14s13 7 14-10Z"/><path d="m5 20 10-11"/></>,
    link: <><path d="M10 13a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-2 2M14 11a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l2-2"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.book}</svg>;
}

function App() {
  const [watchlist, setWatchlist] = useState([]);
  const [booting, setBooting] = useState(true);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get('run'));
  const [run, setRun] = useState(null);
  const [error, setError] = useState('');
  const [candidates, setCandidates] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [loadingRun, setLoadingRun] = useState(false);
  const [revision, setRevision] = useState(0);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState(null);
  const [noteError, setNoteError] = useState('');
  const request = useRef(null);
  const refreshing = useCallback(async () => {
    const data = await api('/api/watchlist');
    setWatchlist(data);
    return data;
  }, []);

  useEffect(() => {
    let active = true;
    refreshing().then(data => {
      if (active && !new URLSearchParams(location.search).get('run') && data[0]?.runs[0]) setSelected(data[0].runs[0].id);
    }).catch(e => active && setError(e.message)).finally(() => active && setBooting(false));
    return () => {active = false;};
  }, [refreshing]);

  useEffect(() => {
    if (!selected) return;
    let active = true, timer;
    setLoadingRun(true);
    setRun(null);
    setNoteOpen(false);
    setNote(null);
    const url = new URL(location.href);
    url.searchParams.set('run', selected);
    history.replaceState(null, '', url);
    async function load() {
      try {
        const value = await api(`/api/research/${selected}`);
        if (!active) return;
        setRun(value);
        setLoadingRun(false);
        if (value.status === 'publishing') timer = setTimeout(load, 350);
        else await refreshing();
      } catch (e) { if (active) {setError(e.message); setLoadingRun(false);} }
    }
    load();
    return () => {active = false; clearTimeout(timer);};
  }, [selected, refreshing, revision]);

  useEffect(() => {
    if (!noteOpen || !selected) return;
    let active = true;
    setNote(null); setNoteError('');
    fetch(`/api/research/${selected}/note`).then(async r => {
      if (!r.ok) throw new Error('The note is unavailable in the configured vault. Your saved snapshot is still here.');
      return r.text();
    }).then(text => active && setNote(text)).catch(e => active && setNoteError(e.message));
    return () => {active = false;};
  }, [noteOpen, selected]);

  function select(id) {setError(''); setCandidates([]); setSelected(id);}
  async function research(value = query) {
    if (!value.trim() || submitting) return;
    setSubmitting(true); setError(''); setCandidates([]);
    const normalized = value.trim().toUpperCase();
    if (request.current?.query !== normalized) request.current = {query: normalized, request_key: crypto.randomUUID()};
    try {
      const value = await api('/api/research', post(request.current));
      request.current = null;
      setQuery('');
      select(value.id);
      await refreshing();
    } catch (e) {setError(e.message); setCandidates(e.candidates || []);}
    finally {setSubmitting(false);}
  }
  async function retry() {
    setSubmitting(true); setError('');
    try {
      const value = await api(`/api/research/${selected}/retry`, post({}));
      setRun(value);
      // Re-enter polling without creating another research run.
      setRevision(value => value + 1);
    } catch (e) {setError(e.message);}
    finally {setSubmitting(false);}
  }
  const snapshot = run?.snapshot;
  const currentCompany = watchlist.find(item => item.id === snapshot?.security.security_id);
  const hasNote = run && run.note.integrity !== 'unavailable';

  return <div className="shell">
    <aside className="sidebar">
      <a href="/" className="brand"><span className="brand-icon"><Icon name="leaf"/></span>graph_stock<span className="brand-dot">.</span></a>
      <p className="side-label">WORKSPACE</p>
      <div className="nav-active"><Icon name="book"/> Research library <span>{watchlist.length}</span></div>
      <a className="nav-link" href="/diagnostic"><Icon name="link"/> Connection check</a>
      <div className="watch-heading"><p className="side-label">YOUR WATCHLIST</p><span className="small-count">{watchlist.length}</span></div>
      {booting ? <p className="side-empty">Loading your library…</p> : watchlist.length === 0 ? <p className="side-empty">Research a fixture stock to start your watchlist.</p> :
        <div className="watchlist">{watchlist.map(company => <button key={company.id} className={`watch-row ${snapshot?.security.security_id === company.id ? 'selected' : ''}`} onClick={() => select(company.runs[0].id)} aria-pressed={snapshot?.security.security_id === company.id}>
          <span className="ticker-icon">{company.symbol.slice(0, 2)}</span><span><strong>{company.symbol}</strong><small>{company.runs.length} saved {company.runs.length === 1 ? 'snapshot' : 'snapshots'}</small></span><span className="watch-dot"/>
        </button>)}</div>}
      <div className="side-bottom"><span className="local-dot"/> Local workspace<p>Your research stays on this device.<br/>This build uses synthetic test data.</p></div>
    </aside>
    <main>
      <div className="topbar"><span>Workspace <span className="slash">/</span> <strong>Research library</strong></span><span className="pill demo">SOURCE COLLECTION + FIXTURES</span></div>
      <header><p className="eyebrow">FROM QUESTION TO RESEARCH MEMORY</p><h1>Your research,<br className="mobile-break"/> kept in view.</h1><p className="intro">Find a company, save a snapshot, and pick up where you left off.</p></header>
      <Discovery onQueued={id=>{refreshing();select(id);}}/>
      <Filings/>
      <section aria-label="Stock search" className="search-section">
        <form onSubmit={e => {e.preventDefault(); research();}} className="search-form"><Icon name="search"/><label className="sr-only" htmlFor="search">NSE ticker or company name</label><input id="search" value={query} maxLength={80} onChange={e => setQuery(e.target.value)} placeholder="NSE ticker or company name" autoComplete="off"/><button className="primary" disabled={!query.trim() || submitting}>{submitting ? 'Saving…' : 'Research fixture'}<Icon name="arrow" size={17}/></button></form>
        <div className="search-hint"><span>Available fixtures</span>{['HAL', 'BEL', 'BHEL'].map(symbol => <button key={symbol} onClick={() => research(symbol)} disabled={submitting}>{symbol}<span>↗</span></button>)}</div>
        {submitting && <p role="status" className="progress-line">Resolving the fixture and saving your research…</p>}
        {error && <div className="error" role="alert"><strong>Research needs your attention</strong><p>{error}</p>{candidates.length > 0 && <div className="candidate-list">{candidates.map(c => <button key={c.security_id} onClick={() => research(c.symbol)}><strong>{c.symbol}</strong><span>{c.name}</span><Icon name="arrow" size={16}/></button>)}</div>}</div>}
      </section>
      <div className="demo-banner"><span className="demo-mark">i</span><p><strong>Synthetic test data.</strong> Company names identify fixtures only. Figures below are made up; no live research or trading signals are available.</p></div>
      {(booting || loadingRun) && <section className="empty-card" role="status"><div className="loading-orbit"/><h2>{booting ? 'Opening your research library' : 'Retrieving your saved snapshot'}</h2><p>Reading the local research record.</p></section>}
      {!booting && !loadingRun && !run && <section className="empty-card"><div className="empty-illustration"><div className="paper-lines"><Icon name="book" size={34}/><span/><span/><span/></div><span className="empty-plus">+</span></div><p className="eyebrow">A PLACE FOR YOUR FIRST IDEA</p><h2>Your library starts with one company.</h2><p>Try HAL to see a saved fixture snapshot, its evidence<br className="desktop-break"/> and a dated research note ready for Obsidian.</p><button className="secondary" onClick={() => research('HAL')} disabled={submitting}>Explore the HAL fixture <Icon name="arrow" size={17}/></button><div className="empty-features"><span><Icon name="check" size={15}/>Saved locally</span><span><Icon name="check" size={15}/>Evidence included</span><span><Icon name="check" size={15}/>Reopens after restart</span></div></section>}
      {!loadingRun && snapshot && <>
        <section className="snapshot-head"><div><div className="company-line"><span className="exchange">NSE</span><h2>{snapshot.security.symbol}</h2><span className="pill fixture">FIXTURE</span></div><p>{snapshot.security.name}</p></div><div className="saved-meta"><span className={`status-tag ${run.status !== 'completed' ? 'pending' : ''}`}><Icon name={run.status === 'completed' ? 'check' : 'book'} size={14}/>{run.status === 'completed' ? 'Saved locally' : run.status === 'publishing' ? 'Publishing note' : 'Note needs attention'}</span><small>{date(run.created_at)}</small></div></section>
        <div className="snapshot-tools"><span>Research snapshot <span className="muted">· Synthetic sample</span></span>{currentCompany?.runs.length > 1 && <select aria-label="Saved snapshot" value={selected || ''} onChange={e => select(e.target.value)}>{currentCompany.runs.map((r, i) => <option value={r.id} key={r.id}>{i === 0 ? 'Latest · ' : ''}{date(r.created_at)} · {r.id.slice(0, 6)}</option>)}</select>}</div>
        {run.status !== 'completed' && <div className="run-message" role="status"><span>{run.message}</span>{run.status !== 'publishing' && <button className="text-button" onClick={retry} disabled={submitting}>Retry note publication</button>}</div>}
        <div className="metric-grid">{snapshot.metrics.map(metric => <article className="metric" key={metric.id}><span>{metric.label}</span><strong>{metric.unit === 'INR crore' ? `₹${money(metric.value)}` : money(metric.value)}<small>{metric.unit === 'INR crore' ? 'Cr' : '%'}</small></strong><p>{metric.period} <span>· fixture</span></p></article>)}</div>
        <div className="research-grid"><section className="card overview"><p className="eyebrow">RESEARCH OVERVIEW</p><h3>A saved example, not a company view.</h3><p>{snapshot.summary}</p><div className="coverage"><span>Real research coverage</span><strong>Not assessed</strong></div><div className="missing"><p>Waiting for future research stages</p>{snapshot.missing.map(item => <div key={item}><span>○</span>{item}</div>)}</div></section>
          <section className="card note-card"><span className="note-icon"><Icon name="book" size={28}/></span><p className="eyebrow">RESEARCH MEMORY</p><h3>Your dated note is {hasNote ? 'ready.' : run.status === 'publishing' ? 'pending.' : 'unavailable.'}</h3><p>A Markdown record of this snapshot, its evidence and calculations.</p>{run.note.integrity === 'modified' && <p className="note-warning">The note has been edited since publication. Your changes are preserved.</p>}
          <button className="secondary" disabled={!hasNote} onClick={() => setNoteOpen(!noteOpen)}>{noteOpen ? 'Hide note' : 'Read research note'}<Icon name="arrow" size={16}/></button>
          {hasNote && <div className="note-links"><a href={run.note.obsidian_uri}>Open in Obsidian ↗</a><a href={`/api/research/${run.id}/note?download=true`}>Download .md ↓</a></div>}<small>Open the configured test-vault folder in Obsidian first. The note is readable here without it.</small></section></div>
        {noteOpen && <section className="card note-preview" aria-label="Research note"><h3>Saved research note</h3>{noteError ? <p role="alert">{noteError}</p> : note === null ? <p role="status">Opening the note…</p> : <pre>{note}</pre>}</section>}
        <section className="card evidence" id="evidence"><div className="section-heading"><div><p className="eyebrow">TRACEABLE BY DESIGN</p><h3>Evidence & calculations</h3></div><span className="pill">{snapshot.evidence.length} FIXTURE SOURCE</span></div>{snapshot.evidence.map(item => <div className="source-row" key={item.id}><span className="source-icon"><Icon name="book"/></span><div><strong>{item.title}</strong><p>{item.locator} · Synthetic, version {item.version}</p><code>{item.id}</code></div><span className="source-label">BUNDLED TEST DATA</span></div>)}<details><summary>Inspect the calculation lineage</summary><table><thead><tr><th>Metric</th><th>Deterministic calculation</th></tr></thead><tbody>{snapshot.metrics.map(m => <tr key={m.id}><td>{m.label}</td><td>{m.formula}</td></tr>)}</tbody></table><p className="lineage-facts">Input facts: revenue A = 1,000; revenue B = 1,200; operating profit B = 180 (INR crore). These are synthetic values.</p></details></section>
        <p className="record-id">Snapshot {run.id} · {snapshot.schema_version}</p>
      </>}
      <footer><span><span className="local-dot"/> Local storage · SQLite + Markdown</span><span>Checkpointed refresh reuses matching work.</span></footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
