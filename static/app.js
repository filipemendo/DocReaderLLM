const state = {
  documents: [],
  chats: [],
  activeChat: null,
  activeDocument: null,
  chatDrawerOpen: false,
  chatDrawerPinned: false,
};

const els = {
  chatDrawerToggle: document.querySelector("#chat-drawer-toggle"),
  chatDrawer: document.querySelector("#chat-drawer"),
  pinChatDrawer: document.querySelector("#pin-chat-drawer"),
  chatDrawerResizer: document.querySelector("#chat-drawer-resizer"),
  chatDrawerBackdrop: document.querySelector("#chat-drawer-backdrop"),
  chatSearch: document.querySelector("#chat-search"),
  drawerNewChat: document.querySelector("#drawer-new-chat"),
  urlForm: document.querySelector("#url-form"),
  urlInput: document.querySelector("#url-input"),
  fileInput: document.querySelector("#file-input"),
  documentList: document.querySelector("#document-list"),
  addDocuments: document.querySelector("#add-documents"),
  libraryModal: document.querySelector("#library-modal"),
  closeLibrary: document.querySelector("#close-library"),
  librarySearch: document.querySelector("#library-search"),
  libraryList: document.querySelector("#library-list"),
  documentTitle: document.querySelector("#document-title"),
  documentMeta: document.querySelector("#document-meta"),
  reader: document.querySelector("#reader"),
  openSource: document.querySelector("#open-source"),
  chatResizer: document.querySelector("#chat-resizer"),
  activeChatTitle: document.querySelector("#active-chat-title"),
  chatList: document.querySelector("#chat-list"),
  newChat: document.querySelector("#new-chat"),
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

async function initializeApp() {
  await loadDocuments();
  await loadChats();
  if (state.chats.length) {
    await openChat(state.chats[0].id);
  } else {
    await createNewChat();
  }
}

async function loadDocuments() {
  const payload = await api("/api/documents");
  state.documents = payload.documents;
  renderAttachedDocuments();
  renderLibraryList();
}

async function loadChats() {
  const payload = await api("/api/chats");
  state.chats = payload.chats;
  renderChatList();
}

async function createNewChat() {
  const payload = await api("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  await loadChats();
  await openChat(payload.chat.id, { openFirstDocument: false });
  if (!state.chatDrawerPinned) {
    closeChatDrawer();
  }
}

async function openChat(chatId, options = {}) {
  const payload = await api(`/api/chats/${chatId}`);
  state.activeChat = payload.chat;
  setActiveChatTitle(state.activeChat.title);
  renderChatList();
  renderAttachedDocuments();
  renderChatMessages();
  renderLibraryList();

  const attachedIds = new Set(state.activeChat.document_ids);
  if (state.activeDocument && !attachedIds.has(state.activeDocument.id)) {
    clearReader();
  }
  if (!state.activeDocument && options.openFirstDocument !== false && state.activeChat.document_ids.length) {
    await openDocument(state.activeChat.document_ids[0]);
  }
}

function setActiveChatTitle(title) {
  els.activeChatTitle.textContent = title || "New chat";
  els.activeChatTitle.title = "Double-click to rename";
}

function renderChatList() {
  els.chatList.innerHTML = "";
  const query = els.chatSearch.value.trim().toLowerCase();
  const chats = state.chats.filter((chat) => !query || chat.title.toLowerCase().includes(query));
  if (!chats.length) {
    els.chatList.innerHTML = `<div class="empty-copy">${state.chats.length ? "No chats match this search." : "No saved chats yet."}</div>`;
    return;
  }
  chats.forEach((chat) => {
    const item = window.document.createElement("button");
    item.type = "button";
    item.className = `chat-item ${state.activeChat?.id === chat.id ? "active" : ""}`;
    item.innerHTML = `
      <div class="chat-item-title">${escapeHtml(chat.title)}</div>
      <div class="chat-item-meta">${chat.message_count} messages - ${chat.document_ids.length} docs</div>
    `;
    item.addEventListener("click", async () => {
      await openChat(chat.id);
      if (!state.chatDrawerPinned) {
        closeChatDrawer();
      }
    });
    els.chatList.appendChild(item);
  });
}

function beginRenameActiveChat() {
  if (!state.activeChat || els.activeChatTitle.querySelector("input")) return;
  const previousTitle = state.activeChat.title || "New chat";
  const input = window.document.createElement("input");
  input.className = "chat-title-input";
  input.type = "text";
  input.value = previousTitle;
  input.maxLength = 120;
  els.activeChatTitle.replaceChildren(input);
  input.focus();
  input.select();

  let finished = false;
  const finish = async (save) => {
    if (finished) return;
    finished = true;
    const nextTitle = input.value.trim();
    if (!save || !nextTitle || nextTitle === previousTitle) {
      setActiveChatTitle(previousTitle);
      return;
    }
    try {
      const payload = await api(`/api/chats/${state.activeChat.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: nextTitle }),
      });
      state.activeChat = payload.chat;
      setActiveChatTitle(state.activeChat.title);
      await loadChats();
    } catch (error) {
      setActiveChatTitle(previousTitle);
      addMessage("error", "Rename failed", error.message, false);
    }
  };

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(false));
}

function renderAttachedDocuments() {
  els.documentList.innerHTML = "";
  if (!state.activeChat) {
    els.documentList.innerHTML = `<div class="empty-copy">Start or select a chat.</div>`;
    return;
  }

  const attached = state.activeChat.document_ids
    .map((documentId) => findDocument(documentId))
    .filter(Boolean);

  if (!attached.length) {
    els.documentList.innerHTML = `<div class="empty-copy">This chat has no documents attached yet. Use Add to choose from the saved library.</div>`;
    return;
  }

  attached.forEach((doc) => {
    const row = window.document.createElement("div");
    row.className = "document-row";

    const item = window.document.createElement("button");
    item.type = "button";
    item.className = `document-item ${state.activeDocument?.id === doc.id ? "active" : ""}`;
    item.innerHTML = `
      <div class="document-item-title">${escapeHtml(doc.title)}</div>
      <div class="document-item-meta">${escapeHtml(doc.kind.toUpperCase())} - ${formatCount(doc.text_length)} chars</div>
    `;
    item.addEventListener("click", () => openDocument(doc.id));

    const remove = window.document.createElement("button");
    remove.type = "button";
    remove.className = "remove-document";
    remove.title = "Remove from chat";
    remove.textContent = "x";
    remove.addEventListener("click", () => detachDocument(doc.id));

    row.appendChild(item);
    row.appendChild(remove);
    els.documentList.appendChild(row);
  });
}

async function openDocument(documentId) {
  const payload = await api(`/api/documents/${documentId}`);
  state.activeDocument = payload.document;
  renderAttachedDocuments();
  renderDocumentHeader();
  await renderReader(payload.document);
}

function clearReader() {
  state.activeDocument = null;
  renderDocumentHeader();
  els.reader.className = "reader empty-state";
  els.reader.innerHTML = "<div>Select a document attached to this chat.</div>";
}

function renderDocumentHeader() {
  const doc = state.activeDocument;
  els.documentTitle.textContent = doc ? doc.title : "No document open";
  els.documentMeta.textContent = doc
    ? `${doc.kind.toUpperCase()} - ${doc.source_type}${doc.source_url ? ` - ${doc.source_url}` : ""}`
    : "Attach a saved document to the current chat, then open it.";
  els.openSource.disabled = !doc;
}

async function renderReader(doc) {
  els.reader.className = "reader";
  els.reader.innerHTML = "";

  if (doc.kind === "html" || doc.kind === "markdown" || doc.kind === "text" || doc.kind === "epub") {
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

  const payload = await api(`/api/documents/${doc.id}/text`);
  const pre = window.document.createElement("pre");
  pre.className = "reader-text";
  pre.textContent = payload.text || "No readable text was extracted.";
  pre.addEventListener("mouseup", captureTopSelection);
  els.reader.appendChild(pre);
}

function renderChatMessages() {
  els.chatLog.innerHTML = "";
  if (!state.activeChat?.messages.length) {
    addMessage("assistant", "Ready", "Ask about a selected passage, or attach multiple documents and ask across them.", false);
    return;
  }
  state.activeChat.messages.forEach((message) => {
    const meta = message.role === "assistant"
      ? `${message.provider || "assistant"}${message.model ? ` - ${message.model}` : ""}`
      : "Question";
    addMessage(message.role, meta, message.content, message.role === "assistant");
  });
}

function renderLibraryList() {
  if (!els.libraryList) return;
  const query = els.librarySearch.value.trim().toLowerCase();
  const attachedIds = new Set(state.activeChat?.document_ids || []);
  const filtered = state.documents.filter((doc) => {
    const haystack = `${doc.title} ${doc.kind} ${doc.source_name} ${doc.source_url || ""}`.toLowerCase();
    return !query || haystack.includes(query);
  });

  els.libraryList.innerHTML = "";
  if (!filtered.length) {
    els.libraryList.innerHTML = `<div class="empty-copy">No documents match this search.</div>`;
    return;
  }

  filtered.forEach((doc) => {
    const row = window.document.createElement("div");
    row.className = "library-item";
    const attached = attachedIds.has(doc.id);
    row.innerHTML = `
      <div class="library-item-main">
        <div class="document-item-title">${escapeHtml(doc.title)}</div>
        <div class="document-item-meta">${escapeHtml(doc.kind.toUpperCase())} - ${formatCount(doc.text_length)} chars</div>
      </div>
    `;
    const action = window.document.createElement("button");
    action.type = "button";
    action.className = "library-item-action";
    action.textContent = attached ? "Open" : "Add";
    action.addEventListener("click", async () => {
      if (!attached) {
        await attachDocument(doc.id);
      }
      closeLibraryModal();
      await openDocument(doc.id);
    });
    row.appendChild(action);
    els.libraryList.appendChild(row);
  });
}

async function attachDocument(documentId) {
  await ensureActiveChat();
  const payload = await api(`/api/chats/${state.activeChat.id}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_ids: [documentId] }),
  });
  state.activeChat = payload.chat;
  await loadChats();
  renderAttachedDocuments();
  renderLibraryList();
}

async function detachDocument(documentId) {
  if (!state.activeChat) return;
  const payload = await api(`/api/chats/${state.activeChat.id}/documents/${documentId}`, {
    method: "DELETE",
  });
  state.activeChat = payload.chat;
  await loadChats();
  renderAttachedDocuments();
  renderLibraryList();
  if (state.activeDocument?.id === documentId) {
    clearReader();
  }
}

async function ensureActiveChat() {
  if (!state.activeChat) {
    await createNewChat();
  }
}

function openLibraryModal() {
  renderLibraryList();
  els.libraryModal.classList.remove("hidden");
  els.librarySearch.focus();
}

function closeLibraryModal() {
  els.libraryModal.classList.add("hidden");
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
  addMessage("user", "Import URL", url, false);
  try {
    await ensureActiveChat();
    const payload = await api("/api/documents/import-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    els.urlInput.value = "";
    await loadDocuments();
    await attachDocument(payload.document.id);
    await openDocument(payload.document.id);
    addMessage("assistant", "Imported", payload.document.title, false);
  } catch (error) {
    addMessage("error", "Import failed", error.message, false);
  } finally {
    setBusy(event.submitter, false);
  }
}

async function uploadFile() {
  const file = els.fileInput.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  addMessage("user", "Upload", file.name, false);
  try {
    await ensureActiveChat();
    const payload = await api("/api/documents/upload", {
      method: "POST",
      body: form,
    });
    els.fileInput.value = "";
    await loadDocuments();
    await attachDocument(payload.document.id);
    await openDocument(payload.document.id);
    addMessage("assistant", "Uploaded", payload.document.title, false);
  } catch (error) {
    addMessage("error", "Upload failed", error.message, false);
  }
}

async function askQuestion(event) {
  event.preventDefault();
  const question = els.questionInput.value.trim();
  if (!question) return;
  await ensureActiveChat();

  const selectedText = els.selectionText.value.trim();
  const provider = els.providerSelect.value;
  const model = els.modelInput.value.trim();
  els.questionInput.value = "";
  addMessage("user", "Question", question, false);
  const pending = addMessage("assistant", "Thinking", "Working...", false);

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: state.activeChat.id,
        document_id: state.activeDocument?.id || null,
        question,
        selected_text: selectedText,
        provider: provider || null,
        model: model || null,
      }),
    });
    if (!response.ok || !response.body) {
      throw new Error(response.statusText || "Streaming request failed");
    }
    await consumeChatStream(response, pending);
  } catch (error) {
    pending.className = "message error";
    pending.querySelector(".message-meta").textContent = "Chat failed";
    setMessageBody(pending, error.message, false);
  }
}

