import React, {useEffect, useState} from 'react';

const headers = {'Content-Type':'application/json','X-Graph-Stock':'local-research'};
async function api(path, options={}) {
  const response = await fetch('/api/v1/discovery' + path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Candidate discovery could not be completed.');
  return data;
}
async function historyApi(path, options={}) {
  const response = await fetch('/api/v1/bulk-market-history' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Official price history could not be refreshed.');
  return data;
}
async function evidenceApi(path, options={}) {
  const response = await fetch('/api/v1/bulk-evidence' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Official company evidence could not be refreshed.');
  return data;
}

export default function Discovery({onQueued}) {
  const [runs,setRuns]=useState([]), [run,setRun]=useState(null), [history,setHistory]=useState(null), [evidence,setEvidence]=useState(null), [busy,setBusy]=useState(''), [error,setError]=useState('');
  async function refresh(id) {
    const saved=await api(''); setRuns(saved);
    setRun(id ? saved.find(item=>item.id===id) || run : saved[0] || null);
  }
  useEffect(()=>{let live=true; Promise.all([api(''),historyApi(''),evidenceApi('')]).then(([saved,historyRuns,evidenceRuns])=>{if(live){setRuns(saved);setRun(saved[0]||null);setHistory(historyRuns[0]||null);setEvidence(evidenceRuns[0]||null);}}).catch(e=>live&&setError(e.message));return()=>{live=false;};},[]);
  async function screen() {
    setBusy('screen');setError('');
    try {const value=await api('',{method:'POST',headers,body:JSON.stringify({request_key:crypto.randomUUID()})});await refresh(value.id);}
    catch(e){setError(e.message);}finally{setBusy('');}
  }
  async function queue(candidate) {
    setBusy(candidate.security_id);setError('');
    try {const value=await api(`/${run.id}/candidates/${encodeURIComponent(candidate.security_id)}/queue`,{method:'POST',headers,body:JSON.stringify({request_key:crypto.randomUUID()})});await refresh(run.id);onQueued(value.research_run_id);}
    catch(e){setError(e.message);}finally{setBusy('');}
  }
  async function loadHistory() {
    setBusy('history');setError('');
    try {
      let value=await historyApi('',{method:'POST',headers,body:JSON.stringify({request_key:crypto.randomUUID()})});
      setHistory(value);
      while(['queued','running'].includes(value.status)) {
        await new Promise(resolve=>setTimeout(resolve,750));
        value=await historyApi(`/${value.id}`);setHistory(value);
      }
      if(!['completed','partial'].includes(value.status)) throw new Error(value.message||'Official price history did not complete.');
      const screened=await api('',{method:'POST',headers,body:JSON.stringify({request_key:crypto.randomUUID()})});
      await refresh(screened.id);
    } catch(e){setError(e.message);} finally{setBusy('');}
  }
  async function loadEvidence() {
    setBusy('evidence');setError('');
    try {
      let value=await evidenceApi('',{method:'POST',headers,body:JSON.stringify({request_key:crypto.randomUUID(),symbols:['BEL','HAL','BHEL']})});
      setEvidence(value);
      while(['queued','running'].includes(value.status)) {
        await new Promise(resolve=>setTimeout(resolve,750));
        value=await evidenceApi(`/${value.id}`);setEvidence(value);
      }
      if(!['completed','partial'].includes(value.status)) throw new Error(value.message||'Official company evidence did not complete.');
      const screened=await api('',{method:'POST',headers,body:JSON.stringify({request_key:crypto.randomUUID()})});
      await refresh(screened.id);
    } catch(e){setError(e.message);} finally{setBusy('');}
  }
  return <section className="card discovery-panel" aria-label="NSE candidate discovery">
    <div className="discovery-title"><div><p className="eyebrow">NSE DIRECTORY · LOCAL EVIDENCE</p><h2>Find explainable research candidates</h2></div><div className="discovery-actions"><button className="secondary" onClick={loadEvidence} disabled={Boolean(busy)}>{busy==='evidence'?'Loading evidence…':'Load company evidence'}</button><button className="secondary" onClick={loadHistory} disabled={Boolean(busy)}>{busy==='history'?'Loading history…':'Load 64 market sessions'}</button><button className="secondary" onClick={screen} disabled={Boolean(busy)}>{busy==='screen'?'Refreshing…':'Refresh NSE coverage'}</button></div></div>
    <p>The official NSE equity directory defines identity coverage. Rankings use only traceable financial, ownership and adjusted-market evidence already saved locally.</p>
    {history&&<p className={`history-status ${history.status}`}><strong>Official market history: {history.status.replaceAll('-',' ')}</strong> {history.sessions_available!=null?`${history.sessions_available} of ${history.target_sessions} sessions collected.`:history.sessions?`${history.sessions.length} sessions saved; ${history.materialized?.length||0} company histories materialized.`:history.message}</p>}
    {evidence&&<p className={`history-status ${evidence.status}`}><strong>Official company evidence: {evidence.status.replaceAll('-',' ')}</strong> {evidence.completed?`${evidence.completed.length} completed; ${evidence.gaps?.length||0} gaps.`:evidence.completed_count!=null?`${evidence.completed_count} completed; ${evidence.gap_count} gaps.`:evidence.message}</p>}
    {error&&<p className="note-warning" role="alert">{error}</p>}
    {runs.length>1&&<label className="discovery-history">Saved screen<select value={run?.id||''} onChange={e=>setRun(runs.find(item=>item.id===e.target.value))}>{runs.map(item=><option key={item.id} value={item.id}>{item.universe.as_of_date} · {item.candidate_count} candidate(s)</option>)}</select></label>}
    {!run&&<p className="muted">Refresh coverage to inspect eligibility, missing inputs and evidence-backed rankings.</p>}
    {run&&<><div className="discovery-meta"><span><strong>{run.universe.as_of_date}</strong>directory observed</span><span><strong>{run.universe.source_kind.replaceAll('-',' ')}</strong>identity evidence</span><span><strong>{run.candidate_count} / {run.universe.assessed_security_count ?? run.candidate_count+run.excluded.length}</strong>eligible / assessed</span><span><strong>{run.universe.security_count ?? run.candidate_count+run.excluded.length}</strong>directory securities</span></div>
      {run.universe.unassessed_security_count>0&&<p className="coverage-note"><strong>{run.universe.unassessed_security_count.toLocaleString('en-IN')} securities are unassessed.</strong> They have official directory identity but not enough saved local screening evidence, so none silently pass.</p>}
      <div className="candidate-cards">{run.candidates.map(item=><article key={item.security_id}><div className="candidate-rank">#{item.rank}</div><div><strong>{item.symbol} · {item.name}</strong><p>{item.reason}</p><div className="component-scores">{Object.entries(item.components).map(([name,value])=><span key={name}>{name}<strong>{value}</strong></span>)}</div><details><summary>Rules and evidence</summary>{item.metrics.map(metric=><p key={metric.name}><strong>{metric.name.replaceAll('_',' ')}</strong>: {metric.value} {metric.unit}<small>{metric.as_of_date} · {metric.evidence_id}</small></p>)}<code>Overall score {item.score} · {run.policy.version}</code></details></div><button className="secondary" disabled={Boolean(busy)||Boolean(item.queued)} onClick={()=>queue(item)}>{item.queued?'Research queued':busy===item.security_id?'Queueing…':'Queue research'}</button></article>)}</div>
      <details className="excluded-list"><summary>{run.excluded.length} assessed securities excluded with reasons</summary>{run.excluded.map(item=><article key={item.security_id}><strong>{item.symbol}</strong><span>{[...item.failed_rules.map(rule=>`${rule.metric.replaceAll('_',' ')} failed`),...item.missing_metrics.map(metric=>`${metric.metric.replaceAll('_',' ')} missing: ${metric.reason}`)].join(' · ')}</span></article>)}</details>
      <div className="discovery-links"><a href={`/api/v1/discovery/${run.id}/report`} target="_blank" rel="noreferrer">Read screening report</a><span>No orders are created. Eligible selections enter the persistent research queue only.</span></div>
    </>}
  </section>;
}
