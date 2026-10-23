// Upload page: choose one or more account files and queue them.
//
// The files are sent together to /v1/batches. The server reviews a few accounts at a time, in order;
// the results page (/results?batch=...) follows their progress and shows one report per page.

const MAX_UPLOAD_BYTES = 30 * 1024 * 1024; // keep in line with MAX_UPLOAD_BYTES in app/web/routes.py
const FILE_TYPES = [".csv", ".tsv", ".txt", ".parquet"];
const DEFAULT_FILE_HINT = "Drop account files here";

const els = {
  form: document.querySelector("#upload-form"),
  fileInput: document.querySelector("#file"),
  fileField: document.querySelector("#file-field"),
  fileName: document.querySelector("#file-name"),
  fileList: document.querySelector("#file-list"),
  submitButton: document.querySelector("#submit-button"),
  submitButtonLabel: document.querySelector("#submit-button-label"),
  loading: document.querySelector("#loading"),
  error: document.querySelector("#error"),
};

els.fileInput.addEventListener("change", () => filesChosen(els.fileInput.files));
["dragenter", "dragover"].forEach((name) => els.fileField.addEventListener(name, (event) => {
  event.preventDefault();
  els.fileField.classList.add("is-dragging");
}));
["dragleave", "drop"].forEach((name) => els.fileField.addEventListener(name, (event) => {
  event.preventDefault();
  els.fileField.classList.remove("is-dragging");
}));
els.fileField.addEventListener("drop", (event) => {
  const files = event.dataTransfer?.files;
  if (files && files.length) {
    els.fileInput.files = files;
    filesChosen(files);
  }
});
els.form.addEventListener("submit", submit);

// Every problem with the chosen files, as messages for staff (empty when all are fine).
function fileProblems(files) {
  return files.flatMap((file) => {
    if (!FILE_TYPES.some((type) => file.name.toLowerCase().endsWith(type))) {
      return [`"${file.name}" is not a CSV, TSV or Parquet file.`];
    }
    return file.size > MAX_UPLOAD_BYTES ? [`"${file.name}" is larger than the 30 MB limit.`] : [];
  });
}

function filesChosen(fileList) {
  const files = Array.from(fileList || []);
  const problems = fileProblems(files);
  if (!files.length || problems.length) {
    if (problems.length) showError(problems.join(" "));
    els.fileInput.value = "";
    els.fileName.textContent = DEFAULT_FILE_HINT;
    els.fileList.innerHTML = "";
    els.fileList.classList.add("hidden");
    return;
  }
  clearError();
  els.fileName.textContent = files.length === 1 ? files[0].name : `${files.length} files selected`;
  els.fileList.innerHTML = files.map((file) => `<li>${escapeHtml(file.name)}</li>`).join("");
  els.fileList.classList.toggle("hidden", files.length < 2);
}

async function submit(event) {
  event.preventDefault();
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    showError("Choose at least one account file first.");
    return;
  }
  const payload = new FormData();
  files.forEach((file) => payload.append("files", file));
  setBusy(true);
  try {
    const response = await fetch("/v1/batches", { method: "POST", body: payload });
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.detail || `Upload failed (HTTP ${response.status}).`);
    window.location.href = `/results?batch=${encodeURIComponent(body.batch_id)}`;
  } catch (error) {
    showError(error.message || "Upload failed. Please try again.");
    setBusy(false);
  }
}

function setBusy(busy) {
  els.submitButton.disabled = busy;
  els.submitButtonLabel.textContent = busy ? "Uploading…" : "Start review";
  els.loading.classList.toggle("hidden", !busy);
  if (busy) clearError();
}

function showError(message) {
  els.error.textContent = message;
  els.error.classList.remove("hidden");
}

function clearError() {
  els.error.classList.add("hidden");
  els.error.textContent = "";
}

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = value ?? "";
  return element.innerHTML;
}