async function consumeChatStream(response, pending) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const event = parseSseEvent(rawEvent);
      if (!event) continue;
      if (event.type === "meta") {
        pending.querySelector(".message-meta").textContent = `${event.data.provider}${event.data.model ? ` - ${event.data.model}` : ""}`;
        setMessageBody(pending, "", true);
      } else if (event.type === "delta") {
        answer += event.data.text || "";
        setMessageBody(pending, answer, true);
      } else if (event.type === "done") {
        state.activeChat = event.data.chat;
        setActiveChatTitle(state.activeChat.title);
        setMessageBody(pending, event.data.answer || answer, true);
        await loadChats();
        renderAttachedDocuments();
        renderLibraryList();
      } else if (event.type === "error") {
        throw new Error(event.data.message || "Streaming failed");
      }
    }
  }
}

function parseSseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  const typeLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines.filter((line) => line.startsWith("data:"));
  if (!typeLine || !dataLines.length) return null;
  const type = typeLine.slice(6).trim();
  const data = JSON.parse(dataLines.map((line) => line.slice(5).trimStart()).join("\n"));
  return { type, data };
}

function addMessage(kind, meta, body, renderMath = kind === "assistant") {
  const message = window.document.createElement("div");
  message.className = `message ${kind}`;
  message.innerHTML = `
    <div class="message-meta">${escapeHtml(meta)}</div>
    <div class="message-body"></div>
  `;
  setMessageBody(message, body, renderMath);
  els.chatLog.appendChild(message);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
  return message;
}

