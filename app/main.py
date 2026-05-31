from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.chats import ChatStore
from app.config import get_settings
from app.documents import DocumentStore
from app.llm import build_llm_provider
from app.models import (
    AttachDocumentsRequest,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    CreateChatRequest,
    ImportUrlRequest,
    ImportUrlResponse,
)
from app.retrieval import LexicalDocumentRetriever, format_retrieved_chunks
from datetime import datetime, timezone


settings = get_settings()
store = DocumentStore(settings.data_dir)
chat_store = ChatStore(settings.data_dir)
retriever = LexicalDocumentRetriever(store)

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


@app.get("/api/chats")
async def list_chats():
    return {"chats": chat_store.list_chats()}


@app.post("/api/chats")
async def create_chat(payload: CreateChatRequest | None = None):
    chat = chat_store.create_chat(payload.title if payload else None)
    return {"chat": chat}


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str):
    chat = chat_store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"chat": chat}


@app.post("/api/chats/{chat_id}/documents")
async def attach_documents(chat_id: str, payload: AttachDocumentsRequest):
    chat = chat_store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    missing = [document_id for document_id in payload.document_ids if not store.get_metadata(document_id)]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown document IDs: {', '.join(missing)}")
    return {"chat": chat_store.attach_documents(chat, payload.document_ids)}


@app.delete("/api/chats/{chat_id}/documents/{document_id}")
async def detach_document(chat_id: str, document_id: str):
    chat = chat_store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"chat": chat_store.detach_document(chat, document_id)}


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
    chat_session = chat_store.require_chat(payload.chat_id)
    document = store.get_metadata(payload.document_id) if payload.document_id else None
    if payload.document_id and not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document and document.id not in chat_session.document_ids:
        chat_session = chat_store.attach_documents(chat_session, [document.id])

    retrieved = retriever.retrieve(
        document_ids=chat_session.document_ids,
        question=payload.question,
        selected_text=payload.selected_text,
        active_document_id=payload.document_id,
        top_k=6,
    )
    context_chunks = format_retrieved_chunks(retrieved)
    document_scope = document_scope_title(chat_session.document_ids)
    history = [
        {"role": message.role, "content": message.content}
        for message in chat_session.messages
        if message.role in {"user", "assistant"}
    ]
    provider = build_llm_provider(payload.provider or settings.default_provider, settings)
    answer = await provider.answer(
        question=payload.question,
        selected_text=payload.selected_text,
        context_chunks=context_chunks,
        document_title=document_scope,
        chat_history=history,
        location=payload.location,
        model=payload.model or settings.default_model,
    )
    now = datetime.now(timezone.utc)
    chat_session = chat_store.append_message(
        chat_session,
        ChatMessage(
            role="user",
            content=payload.question.strip(),
            created_at=now,
            document_id=payload.document_id,
            selected_text=payload.selected_text,
            context_chunks=context_chunks,
        ),
    )
    chat_session = chat_store.append_message(
        chat_session,
        ChatMessage(
            role="assistant",
            content=answer.text,
            created_at=datetime.now(timezone.utc),
            provider=answer.provider,
            model=answer.model,
            context_chunks=context_chunks,
        ),
    )
    return ChatResponse(
        chat=chat_session,
        answer=answer.text,
        provider=answer.provider,
        model=answer.model,
        context_chunks=context_chunks,
    )


@app.get("/health")
async def health():
    return Response("ok", media_type="text/plain")


def document_scope_title(document_ids: list[str]) -> str:
    titles = [metadata.title for document_id in document_ids if (metadata := store.get_metadata(document_id))]
    if not titles:
        return "No attached documents"
    if len(titles) <= 3:
        return "; ".join(titles)
    return "; ".join(titles[:3]) + f"; and {len(titles) - 3} more"
