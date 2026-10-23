// Upload page, "Read from folder": review accounts straight from the server folder.
//
// The folder is fixed on the server (ACCOUNT_FOLDER_PATH); staff choose a range of its files, by file
// name: from 1 to 5 is the first five, from 6 to 10 the next five. They are queued as one batch and
// followed on the same results page as an upload. The option is hidden when no folder is set.

const DEFAULT_RANGE_SIZE = 5; // a small first run; change "To file" for more

const folderEls = {
  switchBar: document.querySelector("#source-switch"),
  switchButtons: document.querySelectorAll(".source-option"),
  uploadForm: document.querySelector("#upload-form"),
  folderForm: document.querySelector("#folder-form"),
  loading: document.querySelector("#folder-loading"),
  panel: document.querySelector("#folder-panel"),
  path: document.querySelector("#folder-path"),
  total: document.querySelector("#folder-total"),
  start: document.querySelector("#range-start"),
  end: document.querySelector("#range-end"),
  countHint: document.querySelector("#count-hint"),
  error: document.querySelector("#folder-error"),
  submit: document.querySelector("#folder-submit"),
  submitLabel: document.querySelector("#folder-submit-label"),
};

const folderState = { loaded: false, summary: null };

showSwitchWhenFolderIsSet();
folderEls.switchButtons.forEach((button) => button.addEventListener("click", () => showSource(button.dataset.source)));
folderEls.start.addEventListener("input", updateRange);
folderEls.end.addEventListener("input", updateRange);
folderEls.folderForm.addEventListener("submit", startFolderBatch);

async function showSwitchWhenFolderIsSet() {
  const health = await fetch("/healthz").then((response) => response.json()).catch(() => null);
  folderEls.switchBar.classList.toggle("hidden", !health?.folder_configured);
}

function showSource(source) {
  folderEls.switchButtons.forEach((button) => {
    const active = button.dataset.source === source;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  folderEls.uploadForm.classList.toggle("hidden", source !== "upload");
  folderEls.folderForm.classList.toggle("hidden", source !== "folder");
  if (source === "folder" && !folderState.loaded) loadFolder();
}

async function loadFolder() {
  folderState.loaded = true;
  folderEls.loading.classList.remove("hidden");
  try {
    const response = await fetch("/v1/folder");
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.detail || `Could not read the folder (HTTP ${response.status}).`);
    folderState.summary = body;
    folderEls.path.textContent = body.folder;
    folderEls.total.textContent = String(body.total_files);
    folderEls.start.value = "1";
    folderEls.end.value = String(Math.min(DEFAULT_RANGE_SIZE, body.total_files));
    folderEls.panel.classList.remove("hidden");
    updateRange();
  } catch (error) {
    folderState.loaded = false; // switching back to the folder tab tries again
    showFolderError(error.message || "Could not read the folder.");
  } finally {
    folderEls.loading.classList.add("hidden");
  }
}

function chosenRange() {
  return { start: Number.parseInt(folderEls.start.value, 10), end: Number.parseInt(folderEls.end.value, 10) };
}

function updateRange() {
  const available = folderState.summary?.total_files ?? 0;
  for (const input of [folderEls.start, folderEls.end]) input.max = String(Math.max(available, 1));
  const { start, end } = chosenRange();
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && start <= end && end <= available;
  folderEls.submit.disabled = !valid;
  if (!available) {
    folderEls.countHint.textContent = "The folder has no CSV, TSV or Parquet files.";
  } else if (!valid) {
    folderEls.countHint.textContent = `Enter a range within 1 to ${available}, with "From" no bigger than "To".`;
  } else {
    const count = end - start + 1;
    const atOnce = folderState.summary.accounts_at_once;
    folderEls.countHint.textContent = `Files ${start} to ${end} of ${available}, by file name: ${count} `
      + `account${count === 1 ? "" : "s"}, reviewed ${atOnce} at a time.`;
  }
  clearFolderError();
}

async function startFolderBatch(event) {
  event.preventDefault();
  folderEls.submit.disabled = true;
  folderEls.submitLabel.textContent = "Queuing…";
  try {
    const response = await fetch("/v1/folder-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(chosenRange()),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(typeof body?.detail === "string" ? body.detail : `Could not start (HTTP ${response.status}).`);
    }
    window.location.href = `/results?batch=${encodeURIComponent(body.batch_id)}`;
  } catch (error) {
    showFolderError(error.message || "Could not start the review.");
    folderEls.submit.disabled = false;
    folderEls.submitLabel.textContent = "Start review";
  }
}

function showFolderError(message) {
  folderEls.error.textContent = message;
  folderEls.error.classList.remove("hidden");
}

function clearFolderError() {
  folderEls.error.classList.add("hidden");
  folderEls.error.textContent = "";
}
