// Results page — renders whatever the upload page stored right before it
// navigated here. If nothing is stored (direct link, page refresh after
// clearing storage, etc.), we show the empty state instead of a blank page.

const RESULT_STORAGE_KEY = "dd:last-result";
const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };

const els = {
  emptyState: document.querySelector("#empty-state"),
  result: document.querySelector("#result"),
  caseId: document.querySelector("#case-id"),
  generatedAt: document.querySelector("#generated-at"),
  decisionCard: document.querySelector("#decision-card"),
  decision: document.querySelector("#decision"),
  decisionRationale: document.querySelector("#decision-rationale"),
  riskBadge: document.querySelector("#risk-badge"),
  transactionCount: document.querySelector("#transaction-count"),
  segmentsCount: document.querySelector("#segments-count"),
  riskLevel: document.querySelector("#risk-level"),
  summary: document.querySelector("#summary"),
  mitigatingSection: document.querySelector("#mitigating-section"),
  mitigatingFactors: document.querySelector("#mitigating-factors"),
  findings: document.querySelector("#findings"),
  findingsCount: document.querySelector("#findings-count"),
  limitations: document.querySelector("#limitations"),
  reportHtmlLink: document.querySelector("#report-html-link"),
  reportJsonLink: document.querySelector("#report-json-link"),
};

init();

function init() {
  const raw = sessionStorage.getItem(RESULT_STORAGE_KEY);
  const data = raw ? safeParse(raw) : null;

  if (!data) {
    els.emptyState.classList.remove("hidden");
    els.result.classList.add("hidden");
    return;
  }

  renderResult(data);
  els.emptyState.classList.add("hidden");
  els.result.classList.remove("hidden");
}

function safeParse(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function renderResult(data) {
  els.caseId.textContent = data.case_id;
  els.generatedAt.textContent = data.generated_at
    ? `Generated ${new Date(data.generated_at).toLocaleString()}`
    : "";

  els.decisionCard.className = `decision-card risk-${data.risk_level}`;
  els.decision.textContent = formatEnum(data.decision);
  els.decisionRationale.textContent = data.decision_rationale;

  els.riskBadge.textContent = `${data.risk_level.toUpperCase()} RISK`;
  els.riskBadge.className = `risk-badge risk-${data.risk_level}`;

  els.transactionCount.textContent = data.transactions_processed.toLocaleString();
  els.segmentsCount.textContent = data.chunks_processed.toLocaleString();
  els.riskLevel.textContent = data.risk_level.toUpperCase();

  els.summary.textContent = data.executive_summary;

  renderMitigatingFactors(data.mitigating_factors || []);
  renderFindings(data.findings || []);

  els.limitations.innerHTML = (data.limitations || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("") || "<li class='muted'>None recorded.</li>";

  els.reportHtmlLink.href = data.report_html;
  els.reportJsonLink.href = data.report_json;
}

function renderMitigatingFactors(factors) {
  if (!factors.length) {
    els.mitigatingSection.classList.add("hidden");
    return;
  }

  els.mitigatingSection.classList.remove("hidden");
  els.mitigatingFactors.innerHTML = factors
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}

function renderFindings(findings) {
  els.findingsCount.textContent = findings.length
    ? `${findings.length} finding${findings.length === 1 ? "" : "s"}`
    : "";

  if (!findings.length) {
    els.findings.innerHTML =
      "<p class='muted'>No material finding with verified transaction evidence was returned.</p>";
    return;
  }

  const sorted = [...findings].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
  );

  els.findings.innerHTML = sorted
    .map((finding) => {
      const evidenceItems = finding.evidence
        .map(
          (item) => `
            <li>
              <span class="transaction-ids">${escapeHtml(item.transaction_ids.join(", "))}</span>
              <span>${escapeHtml(item.statement)}</span>
            </li>`
        )
        .join("");

      return `
        <article class="finding severity-${escapeHtml(finding.severity)}">
          <div class="finding-header">
            <h4>${escapeHtml(formatEnum(finding.category))}</h4>
            <span class="severity ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span>
          </div>
          <p>${escapeHtml(finding.rationale)}</p>
          <p class="confidence">Model confidence: ${Math.round(finding.confidence * 100)}%</p>
          <h5>Verified evidence</h5>
          <ul>${evidenceItems}</ul>
        </article>`;
    })
    .join("");
}

function formatEnum(value) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = value ?? "";
  return element.innerHTML;
}
