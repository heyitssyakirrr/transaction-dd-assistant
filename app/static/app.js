// Transaction Due-Diligence Workspace — upload/analyse workflow.
//
// This file only owns UI state (idle / loading / error / result) and
// rendering. All risk assessment happens server-side.

const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;

const els = {
  form: document.querySelector("#analysis-form"),
  fileInput: document.querySelector("#file"),
  fileField: document.querySelector("#file-field"),
  fileName: document.querySelector("#file-name"),
  submitButton: document.querySelector("#submit-button"),
  submitButtonLabel: document.querySelector("#submit-button-label"),
  resultStatus: document.querySelector("#result-status"),
  loading: document.querySelector("#loading"),
  error: document.querySelector("#error"),
  emptyState: document.querySelector("#empty-state"),
  result: document.querySelector("#result"),
  decision: document.querySelector("#decision"),
  decisionRationale: document.querySelector("#decision-rationale"),
  riskBadge: document.querySelector("#risk-badge"),
  transactionCount: document.querySelector("#transaction-count"),
  segmentsCount: document.querySelector("#segments-count"),
  riskLevel: document.querySelector("#risk-level"),
  summary: document.querySelector("#summary"),
  findings: document.querySelector("#findings"),
  findingsCount: document.querySelector("#findings-count"),
  limitations: document.querySelector("#limitations"),
  reportHtmlLink: document.querySelector("#report-html-link"),
  reportJsonLink: document.querySelector("#report-json-link"),
};

const DEFAULT_FILE_HINT = "Drag a file here or click to browse";

init();

function init() {
  els.fileInput.addEventListener("change", () => {
    handleFileSelected(els.fileInput.files[0]);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    els.fileField.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.fileField.classList.add("is-dragging");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    els.fileField.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.fileField.classList.remove("is-dragging");
    });
  });

  els.fileField.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      els.fileInput.files = event.dataTransfer.files;
      handleFileSelected(file);
    }
  });

  els.form.addEventListener("submit", handleSubmit);
}

function handleFileSelected(file) {
  if (!file) {
    els.fileName.textContent = DEFAULT_FILE_HINT;
    return;
  }

  const isCsv = file.name.toLowerCase().endsWith(".csv");
  if (!isCsv) {
    showError("Please choose a .csv file exported from online banking or a core system.");
    els.fileInput.value = "";
    els.fileName.textContent = DEFAULT_FILE_HINT;
    return;
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    showError(`"${file.name}" is larger than the 15 MB limit for this workspace.`);
    els.fileInput.value = "";
    els.fileName.textContent = DEFAULT_FILE_HINT;
    return;
  }

  clearError();
  els.fileName.textContent = file.name;
}

async function handleSubmit(event) {
  event.preventDefault();

  const file = els.fileInput.files[0];
  if (!file) {
    showError("Choose a CSV statement before running an analysis.");
    return;
  }

  const payload = new FormData();
  payload.append("file", file);

  setBusy(true);

  try {
    const response = await fetch("/v1/transactions/analyze-file", {
      method: "POST",
      body: payload,
    });

    const body = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(body?.detail || `Statement analysis failed (HTTP ${response.status}).`);
    }

    clearError();
    renderResult(body);
  } catch (error) {
    showError(error.message || "Statement analysis failed. Please try again.");
    els.result.classList.add("hidden");
    els.emptyState.classList.remove("hidden");
  } finally {
    setBusy(false);
  }
}

function setBusy(isBusy) {
  els.submitButton.disabled = isBusy;
  els.submitButtonLabel.textContent = isBusy ? "Analysing…" : "Analyse statement";
  els.loading.classList.toggle("hidden", !isBusy);

  if (isBusy) {
    clearError();
    els.result.classList.add("hidden");
    els.emptyState.classList.add("hidden");
    els.resultStatus.textContent = "Segmenting the statement and consulting the model…";
  }
}

function showError(message) {
  els.error.textContent = message;
  els.error.classList.remove("hidden");
}

function clearError() {
  els.error.classList.add("hidden");
  els.error.textContent = "";
}

function renderResult(data) {
  els.emptyState.classList.add("hidden");

  els.decision.textContent = formatEnum(data.decision);
  els.decisionRationale.textContent = data.decision_rationale;

  els.riskBadge.textContent = `${data.risk_level.toUpperCase()} RISK`;
  els.riskBadge.className = `risk-badge risk-${data.risk_level}`;

  els.transactionCount.textContent = data.transactions_processed.toLocaleString();
  els.segmentsCount.textContent = data.chunks_processed.toLocaleString();
  els.riskLevel.textContent = data.risk_level.toUpperCase();

  els.summary.textContent = data.executive_summary;

  renderFindings(data.findings);

  els.limitations.innerHTML = data.limitations
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  els.reportHtmlLink.href = data.report_html;
  els.reportJsonLink.href = data.report_json;

  els.resultStatus.textContent =
    `${data.transactions_processed.toLocaleString()} transactions reviewed across ` +
    `${data.chunks_processed} LLM segment${data.chunks_processed === 1 ? "" : "s"}.`;

  els.result.classList.remove("hidden");
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

  els.findings.innerHTML = findings
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
        <article class="finding">
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