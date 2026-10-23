// Results page: /results?batch=<id>&page=<n>
//
// The batch is polled until every file has finished. One report per page: when a file is done its report
// is fetched once (GET /v1/reports/<id>) and drawn here, in the order an analyst works (the same order as
// the saved HTML report). Each part is a card whose title says who wrote it: "AI" (the AI's text, shown as
// written) or "Exact" (computed from the file by code). Every value is escaped before it is put on the page.

const POLL_MS = 5000;
const FILE_STATUS_LABELS = { queued: "Waiting", reviewing: "Reviewing", done: "Ready", failed: "Failed" };
const RISK_LABELS = { low: "LOW RISK", medium: "MEDIUM RISK", high: "HIGH RISK", not_assessed: "RISK NOT ASSESSED" };
const CHECK_LABELS = { found: "Found", not_found: "Not found", cannot_check: "Cannot check", not_reported: "Not reported" };
const STRENGTH_TONE = { strong: "high", moderate: "medium", weak: "low" };

const els = {
  batchBar: document.querySelector("#batch-bar"),
  position: document.querySelector("#batch-position"),
  file: document.querySelector("#batch-file"),
  fileStatus: document.querySelector("#batch-file-status"),
  progress: document.querySelector("#batch-progress"),
  prev: document.querySelector("#prev-report"),
  next: document.querySelector("#next-report"),
  placeholder: document.querySelector("#placeholder"),
  placeholderText: document.querySelector("#placeholder-text"),
  placeholderLink: document.querySelector("#placeholder-link"),
  report: document.querySelector("#report"),
};

// reports: report id -> report JSON, so paging back is instant. shown: the report id on the page now.
const state = { id: null, data: null, page: 1, reports: new Map(), shown: null, loading: null };

const params = new URLSearchParams(window.location.search);
if (params.get("batch")) {
  state.id = params.get("batch");
  state.page = Number.parseInt(params.get("page"), 10) || 1;
  els.placeholderLink.classList.add("hidden");
  els.placeholderText.textContent = "Loading…";
  els.prev.addEventListener("click", () => goToPage(state.page - 1));
  els.next.addEventListener("click", () => goToPage(state.page + 1));
  poll();
}

// --- the batch ---------------------------------------------------------------------------------

async function poll() {
  try {
    const response = await fetch(`/v1/batches/${encodeURIComponent(state.id)}`);
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      showPlaceholder(body?.detail || `Could not load this batch (HTTP ${response.status}).`, true);
      return;
    }
    state.data = body;
    state.page = Math.min(Math.max(state.page, 1), body.total);
    showPage();
    if (!body.finished) setTimeout(poll, POLL_MS);
  } catch {
    setTimeout(poll, POLL_MS); // a dropped connection should not stop the page
  }
}

function goToPage(page) {
  if (!state.data || page < 1 || page > state.data.total) return;
  state.page = page;
  const url = new URL(window.location.href);
  url.searchParams.set("page", String(page));
  window.history.replaceState(null, "", url);
  showPage();
  window.scrollTo({ top: 0 });
}

function showPage() {
  const { data, page } = state;
  const file = data.files[page - 1];
  els.batchBar.classList.remove("hidden");
  els.position.textContent = `Report ${page} of ${data.total}`;
  els.file.textContent = file.file_name;
  els.fileStatus.textContent = FILE_STATUS_LABELS[file.status] || file.status;
  els.fileStatus.className = `file-status status-${file.status === "reviewing" ? "analysing" : file.status}`;
  els.prev.disabled = page <= 1;
  els.next.disabled = page >= data.total;

  const c = data.counts;
  els.progress.textContent = data.finished
    ? `All ${data.total} files finished: ${c.done} ready, ${c.failed} failed.`
    : `${c.done} ready · ${c.reviewing} reviewing · ${c.queued} waiting · ${c.failed} failed. `
      + `${data.accounts_at_once} account${data.accounts_at_once === 1 ? " is" : "s are"} reviewed at a time.`;
  els.progress.classList.remove("hidden");

  if (file.status !== "done") {
    state.shown = null;
    showPlaceholder(file.status === "failed" ? `This file could not be reviewed: ${file.error}`
      : file.status === "reviewing" ? "Reviewing this account now. The report appears here when it is ready."
        : "Waiting in the queue. It starts when the files before it have started.");
    return;
  }
  const report = state.reports.get(file.report_id);
  if (!report) {
    loadReport(file.report_id);
    return;
  }
  if (state.shown !== file.report_id) { // draw once, so polling does not reset the page
    els.report.innerHTML = renderReport(report);
    state.shown = file.report_id;
  }
  els.placeholder.classList.add("hidden");
  els.report.classList.remove("hidden");
}