function setMessageBody(message, body, renderMath) {
  const target = message.querySelector(".message-body");
  if (renderMath) {
    target.innerHTML = renderMarkdown(body);
    typesetMath(target);
  } else {
    target.textContent = body;
  }
}

function renderMarkdown(text) {
  const { text: protectedText, segments } = protectMathSegments(String(text || ""));
  const blocks = protectedText.replace(/\r\n/g, "\n").split(/\n{2,}/);
  const html = blocks.map((block) => renderMarkdownBlock(block)).join("");
  return restoreMathSegments(html, segments);
}

function renderMarkdownBlock(block) {
  const trimmed = block.trim();
  if (!trimmed) return "";
  const codeMatch = trimmed.match(/^```[a-zA-Z0-9_-]*\n([\s\S]*?)```$/);
  if (codeMatch) {
    return `<pre><code>${escapeHtml(codeMatch[1])}</code></pre>`;
  }
  const lines = trimmed.split("\n");
  if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
    return `<ul>${lines.map((line) => `<li>${renderMarkdownInline(line.replace(/^\s*[-*]\s+/, ""))}</li>`).join("")}</ul>`;
  }
  if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
    return `<ol>${lines.map((line) => `<li>${renderMarkdownInline(line.replace(/^\s*\d+\.\s+/, ""))}</li>`).join("")}</ol>`;
  }
  return `<p>${renderMarkdownInline(trimmed).replace(/\n/g, "<br>")}</p>`;
}

