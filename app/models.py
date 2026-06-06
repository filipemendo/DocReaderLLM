from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


DocumentKind = Literal["pdf", "epub", "html", "markdown", "text", "unknown"]


class DocumentMetadata(BaseModel):
    id: str
    title: str
    kind: DocumentKind
    source_type: Literal["upload", "url"]
    source_name: str
    source_url: str | None = None
    mime_type: str | None = None
    created_at: datetime
    text_length: int = 0


class ImportUrlRequest(BaseModel):
    url: HttpUrl


class ImportUrlResponse(BaseModel):
    document: DocumentMetadata


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    document_id: str | None = None
    selected_text: str = ""
    provider: str | None = None
    model: str | None = None
    context_chunks: list[str] = []


class ChatSession(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    document_ids: list[str] = []
    messages: list[ChatMessage] = []


class ChatSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    document_ids: list[str] = []
    message_count: int = 0


class CreateChatRequest(BaseModel):
    title: str | None = None


class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class AttachDocumentsRequest(BaseModel):
    document_ids: list[str] = []


class ChatRequest(BaseModel):
    chat_id: str | None = None
    document_id: str | None = None
    question: str = Field(min_length=1)
    selected_text: str = ""
    location: str | None = None
    provider: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    chat: ChatSession
    answer: str
    provider: str
    model: str | None = None
    context_chunks: list[str] = []
