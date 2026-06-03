from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.chats import ChatStore
from app.config import get_settings
from app.documents import DocumentStore, enhance_display_html
from app.llm import BaseProvider, build_llm_provider
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
import json


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
    return HTMLResponse(enhance_display_html(html))


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
    chat_session, provider, model_name, answer_kwargs, context_chunks = prepare_chat_answer(payload)
    answer = await provider.answer(
        **answer_kwargs,
    )
    chat_session = persist_chat_turn(
        chat_session=chat_session,
        payload=payload,
        answer_text=answer.text,
        provider=answer.provider,
        model=answer.model,
        context_chunks=context_chunks,
    )
    return ChatResponse(
        chat=chat_session,
        answer=answer.text,
        provider=answer.provider,
        model=answer.model,
        context_chunks=context_chunks,
    )


@app.post("/api/chat/stream")
async def stream_chat(payload: ChatRequest):
    chat_session, provider, model_name, answer_kwargs, context_chunks = prepare_chat_answer(payload)

    async def events():
        answer_parts = []
        yield sse("meta", {"provider": provider.provider, "model": model_name, "chat_id": chat_session.id})
        try:
            async for piece in provider.stream_answer(**answer_kwargs):
                answer_parts.append(piece)
                yield sse("delta", {"text": piece})
        except Exception as exc:
            yield sse("error", {"message": str(exc)})
            return

        answer_text = "".join(answer_parts).strip()
        saved_chat = persist_chat_turn(
            chat_session=chat_session,
            payload=payload,
            answer_text=answer_text,
            provider=provider.provider,
            model=model_name,
            context_chunks=context_chunks,
        )
        yield sse(
            "done",
            {
                "chat": saved_chat.model_dump(mode="json"),
                "answer": answer_text,
                "provider": provider.provider,
                "model": model_name,
                "context_chunks": context_chunks,
            },
        )

    return StreamingResponse(events(), media_type="text/event-stream")


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


def prepare_chat_answer(payload: ChatRequest) -> tuple[object, BaseProvider, str | None, dict, list[str]]:
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
    history = [
        {"role": message.role, "content": message.content}
        for message in chat_session.messages
        if message.role in {"user", "assistant"}
    ]
    provider = build_llm_provider(payload.provider or settings.default_provider, settings)
    model_name = provider.model_name(payload.model or settings.default_model)
    answer_kwargs = {
        "question": payload.question,
        "selected_text": payload.selected_text,
        "context_chunks": context_chunks,
        "document_title": document_scope_title(chat_session.document_ids),
        "chat_history": history,
        "location": payload.location,
        "model": model_name,
    }
    return chat_session, provider, model_name, answer_kwargs, context_chunks


def persist_chat_turn(
    *,
    chat_session,
    payload: ChatRequest,
    answer_text: str,
    provider: str,
    model: str | None,
    context_chunks: list[str],
):
    chat_session = chat_store.append_message(
        chat_session,
        ChatMessage(
            role="user",
            content=payload.question.strip(),
            created_at=datetime.now(timezone.utc),
            document_id=payload.document_id,
            selected_text=payload.selected_text,
            context_chunks=context_chunks,
        ),
    )
    return chat_store.append_message(
        chat_session,
        ChatMessage(
            role="assistant",
            content=answer_text,
            created_at=datetime.now(timezone.utc),
            provider=provider,
            model=model,
            context_chunks=context_chunks,
        ),
    )


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
