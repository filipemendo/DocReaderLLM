const viewer = document.querySelector("#viewer");
const statusEl = document.querySelector("#status");

const params = new URLSearchParams(window.location.search);
const fileUrl = params.get("file");
let currentPdf = null;

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
    currentPdf = await window.pdfjsLib.getDocument(fileUrl).promise;
    setStatus(`Rendering ${currentPdf.numPages} pages...`);
    for (let pageNumber = 1; pageNumber <= currentPdf.numPages; pageNumber += 1) {
      await renderPage(currentPdf, pageNumber);
      setStatus(`Rendered ${pageNumber} of ${currentPdf.numPages} pages`);
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
  shell.dataset.pageNumber = String(pageNumber);

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

  const annotationLayer = document.createElement("div");
  annotationLayer.className = "annotationLayer";

  const label = document.createElement("div");
  label.className = "page-label";
  label.textContent = String(pageNumber);

  shell.appendChild(canvas);
  shell.appendChild(textLayer);
  shell.appendChild(annotationLayer);
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

  await renderAnnotationLinks(page, viewport, annotationLayer);
}

async function renderAnnotationLinks(page, viewport, container) {
  const annotations = await page.getAnnotations({ intent: "display" });
  annotations
    .filter((annotation) => annotation.subtype === "Link" && annotation.rect)
    .forEach((annotation) => {
      const link = document.createElement("a");
      link.className = "annotation-link";
      const rect = viewport.convertToViewportRectangle(annotation.rect);
      const left = Math.min(rect[0], rect[2]);
      const top = Math.min(rect[1], rect[3]);
      link.style.left = `${left}px`;
      link.style.top = `${top}px`;
      link.style.width = `${Math.abs(rect[0] - rect[2])}px`;
      link.style.height = `${Math.abs(rect[1] - rect[3])}px`;
      link.title = annotation.url || "Go to linked location";

      if (annotation.url) {
        link.href = annotation.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      } else if (annotation.dest) {
        link.href = "#";
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          await scrollToDestination(annotation.dest);
        });
      }
      container.appendChild(link);
    });
}

async function scrollToDestination(destination) {
  if (!currentPdf) return;
  const explicitDestination = typeof destination === "string"
    ? await currentPdf.getDestination(destination)
    : destination;
  if (!explicitDestination?.length) return;
  const pageRef = explicitDestination[0];
  const pageIndex = typeof pageRef === "object"
    ? await currentPdf.getPageIndex(pageRef)
    : Number(pageRef) - 1;
  const pageNumber = pageIndex + 1;
  const pageElement = document.querySelector(`[data-page-number="${pageNumber}"]`);
  if (pageElement) {
    pageElement.scrollIntoView({ behavior: "smooth", block: "start" });
  }
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
