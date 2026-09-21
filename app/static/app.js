const form = document.querySelector("#analysis-form");
const fileInput = document.querySelector("#file");
const fileName = document.querySelector("#file-name");

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name ?? "No file selected";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = fileInput.files[0];
  if (!file) return;

  const payload = new FormData();
  payload.append("file", file);

  try {
    const response = await fetch("/v1/transactions/analyze-file", {
      method: "POST",
      body: payload
    });

    const body = await response.json();

    if (!response.ok) {
      throw new Error(body.detail || "Statement analysis failed.");
    }

    renderResult(body);
  } catch (error) {
    alert(error.message);
  }
});

function renderResult(data) {
  document.querySelector("#decision").textContent =
    data.decision.replaceAll("_", " ").toUpperCase();

  document.querySelector("#decision-rationale").textContent =
    data.decision_rationale;

  document.querySelector("#summary").textContent =
    data.executive_summary;

  document.querySelector("#transaction-count").textContent =
    data.transactions_processed.toLocaleString();

  document.querySelector("#credit-total").textContent =
    data.chunks_processed.toLocaleString();

  document.querySelector("#debit-total").textContent =
    data.risk_level.toUpperCase();

  const findings = document.querySelector("#findings");
  findings.innerHTML = "";

  data.findings.forEach((finding) => {
    findings.insertAdjacentHTML("beforeend", `
      <article class="finding">
        <h4>${escapeHtml(finding.category)}</h4>
        <p>${escapeHtml(finding.rationale)}</p>
        <ul>
          ${finding.evidence.map((item) => `
            <li>
              <strong>${escapeHtml(item.transaction_ids.join(", "))}</strong>:
              ${escapeHtml(item.statement)}
            </li>
          `).join("")}
        </ul>
      </article>
    `);
  });

  if (!data.findings.length) {
    findings.innerHTML = "<p class='muted'>No material finding with verified transaction evidence was returned.</p>";
  }

  const links = `
    <p class="report-links">
      <a href="${data.report_html}" target="_blank">Open saved report</a>
      <a href="${data.report_json}" target="_blank">Download JSON</a>
    </p>
  `;

  findings.insertAdjacentHTML("beforeend", links);
  const limitations = document.querySelector("#limitations");
  limitations.innerHTML = data.limitations
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  document.querySelector("#result-status").textContent =
    `${data.transactions_processed.toLocaleString()} transactions reviewed across ${data.chunks_processed} LLM segments.`;
  document.querySelector("#result").classList.remove("hidden");
}

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = value;
  return element.innerHTML;
}
