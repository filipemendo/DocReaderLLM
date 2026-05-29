from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import bleach
import fitz
import httpx
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from fastapi import UploadFile

from app.models import DocumentKind, DocumentMetadata


HTML_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union(
    {
        "article",
        "aside",
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "i",
        "img",
        "li",
        "main",
        "math",
        "mi",
        "mn",
        "mo",
        "mrow",
        "msub",
        "msup",
        "msubsup",
        "ol",
        "p",
        "pre",
        "section",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
HTML_ATTRIBUTES = {
    "*": ["aria-label", "class", "id", "title"],
    "a": ["href", "name", "rel", "title"],
    "img": ["alt", "height", "src", "title", "width"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
}


class DocumentStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.documents_dir = data_dir / "documents"
        self.documents_dir.mkdir(parents=True, exist_ok=True)

    def list_documents(self) -> list[DocumentMetadata]:
        documents = []
        for metadata_path in sorted(self.documents_dir.glob("*/metadata.json"), reverse=True):
            try:
                documents.append(DocumentMetadata.model_validate_json(metadata_path.read_text()))
            except Exception:
                continue
        return documents

    async def save_upload(self, file: UploadFile) -> DocumentMetadata:
        filename = Path(file.filename or "document").name
        doc_id = uuid.uuid4().hex
        doc_dir = self._doc_dir(doc_id)
        doc_dir.mkdir(parents=True)

        original_path = doc_dir / f"original{Path(filename).suffix.lower()}"
        size = 0
        with original_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                out.write(chunk)
        if size == 0:
            shutil.rmtree(doc_dir)
            raise ValueError("Uploaded file is empty")

        kind = infer_kind(filename, file.content_type)
        return self._materialize_document(
            doc_id=doc_id,
            source_type="upload",
            source_name=filename,
            source_url=None,
            mime_type=file.content_type or mimetypes.guess_type(filename)[0],
            kind=kind,
            original_path=original_path,
        )

    async def import_url(self, url: str) -> DocumentMetadata:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http and https URLs are supported")

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not fetch remote document: {exc}") from exc

        if not content:
            raise ValueError("Remote document is empty")

        filename = infer_filename_from_url(url, response.headers.get("content-type"))
        doc_id = uuid.uuid4().hex
        doc_dir = self._doc_dir(doc_id)
        doc_dir.mkdir(parents=True)
        original_path = doc_dir / f"original{Path(filename).suffix.lower()}"
        original_path.write_bytes(content)

        kind = infer_kind(filename, response.headers.get("content-type"))
        return self._materialize_document(
            doc_id=doc_id,
            source_type="url",
            source_name=filename,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type"),
            kind=kind,
            original_path=original_path,
        )

    def get_metadata(self, document_id: str) -> DocumentMetadata | None:
        path = self._doc_dir(document_id) / "metadata.json"
        if not path.exists():
            return None
        return DocumentMetadata.model_validate_json(path.read_text())

    def get_text(self, document_id: str) -> str:
        path = self._doc_dir(document_id) / "text.txt"
        return path.read_text(errors="replace") if path.exists() else ""

    def get_display_html(self, document_id: str) -> str | None:
        path = self._doc_dir(document_id) / "display.html"
        return path.read_text(errors="replace") if path.exists() else None

    def get_original_path(self, document_id: str) -> Path:
        matches = list(self._doc_dir(document_id).glob("original*"))
        return matches[0] if matches else self._doc_dir(document_id) / "original"

    def _materialize_document(
        self,
        *,
        doc_id: str,
        source_type: str,
        source_name: str,
        source_url: str | None,
        mime_type: str | None,
        kind: DocumentKind,
        original_path: Path,
    ) -> DocumentMetadata:
        text, display_html, title = extract_document(original_path, kind, source_url)
        if display_html:
            (self._doc_dir(doc_id) / "display.html").write_text(display_html)
        (self._doc_dir(doc_id) / "text.txt").write_text(text)

        metadata = DocumentMetadata(
            id=doc_id,
            title=title or readable_title(source_name),
            kind=kind,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            mime_type=mime_type,
            created_at=datetime.now(timezone.utc),
            text_length=len(text),
        )
        (self._doc_dir(doc_id) / "metadata.json").write_text(metadata.model_dump_json(indent=2))
        return metadata

    def _doc_dir(self, document_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", document_id)
        return self.documents_dir / safe_id


def extract_document(path: Path, kind: DocumentKind, source_url: str | None) -> tuple[str, str | None, str | None]:
    if kind == "pdf":
        return extract_pdf(path)
    if kind == "epub":
        return extract_epub(path)
    if kind == "html":
        html = path.read_text(errors="replace")
        return extract_html(html, source_url)
    text = path.read_text(errors="replace")
    return normalize_text(text), text_to_display_html(text), readable_title(path.name)


def extract_pdf(path: Path) -> tuple[str, str | None, str | None]:
    pages = []
    title = None
    with fitz.open(path) as doc:
        title = doc.metadata.get("title") if doc.metadata else None
        for index, page in enumerate(doc, start=1):
            page_text = page.get_text("text")
            if page_text.strip():
                pages.append(f"[Page {index}]\n{page_text}")
    return normalize_text("\n\n".join(pages)), None, title


def extract_epub(path: Path) -> tuple[str, str | None, str | None]:
    book = epub.read_epub(str(path))
    title_items = book.get_metadata("DC", "title")
    title = title_items[0][0] if title_items else readable_title(path.name)
    html_parts = []
    text_parts = []
    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            html = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            html_parts.append(str(soup.body or soup))
            text_parts.append(soup.get_text("\n", strip=True))

    display_html = build_display_html(
        title=title,
        body=sanitize_html("\n".join(html_parts), None),
        base_url=None,
    )
    return normalize_text("\n\n".join(text_parts)), display_html, title


def extract_html(html: str, source_url: str | None) -> tuple[str, str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "noscript", "template"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    body = soup.body or soup
    display = build_display_html(title=title or "Imported HTML", body=sanitize_html(str(body), source_url), base_url=source_url)
    text = normalize_text(body.get_text("\n", strip=True))
    return text, display, title


def sanitize_html(html: str, base_url: str | None) -> str:
    return bleach.clean(
        html,
        tags=HTML_TAGS,
        attributes=HTML_ATTRIBUTES,
        protocols={"http", "https", "mailto", "data"},
        strip=True,
    )


def build_display_html(title: str, body: str, base_url: str | None) -> str:
    base = f'<base href="{bleach.clean(base_url, tags=[], strip=True)}">' if base_url else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  {base}
  <title>{bleach.clean(title, tags=[], strip=True)}</title>
  <style>
    body {{
      color: #18201c;
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      line-height: 1.58;
      margin: 0 auto;
      max-width: 880px;
      padding: 32px 40px 64px;
    }}
    img, table {{ max-width: 100%; }}
    pre, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    pre {{ overflow-x: auto; }}
    a {{ color: #1f6feb; }}
  </style>
  <script>
    function normalizeSelectionText(rawText) {{
      const text = String(rawText || "")
        .replace(/\\u00a0/g, " ")
        .replace(/[ \\t]+\\n/g, "\\n")
        .replace(/\\n[ \\t]+/g, "\\n")
        .trim();
      const lines = text.split(/\\n+/).map((line) => line.trim()).filter(Boolean);
      if (lines.length < 3) {{
        return text.replace(/[ \\t]{{2,}}/g, " ");
      }}
      const fragments = lines.filter((line) =>
        line.length <= 3 ||
        /^[A-Za-z0-9()[\\]{{}}.,;:=+\\-*/^_|<>≤≥≈≃≅≠∼∝∈∉⊂⊃⊆⊇∪∩→←↦⇒⇔±∓×÷·⋅∘∑∏∫√∞∂∇∀∃¬∧∨α-ωΑ-Ω]+$/u.test(line)
      ).length;
      if (fragments / lines.length < 0.35) {{
        return text.replace(/[ \\t]{{2,}}/g, " ");
      }}
      return lines.join(" ")
        .replace(/\\s+([,.;:)\\]}}])/g, "$1")
        .replace(/([([{{])\\s+/g, "$1")
        .replace(/[ \\t]{{2,}}/g, " ")
        .trim();
    }}

    document.addEventListener("selectionchange", () => {{
      const text = normalizeSelectionText(window.getSelection ? window.getSelection() : "");
      if (text) {{
        window.parent.postMessage({{ type: "reader-selection", text }}, "*");
      }}
    }});
  </script>
</head>
<body>{body}</body>
</html>"""


def text_to_display_html(text: str) -> str:
    escaped = bleach.clean(text)
    return build_display_html("Text document", f"<pre>{escaped}</pre>", None)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def infer_kind(filename: str, mime_type: str | None) -> DocumentKind:
    suffix = Path(filename).suffix.lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    if suffix == ".pdf" or mime == "application/pdf":
        return "pdf"
    if suffix == ".epub" or mime == "application/epub+zip":
        return "epub"
    if suffix in {".html", ".htm"} or mime in {"text/html", "application/xhtml+xml"}:
        return "html"
    if suffix in {".txt", ".md"} or mime.startswith("text/"):
        return "text"
    return "unknown"


def infer_filename_from_url(url: str, content_type: str | None) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or hashlib.sha1(url.encode()).hexdigest()[:12]
    if "." not in name:
        extension = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".html"
        name = f"{name}{extension}"
    return name


def readable_title(name: str) -> str:
    stem = Path(name).stem
    return re.sub(r"[_-]+", " ", stem).strip().title() or "Untitled document"
