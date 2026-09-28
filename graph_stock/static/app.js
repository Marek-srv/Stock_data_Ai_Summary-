const $ = id => document.getElementById(id);
let current = null;
let submitting = false;
let requestKey = null;
const active = status => ["queued", "running"].includes(status);
async function api(path, options = {}) {
  const response = await fetch(path, {cache: "no-store", ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
  return data;
}
function show(run) {
  current = run;
  $("badge").textContent = run.status.replaceAll("-", " ");
  $("status").textContent = run.message;
  $("start").disabled = submitting || active(run.status);
  $("retry").hidden = active(run.status) || run.status === "completed";
  $("result").hidden = !run.result;
  if (run.result) {
    $("summary").textContent = run.result.summary;
    $("evidence").textContent = run.result.evidence_id + " · synthetic";
    $("growth").textContent = run.result.growth_display;
  }
  $("details").hidden = false;
  $("metadata").textContent = JSON.stringify({request: run.id, client_version: run.version, auth: run.auth_method, attempts: run.attempts, usage: run.usage, updated: run.updated_at}, null, 2);
}
async function refresh() {
  try {
    const runs = await api("/api/diagnostics");
    $("empty").hidden = runs.length > 0;
    $("history").replaceChildren();
    for (const run of runs) {
      const button = document.createElement("button");
      button.textContent = run.status.replaceAll("-", " ");
      const date = document.createElement("span");
      date.textContent = new Date(run.created_at).toLocaleString();
      button.append(date);
      button.onclick = () => show(run);
      $("history").append(button);
    }
    if (!current && runs.length) show(runs[0]);
    else if (current) {
      const updated = runs.find(run => run.id === current.id);
      show(updated || await api(`/api/diagnostics/${current.id}`));
    }
  } catch (error) { $("status").textContent = "Application unavailable. Your saved checks will return when it restarts."; }
}
async function submit(retry = false) {
  submitting = true;
  $("start").disabled = true;
  $("retry").disabled = true;
  if (!requestKey) requestKey = crypto.randomUUID();
  try {
    const path = retry ? `/api/diagnostics/${current.id}/retry` : "/api/diagnostics";
    const run = await api(path, {method: "POST", headers: {"Content-Type": "application/json", "X-Graph-Stock": "local-diagnostic"}, ...(retry ? {} : {body: JSON.stringify({request_key: requestKey})})});
    requestKey = null;
    show(run);
    await refresh();
  } catch (error) { $("status").textContent = error.message; }
  finally { submitting = false; $("start").disabled = !!current && active(current.status); $("retry").disabled = false; }
}
$("start").onclick = () => submit();
$("retry").onclick = () => submit(true);
refresh();
setInterval(refresh, 2000);
