const viewer = document.querySelector("#viewer");
const statusEl = document.querySelector("#status");

const params = new URLSearchParams(window.location.search);
const fileUrl = params.get("file");

if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.className = isError ? "status error" : "status";
}

async function renderPdf() {
  if (!fileUrl) {
    setStatus("No PDF file was provided.", true);
    return;
  }
  if (!window.pdfjsLib) {
    setStatus("PDF.js did not load. Check your browser network access to the PDF.js CDN.", true);
    return;
  }

  try {
    const pdf = await window.pdfjsLib.getDocument(fileUrl).promise;
    setStatus(`Rendering ${pdf.numPages} pages...`);
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      await renderPage(pdf, pageNumber);
      setStatus(`Rendered ${pageNumber} of ${pdf.numPages} pages`);
    }
    statusEl.remove();
  } catch (error) {
    setStatus(`Could not render PDF: ${error.message}`, true);
  }
}

async function renderPage(pdf, pageNumber) {
  const page = await pdf.getPage(pageNumber);
  const baseViewport = page.getViewport({ scale: 1 });
  const availableWidth = Math.max(320, Math.min(940, viewer.clientWidth - 48));
  const scale = availableWidth / baseViewport.width;
  const viewport = page.getViewport({ scale });

  const shell = document.createElement("div");
  shell.className = "pdf-page";
  shell.style.width = `${viewport.width}px`;
  shell.style.height = `${viewport.height}px`;

  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const outputScale = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;

  const textLayer = document.createElement("div");
  textLayer.className = "textLayer";
  textLayer.style.setProperty("--scale-factor", String(scale));

  const label = document.createElement("div");
  label.className = "page-label";
  label.textContent = String(pageNumber);

  shell.appendChild(canvas);
  shell.appendChild(textLayer);
  shell.appendChild(label);
  viewer.appendChild(shell);

  await page.render({
    canvasContext: context,
    viewport,
    transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null,
  }).promise;

  const textContent = await page.getTextContent();
  await window.pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: textLayer,
    viewport,
    textDivs: [],
  }).promise;
}

function postSelection() {
  const text = String(window.getSelection ? window.getSelection() : "").trim();
  if (text) {
    window.parent.postMessage({ type: "reader-selection", text }, window.location.origin);
  }
}

document.addEventListener("selectionchange", () => {
  window.clearTimeout(postSelection.timer);
  postSelection.timer = window.setTimeout(postSelection, 80);
});
document.addEventListener("mouseup", postSelection);
document.addEventListener("keyup", postSelection);

renderPdf();
