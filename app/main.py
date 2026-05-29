from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.documents import DocumentStore
from app.llm import build_llm_provider
from app.models import ChatRequest, ChatResponse, ImportUrlRequest, ImportUrlResponse
from app.retrieval import retrieve_context


settings = get_settings()
store = DocumentStore(settings.data_dir)

app = FastAPI(title="HTMLreaderLLM")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/api/documents")
async def list_documents():
    return {"documents": store.list_documents()}


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        document = await store.save_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document": document}


@app.post("/api/documents/import-url", response_model=ImportUrlResponse)
async def import_url(payload: ImportUrlRequest):
    try:
        document = await store.import_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportUrlResponse(document=document)


@app.get("/api/documents/{document_id}")
async def get_document(document_id: str):
    document = store.get_metadata(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"document": document}


@app.get("/api/documents/{document_id}/text")
async def get_document_text(document_id: str):
    if not store.get_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"text": store.get_text(document_id)}


@app.get("/api/documents/{document_id}/html")
async def get_document_html(document_id: str):
    document = store.get_metadata(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    html = store.get_display_html(document_id)
    if html is None:
        raise HTTPException(status_code=404, detail="No HTML representation available")
    return HTMLResponse(html)


@app.get("/api/documents/{document_id}/file")
async def get_document_file(document_id: str):
    document = store.get_metadata(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    path = store.get_original_path(document_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document file not found")
    media_type = (document.mime_type or "application/octet-stream").split(";")[0]
    return FileResponse(
        path,
        media_type=media_type,
        filename=document.source_name,
        content_disposition_type="inline",
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    document = store.get_metadata(payload.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    full_text = store.get_text(payload.document_id)
    context_chunks = retrieve_context(
        full_text,
        question=payload.question,
        selected_text=payload.selected_text,
        max_chunks=4,
    )
    provider = build_llm_provider(payload.provider or settings.default_provider, settings)
    answer = await provider.answer(
        question=payload.question,
        selected_text=payload.selected_text,
        context_chunks=context_chunks,
        document_title=document.title,
        location=payload.location,
        model=payload.model or settings.default_model,
    )
    return ChatResponse(
        answer=answer.text,
        provider=answer.provider,
        model=answer.model,
        context_chunks=context_chunks,
    )


@app.get("/health")
async def health():
    return Response("ok", media_type="text/plain")