function renderMarkdownInline(text) {
  const codeSegments = [];
  let value = escapeHtml(text).replace(/`([^`]+)`/g, (_match, code) => {
    const token = `@@CODE${codeSegments.length}@@`;
    codeSegments.push(`<code>${code}</code>`);
    return token;
  });
  value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|#[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  value = value.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/(^|[^\*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  codeSegments.forEach((segment, index) => {
    value = value.replace(`@@CODE${index}@@`, segment);
  });
  return value;
}

function protectMathSegments(text) {
  const segments = [];
  const protectedText = text.replace(/(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g, (match) => {
    const token = `@@MATH${segments.length}@@`;
    segments.push(escapeHtml(match));
    return token;
  });
  return { text: protectedText, segments };
}

function restoreMathSegments(html, segments) {
  let restored = html;
  segments.forEach((segment, index) => {
    restored = restored.replaceAll(`@@MATH${index}@@`, segment);
  });
  return restored;
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

function findDocument(documentId) {
  return state.documents.find((doc) => doc.id === documentId);
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

function initializeChatDrawer() {
  const savedWidth = Number.parseInt(window.localStorage.getItem("chatDrawerWidth") || "", 10);
  if (savedWidth) {
    setChatDrawerWidth(savedWidth);
  }
  state.chatDrawerPinned = window.localStorage.getItem("chatDrawerPinned") === "true";
  state.chatDrawerOpen = state.chatDrawerPinned;
  applyChatDrawerState();

  els.chatDrawerResizer.addEventListener("pointerdown", (event) => {
    if (!state.chatDrawerPinned) return;
    event.preventDefault();
    window.document.body.classList.add("chat-resizing");
    els.chatDrawerResizer.setPointerCapture(event.pointerId);
  });
  els.chatDrawerResizer.addEventListener("pointermove", (event) => {
    if (!els.chatDrawerResizer.hasPointerCapture(event.pointerId)) return;
    setChatDrawerWidth(event.clientX);
  });
  els.chatDrawerResizer.addEventListener("pointerup", (event) => {
    if (els.chatDrawerResizer.hasPointerCapture(event.pointerId)) {
      els.chatDrawerResizer.releasePointerCapture(event.pointerId);
    }
    window.document.body.classList.remove("chat-resizing");
    window.localStorage.setItem(
      "chatDrawerWidth",
      getComputedStyle(window.document.documentElement).getPropertyValue("--chat-drawer-width"),
    );
  });
}

function toggleChatDrawer() {
  if (state.chatDrawerPinned) {
    state.chatDrawerPinned = false;
    state.chatDrawerOpen = false;
    persistChatDrawerPin();
  } else {
    state.chatDrawerOpen = !state.chatDrawerOpen;
  }
  applyChatDrawerState();
}

function closeChatDrawer() {
  if (state.chatDrawerPinned) return;
  state.chatDrawerOpen = false;
  applyChatDrawerState();
}

function toggleChatDrawerPin() {
  state.chatDrawerPinned = !state.chatDrawerPinned;
  state.chatDrawerOpen = true;
  persistChatDrawerPin();
  applyChatDrawerState();
}

function persistChatDrawerPin() {
  window.localStorage.setItem("chatDrawerPinned", String(state.chatDrawerPinned));
}

function applyChatDrawerState() {
  window.document.body.classList.toggle("chat-drawer-open", state.chatDrawerOpen);
  window.document.body.classList.toggle("chat-drawer-pinned", state.chatDrawerPinned);
  els.chatDrawer.setAttribute("aria-hidden", String(!state.chatDrawerOpen));
  els.chatDrawer.inert = !state.chatDrawerOpen;
  els.chatDrawerToggle.setAttribute("aria-expanded", String(state.chatDrawerOpen));
  els.chatDrawerToggle.title = state.chatDrawerOpen ? "Close chat history" : "Open chat history";
  els.pinChatDrawer.textContent = state.chatDrawerPinned ? "Unpin" : "Pin";
  els.pinChatDrawer.title = state.chatDrawerPinned ? "Unpin chat history" : "Pin chat history";
}

function setChatDrawerWidth(width) {
  const parsed = Number.parseInt(width, 10);
  if (!Number.isFinite(parsed)) return;
  const maxWidth = Math.max(280, Math.min(520, window.innerWidth - 520));
  const clamped = Math.max(240, Math.min(maxWidth, parsed));
  window.document.documentElement.style.setProperty("--chat-drawer-width", `${clamped}px`);
}

function initializeChatResizer() {
  const savedWidth = Number.parseInt(window.localStorage.getItem("chatWidth") || "", 10);
  if (savedWidth) {
    setChatWidth(savedWidth);
  }
  els.chatResizer.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    window.document.body.classList.add("chat-resizing");
    els.chatResizer.setPointerCapture(event.pointerId);
  });
  els.chatResizer.addEventListener("pointermove", (event) => {
    if (!els.chatResizer.hasPointerCapture(event.pointerId)) return;
    const workspace = els.chatResizer.parentElement;
    const bounds = workspace.getBoundingClientRect();
    const width = bounds.right - event.clientX;
    setChatWidth(width);
  });
  els.chatResizer.addEventListener("pointerup", (event) => {
    if (els.chatResizer.hasPointerCapture(event.pointerId)) {
      els.chatResizer.releasePointerCapture(event.pointerId);
    }
    window.document.body.classList.remove("chat-resizing");
    window.localStorage.setItem("chatWidth", getComputedStyle(window.document.documentElement).getPropertyValue("--chat-width"));
  });
}

function setChatWidth(width) {
  const parsed = Number.parseInt(width, 10);
  if (!Number.isFinite(parsed)) return;
  const clamped = Math.max(300, Math.min(720, parsed));
  window.document.documentElement.style.setProperty("--chat-width", `${clamped}px`);
}

window.addEventListener("message", (event) => {
  if (event.data?.type === "reader-selection" && event.data.text) {
    setSelectionText(event.data.text);
  }
});

els.urlForm.addEventListener("submit", importUrl);
els.fileInput.addEventListener("change", uploadFile);
els.chatForm.addEventListener("submit", askQuestion);
els.newChat.addEventListener("click", createNewChat);
els.drawerNewChat.addEventListener("click", createNewChat);
els.chatDrawerToggle.addEventListener("click", toggleChatDrawer);
els.pinChatDrawer.addEventListener("click", toggleChatDrawerPin);
els.chatDrawerBackdrop.addEventListener("click", closeChatDrawer);
els.chatSearch.addEventListener("input", renderChatList);
els.activeChatTitle.addEventListener("dblclick", beginRenameActiveChat);
els.addDocuments.addEventListener("click", openLibraryModal);
els.closeLibrary.addEventListener("click", closeLibraryModal);
els.librarySearch.addEventListener("input", renderLibraryList);
els.libraryModal.addEventListener("click", (event) => {
  if (event.target === els.libraryModal) {
    closeLibraryModal();
  }
});
els.openSource.addEventListener("click", () => {
  if (state.activeDocument) {
    const path = state.activeDocument.kind === "html" || state.activeDocument.kind === "markdown" || state.activeDocument.kind === "text" || state.activeDocument.kind === "epub"
      ? `/api/documents/${state.activeDocument.id}/html`
      : `/api/documents/${state.activeDocument.id}/file`;
    window.open(path, "_blank", "noopener");
  }
});
window.document.addEventListener("mouseup", captureTopSelection);
window.document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.chatDrawerOpen && !state.chatDrawerPinned) {
    closeChatDrawer();
  }
});
initializeChatDrawer();
initializeChatResizer();

initializeApp().catch((error) => addMessage("error", "Startup failed", error.message, false));