async function loadReport(reportId) {
  if (state.loading === reportId) return;
  state.loading = reportId;
  showPlaceholder("Loading this report…");
  try {
    const response = await fetch(`/v1/reports/${encodeURIComponent(reportId)}`);
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.detail || `Could not load this report (HTTP ${response.status}).`);
    state.reports.set(reportId, body);
  } catch (error) {
    showPlaceholder(error.message || "Could not load this report.");
    return;
  } finally {
    state.loading = null;
  }
  showPage();
}

function showPlaceholder(text, withLink = false) {
  els.report.classList.add("hidden");
  els.placeholderText.textContent = text;
  els.placeholderLink.classList.toggle("hidden", !withLink);
  els.placeholder.classList.remove("hidden");
}

// --- one report ---------------------------------------------------------------------------------

function renderReport(r) {
  return [
    meta(r), verdict(r), glance(r),
    card("Account story", ["ai"], `<p class="check-insight">${esc(r.account_story) || muted("Not available.")}</p>`),
    verifyFirst(r), questions(r), findings(r), checklist(r), months(r), rejected(r), limitations(r),
    toolUses(r), processing(r), links(r),
  ].join("");
}

function meta(r) {
  return `<div class="results-meta"><div><p class="eyebrow">Account file</p><h1>${esc(r.file_name)}</h1></div>
    <p class="results-generated">Generated ${esc(r.generated_at.slice(0, 16).replace("T", " "))} UTC</p></div>
    <p class="report-legend"><span>${tags(["ai"])} written by the AI</span>
      <span>${tags(["exact"])} computed from the file</span></p>`;
}

function verdict(r) {
  return `<section class="decision-card risk-${esc(r.risk_level)}">
    <div class="decision-main">
      <div class="decision-head"><p class="eyebrow">AI assessment</p>
        <span class="risk-badge risk-${esc(r.risk_level)}">${RISK_LABELS[r.risk_level] || esc(r.risk_level)}</span></div>
      <h2>${esc(r.headline)}</h2>
      <p class="decision-note"><strong>Why this risk level:</strong> ${esc(r.risk_reason)}</p>
      ${problems(r)}
      <p class="section-hint">The AI's assessment supports the analyst. The analyst decides what action to take.</p>
    </div>
    <div class="decision-stats">
      <div><span>Period</span><strong>${esc(r.period_start)}<br>to ${esc(r.period_end)}</strong></div>
      <div><span>Transactions</span><strong>${num(r.transactions)}</strong></div>
      <div><span>Evidence</span><strong>${esc(r.evidence_strength)}</strong></div>
      <div><span>Findings</span><strong>${r.findings.length}</strong></div>
    </div></section>`;
}

// An incomplete review says what failed right under the verdict, so the analyst sees it first.
function problems(r) {
  const failed = r.calls.filter((c) => c.status === "failed");
  if (r.status !== "incomplete" && !failed.length) return "";
  const items = failed.map((c) => `<li><strong>${esc(c.step)}:</strong> ${esc(c.problem)}</li>`).join("");
  return `<div class="problem-box"><strong>Part of this review was not done.</strong> Do not rely on this report
    alone; see Limitations and Processing below, and the app log for the details.${items ? `<ul>${items}</ul>` : ""}</div>`;
}

function glance(r) {
  const g = r.glance;
  const quiet = /^(.*) \((\d+ days?)\)$/.exec(g.longest_quiet || "");
  const tiles = [
    ["Money in", `RM ${rm(g.total_in)}`, `${num(g.count_in)} credits`],
    ["Money out", `RM ${rm(g.total_out)}`, `${num(g.count_out)} debits`],
    ["In minus out", `RM ${rm(g.in_minus_out)}`, "over the whole period"],
    ["Transactions", num(g.transactions), `on ${g.active_days} of ${g.days_in_period} days`],
    ["Largest credit", g.largest_in ? `RM ${rm(g.largest_in.amount)}` : "None", g.largest_in ? `${g.largest_in.tid} · ${g.largest_in.date}` : ""],
    ["Largest debit", g.largest_out ? `RM ${rm(g.largest_out.amount)}` : "None", g.largest_out ? `${g.largest_out.tid} · ${g.largest_out.date}` : ""],
    ["Longest quiet spell", quiet ? quiet[2] : (g.longest_quiet || "None"), quiet ? quiet[1] : ""],
    ["Last credit", g.last_credit || "None",
      g.months_without_activity.length ? `No activity in ${g.months_without_activity.join(", ")}` : "Active every month"],
  ];
  return card("Account at a glance", ["exact"], `<div class="glance-grid">${tiles.map(([label, value, detail]) =>
    `<div class="glance-tile"><span class="glance-label">${esc(label)}</span>
      <span class="glance-value" title="${esc(value)}">${esc(value)}</span>
      ${detail ? `<span class="glance-detail">${esc(detail)}</span>` : ""}</div>`).join("")}</div>`);
}

