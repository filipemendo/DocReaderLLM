const state = {
  documents: [],
  activeDocument: null,
};

const els = {
  urlForm: document.querySelector("#url-form"),
  urlInput: document.querySelector("#url-input"),
  fileInput: document.querySelector("#file-input"),
  documentList: document.querySelector("#document-list"),
  documentTitle: document.querySelector("#document-title"),
  documentMeta: document.querySelector("#document-meta"),
  reader: document.querySelector("#reader"),
  openSource: document.querySelector("#open-source"),
  selectionText: document.querySelector("#selection-text"),
  chatLog: document.querySelector("#chat-log"),
  chatForm: document.querySelector("#chat-form"),
  questionInput: document.querySelector("#question-input"),
  providerSelect: document.querySelector("#provider-select"),
  modelInput: document.querySelector("#model-input"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // Keep the status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function loadDocuments() {
  const payload = await api("/api/documents");
  state.documents = payload.documents;
  renderDocumentList();
  if (!state.activeDocument && state.documents.length) {
    openDocument(state.documents[0].id);
  }
}

function renderDocumentList() {
  els.documentList.innerHTML = "";
  state.documents.forEach((doc) => {
    const item = window.document.createElement("button");
    item.type = "button";
    item.className = `document-item ${state.activeDocument?.id === doc.id ? "active" : ""}`;
    item.innerHTML = `
      <div class="document-item-title">${escapeHtml(doc.title)}</div>
      <div class="document-item-meta">${escapeHtml(doc.kind.toUpperCase())} - ${formatCount(doc.text_length)} chars</div>
    `;
    item.addEventListener("click", () => openDocument(doc.id));
    els.documentList.appendChild(item);
  });
}

async function openDocument(documentId) {
  const payload = await api(`/api/documents/${documentId}`);
  state.activeDocument = payload.document;
  renderDocumentList();
  renderDocumentHeader();
  await renderReader(payload.document);
}

function renderDocumentHeader() {
  const doc = state.activeDocument;
  els.documentTitle.textContent = doc ? doc.title : "No document open";
  els.documentMeta.textContent = doc
    ? `${doc.kind.toUpperCase()} - ${doc.source_type}${doc.source_url ? ` - ${doc.source_url}` : ""}`
    : "Import a URL or upload a file to begin.";
  els.openSource.disabled = !doc;
}

async function renderReader(doc) {
  els.reader.className = "reader";
  els.reader.innerHTML = "";

  if (doc.kind === "html" || doc.kind === "text") {
    const frame = window.document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts allow-popups allow-forms");
    frame.src = `/api/documents/${doc.id}/html`;
    els.reader.appendChild(frame);
    return;
  }

  if (doc.kind === "pdf") {
    const frame = window.document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
    frame.src = `/static/pdf_viewer.html?file=${encodeURIComponent(`/api/documents/${doc.id}/file`)}`;
    els.reader.appendChild(frame);
    return;
  }

  if (doc.kind === "epub" && window.ePub) {
    const host = window.document.createElement("div");
    host.id = "epub-viewer";
    host.style.height = "100%";
    els.reader.appendChild(host);
    const book = window.ePub(`/api/documents/${doc.id}/file`);
    const rendition = book.renderTo(host, { width: "100%", height: "100%", spread: "none" });
    rendition.display();
    rendition.on("selected", (_cfiRange, contents) => {
      setSelectionText(contents.window.getSelection().toString());
    });
    return;
  }

  const payload = await api(`/api/documents/${doc.id}/text`);
  const pre = window.document.createElement("pre");
  pre.className = "reader-text";
  pre.textContent = payload.text || "No readable text was extracted.";
  pre.addEventListener("mouseup", captureTopSelection);
  els.reader.appendChild(pre);
}

function captureTopSelection() {
  const text = String(window.getSelection ? window.getSelection() : "").trim();
  if (text) {
    setSelectionText(text);
  }
}

async function importUrl(event) {
  event.preventDefault();
  const url = els.urlInput.value.trim();
  if (!url) return;
  setBusy(event.submitter, true);
  addMessage("user", "Import URL", url);
  try {
    const payload = await api("/api/documents/import-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    els.urlInput.value = "";
    await loadDocuments();
    await openDocument(payload.document.id);
    addMessage("assistant", "Imported", payload.document.title);
  } catch (error) {
    addMessage("error", "Import failed", error.message);
  } finally {
    setBusy(event.submitter, false);
  }
}

async function uploadFile() {
  const file = els.fileInput.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  addMessage("user", "Upload", file.name);
  try {
    const payload = await api("/api/documents/upload", {
      method: "POST",
      body: form,
    });
    els.fileInput.value = "";
    await loadDocuments();
    await openDocument(payload.document.id);
    addMessage("assistant", "Uploaded", payload.document.title);
  } catch (error) {
    addMessage("error", "Upload failed", error.message);
  }
}

async function askQuestion(event) {
  event.preventDefault();
  const doc = state.activeDocument;
  const question = els.questionInput.value.trim();
  if (!doc || !question) return;

  const selectedText = els.selectionText.value.trim();
  const provider = els.providerSelect.value;
  const model = els.modelInput.value.trim();
  els.questionInput.value = "";
  addMessage("user", "Question", question);
  const pending = addMessage("assistant", "Thinking", "Working...");

  try {
    const payload = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: doc.id,
        question,
        selected_text: selectedText,
        provider: provider || null,
        model: model || null,
      }),
    });
    pending.querySelector(".message-meta").textContent = `${payload.provider}${payload.model ? ` - ${payload.model}` : ""}`;
    setMessageBody(pending, payload.answer, true);
  } catch (error) {
    pending.className = "message error";
    pending.querySelector(".message-meta").textContent = "Chat failed";
    setMessageBody(pending, error.message, false);
  }
}