function verifyFirst(r) {
  if (!r.verify_first.length) return "";
  const items = r.verify_first.map((item) => `<li class="verify-item"><p>${esc(item.action)}</p>${issues(item.issues)}
    ${item.transactions.length ? txnTable(item.transactions, 5) : ""}</li>`).join("");
  return card("What to verify first", ["ai"], `<ol class="verify-list">${items}</ol>`);
}

function questions(r) {
  if (!r.customer_questions.length) return "";
  return card("Questions for the customer or relationship manager", ["ai"],
    `<ol class="question-list">${r.customer_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ol>`);
}

function findings(r) {
  const body = r.findings.length ? r.findings.map(findingCard).join("")
    : `<p>${muted("No pattern was confirmed against the transactions.")}</p>`;
  return card("Findings", ["ai", "exact"], body, `${r.findings.length} confirmed`,
    "The AI's explanation, then the exact figures and transactions behind each finding.");
}

function findingCard(f) {
  const fig = f.figures;
  const part = (title, text) => text ? `<div class="finding-part"><h5>${title}</h5><p>${esc(text)}</p></div>` : "";
  const chips = [
    `<strong>${num(fig.count)}</strong> transactions`,
    `${esc(fig.first_date)} to ${esc(fig.last_date)} (${fig.days} days)`,
    `In <strong>RM ${rm(fig.total_in)}</strong> (${fig.count_in})`,
    `Out <strong>RM ${rm(fig.total_out)}</strong> (${fig.count_out})`,
    ...(fig.out_share_of_in === null ? [] : [`Out is <strong>${esc(fig.out_share_of_in)}%</strong> of in`]),
  ];
  return `<article class="finding-card">
    <div class="check-head"><h4>${esc(f.finding_id)} · ${esc(f.title)}</h4>
      <span class="severity ${STRENGTH_TONE[f.strength] || "low"}">${esc(f.strength)} evidence</span></div>
    <div class="finding-parts">${part("What happened", f.what_happened)}${part("Why it matters", f.why_it_matters)}
      ${part("Ordinary explanation", f.ordinary_explanation)}${part("What to verify", f.what_to_verify)}</div>
    ${issues(f.issues)}
    <div class="figure-row">${chips.map((c) => `<span class="figure-chip">${c}</span>`).join("")}</div>
    ${txnTable(f.transactions, 12)}</article>`;
}

function checklist(r) {
  const rows = r.checklist.map((c) => `<tr><td class="text-cell">${esc(c.title)}</td>
    <td class="text-cell"><span class="status-chip ${esc(c.status)}">${CHECK_LABELS[c.status] || esc(c.status)}</span></td>
    <td class="text-cell">${esc(c.note)}</td></tr>`).join("");
  return card("Pattern checklist", ["ai"], table(["Pattern", "Result", "Note"], rows, [0, 1, 2]), "",
    "Every pattern the AI was asked to look for, and what this data cannot show.");
}

function months(r) {
  const rows = r.months.map((m) => `<tr${m.note ? ' class="has-note"' : ""}><td>${esc(m.month)}</td>
    <td>${num(m.count)}</td><td>${rm(m.total_in)}</td><td>${m.count_in}</td><td>${rm(m.total_out)}</td><td>${m.count_out}</td>
    <td class="text-cell">${esc(m.note)}</td></tr>`).join("");
  return card("Monthly timeline", ["exact", "ai"],
    table(["Month", "Transactions", "In, RM", "Credits", "Out, RM", "Debits", "AI note"], rows, [6]), "",
    "The figures are exact; the notes are the AI's, on the months that stand out (highlighted).");
}

function rejected(r) {
  if (!r.rejected.length) return "";
  return card("Considered and rejected", ["ai"], `<ul class="question-list">${r.rejected.map((x) =>
    `<li><strong>${esc(x.title)}:</strong> ${esc(x.reason)}</li>`).join("")}</ul>`);
}

function limitations(r) {
  const count = r.issues.length ? ` · ${r.issues.length} issue${r.issues.length === 1 ? "" : "s"} found by the checks` : "";
  const found = r.issues.length ? issues(r.issues) : "";
  return `<section class="report-card"><details ${r.issues.length || r.status === "incomplete" ? "open" : ""}>
    <summary>Limitations${count}</summary><ul class="question-list">${r.limitations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    ${found}</details></section>`;
}