function addMessage(kind, meta, body) {
  const message = window.document.createElement("div");
  message.className = `message ${kind}`;
  message.innerHTML = `
    <div class="message-meta">${escapeHtml(meta)}</div>
    <div class="message-body"></div>
  `;
  setMessageBody(message, body, kind === "assistant");
  els.chatLog.appendChild(message);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
  return message;
}

function setMessageBody(message, body, renderMath) {
  const target = message.querySelector(".message-body");
  target.textContent = body;
  if (renderMath) {
    typesetMath(target);
  }
}

function setSelectionText(rawText) {
  const text = normalizeSelectedText(rawText);
  if (text) {
    els.selectionText.value = text;
  }
}

function normalizeSelectedText(rawText) {
  const text = String(rawText || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .trim();
  if (!text) return "";

  const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  if (lines.length < 3) {
    return text.replace(/[ \t]{2,}/g, " ");
  }

  const fragmentCount = lines.filter(isMathSelectionFragment).length;
  if (fragmentCount / lines.length < 0.35) {
    return text.replace(/[ \t]{2,}/g, " ");
  }

  const merged = [];
  let current = "";
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const next = lines[index + 1] || "";
    const shouldMerge = isMathSelectionFragment(line) || isMathSelectionFragment(next);
    if (!current) {
      current = line;
    } else if (shouldMerge) {
      current += ` ${line}`;
    } else {
      merged.push(current);
      current = line;
    }
  }
  if (current) merged.push(current);

  return merged
    .join("\n\n")
    .replace(/\s+([,.;:)\]}])/g, "$1")
    .replace(/([([{])\s+/g, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function isMathSelectionFragment(line) {
  if (line.length <= 3) return true;
  if (line.length <= 8 && /^[A-Za-z0-9()[\]{}.,;:=+\-*/^_|<>≤≥≈≃≅≠∼∝∈∉⊂⊃⊆⊇∪∩→←↦⇒⇔±∓×÷·⋅∘∑∏∫√∞∂∇∀∃¬∧∨α-ωΑ-Ω]+$/u.test(line)) {
    return true;
  }
  return /^[()[\]{}.,;:=+\-*/^_|<>≤≥≈≃≅≠∼∝∈∉⊂⊃⊆⊇∪∩→←↦⇒⇔±∓×÷·⋅∘∑∏∫√∞∂∇∀∃¬∧∨]+$/u.test(line);
}

function typesetMath(element, attempt = 0) {
  window.setTimeout(() => {
    if (window.MathJax?.typesetPromise) {
      window.MathJax.typesetPromise([element]).catch(() => {});
    } else if (attempt < 20) {
      typesetMath(element, attempt + 1);
    }
  }, attempt ? 150 : 0);
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function formatCount(value) {
  return new Intl.NumberFormat().format(value || 0);
}

window.addEventListener("message", (event) => {
  if (event.data?.type === "reader-selection" && event.data.text) {
    setSelectionText(event.data.text);
  }
});

els.urlForm.addEventListener("submit", importUrl);
els.fileInput.addEventListener("change", uploadFile);
els.chatForm.addEventListener("submit", askQuestion);
els.openSource.addEventListener("click", () => {
  if (state.activeDocument) {
    const path = state.activeDocument.kind === "html" || state.activeDocument.kind === "text"
      ? `/api/documents/${state.activeDocument.id}/html`
      : `/api/documents/${state.activeDocument.id}/file`;
    window.open(path, "_blank", "noopener");
  }
});
window.document.addEventListener("mouseup", captureTopSelection);

loadDocuments().catch((error) => addMessage("error", "Startup failed", error.message));