function toolUses(r) {
  if (!r.tool_uses.length) return "";
  const rows = r.tool_uses.map((t) => `<tr><td class="text-cell">${esc(t.step)}</td><td class="text-cell">${esc(t.tool)}</td>
    <td class="text-cell"><code>${esc(t.asked)}</code></td><td class="text-cell"><code>${esc(t.answer)}</code></td></tr>`).join("");
  return `<section class="report-card"><details><summary>What the AI checked
    (${r.tool_uses.length} tool use${r.tool_uses.length === 1 ? "" : "s"})</summary>
    ${table(["Step", "Tool", "Asked", "Answer (first line)"], rows, [0, 1, 2, 3])}</details></section>`;
}

function processing(r) {
  const failed = r.calls.filter((c) => c.status === "failed").length;
  // The "Problem" column only when a call failed, so the table fits the page otherwise.
  const rows = r.calls.map((c) => `<tr${c.status === "failed" ? ' class="call-failed"' : ""}>
    <td class="text-cell">${esc(c.step)}</td><td>${c.status === "answered" ? "Answered" : "Failed"}</td>
    <td>${c.seconds}</td><td>${c.requests}</td><td>${c.tool_uses}</td><td>${num(c.output_tokens)}</td>
    ${failed ? `<td class="text-cell">${esc(c.problem)}</td>` : ""}</tr>`).join("");
  const head = ["Step", "Status", "Seconds", "Requests", "Tool uses", "Output tokens", ...(failed ? ["Problem"] : [])];
  const summary = `${r.total_seconds} s · ${r.calls.length} AI calls · ${r.groups} group${r.groups === 1 ? "" : "s"}`
    + (failed ? ` · ${failed} failed` : "");
  return `<section class="report-card"><details ${failed ? "open" : ""}><summary>Processing · ${summary}</summary>
    ${table(head, rows, failed ? [0, 6] : [0])}</details></section>`;
}

function links(r) {
  return `<section class="report-card actions-row">
    <a class="report-link" href="/reports/${encodeURIComponent(r.report_id)}.html" target="_blank" rel="noopener">Open full report</a>
    <a class="report-link report-link-secondary" href="/reports/${encodeURIComponent(r.report_id)}.json" target="_blank" rel="noopener">Download JSON</a>
  </section>`;
}

// --- helpers ------------------------------------------------------------------------------------

// A report card: title, who wrote it, an optional count on the right and an optional note under the title.
function card(title, sources, body, count = "", note = "") {
  return `<section class="report-card"><div class="report-card-head">
    <div class="report-card-title"><h3>${esc(title)}</h3>${tags(sources)}</div>
    ${count ? `<span class="findings-count">${esc(count)}</span>` : ""}</div>
    ${note ? `<p class="report-card-note">${esc(note)}</p>` : ""}${body}</section>`;
}

function tags(sources) {
  const names = { ai: "AI", exact: "Exact" };
  return `<span class="source">${sources.map((s) => `<span class="source-tag ${s}">${names[s]}</span>`).join("")}</span>`;
}

// Transactions, the first `openUpTo` shown and the rest behind a "Show the other ..." link.
function txnTable(rows, openUpTo) {
  const line = (t) => `<tr><td>${esc(t.tid)}</td><td>${esc(t.date)}</td><td>${t.seq}</td>
    <td>${t.direction === "C" ? "In" : "Out"}</td><td>${rm(t.amount)}</td></tr>`;
  const head = ["ID", "Date", "Seq", "In / out", "Amount, RM"];
  const shown = table(head, rows.slice(0, openUpTo).map(line).join(""));
  if (rows.length <= openUpTo) return shown;
  const rest = rows.length - openUpTo;
  return `${shown}<details class="limitations"><summary>Show the other ${rest} transaction${rest === 1 ? "" : "s"}</summary>
    ${table(head, rows.slice(openUpTo).map(line).join(""))}</details>`;
}

// textColumns: the columns holding words (left-aligned, wrapping); the others are figures.
function table(head, rows, textColumns = []) {
  const th = head.map((h, i) => `<th${textColumns.includes(i) ? ' class="text-cell"' : ""}>${esc(h)}</th>`).join("");
  return `<div class="table-wrap"><table class="evidence-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function issues(list) {
  if (!list || !list.length) return "";
  return `<div class="check-issues"><strong>Check:</strong><ul>${list.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>`;
}

function muted(text) {
  return `<span class="muted">${esc(text)}</span>`;
}

function rm(value) {
  return Number(value).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function num(value) {
  return Number(value).toLocaleString("en-MY");
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
