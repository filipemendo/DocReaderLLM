from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import ChatMessage, ChatSession, ChatSummary


class ChatStore:
    def __init__(self, data_dir: Path):
        self.chats_dir = data_dir / "chats"
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    def list_chats(self) -> list[ChatSummary]:
        chats = []
        for path in self.chats_dir.glob("*.json"):
            try:
                chat = ChatSession.model_validate_json(path.read_text())
            except Exception:
                continue
            chats.append(
                ChatSummary(
                    id=chat.id,
                    title=chat.title,
                    created_at=chat.created_at,
                    updated_at=chat.updated_at,
                    document_ids=chat.document_ids,
                    message_count=len(chat.messages),
                )
            )
        return sorted(chats, key=lambda chat: chat.updated_at, reverse=True)

    def create_chat(self, title: str | None = None) -> ChatSession:
        now = datetime.now(timezone.utc)
        chat = ChatSession(
            id=uuid.uuid4().hex,
            title=(title or "New chat").strip() or "New chat",
            created_at=now,
            updated_at=now,
            document_ids=[],
            messages=[],
        )
        self.save_chat(chat)
        return chat

    def get_chat(self, chat_id: str) -> ChatSession | None:
        path = self._path(chat_id)
        if not path.exists():
            return None
        return ChatSession.model_validate_json(path.read_text())

    def require_chat(self, chat_id: str | None) -> ChatSession:
        if chat_id:
            chat = self.get_chat(chat_id)
            if chat:
                return chat
        return self.create_chat()

    def save_chat(self, chat: ChatSession) -> ChatSession:
        chat.updated_at = datetime.now(timezone.utc)
        self._path(chat.id).write_text(chat.model_dump_json(indent=2))
        return chat

    def attach_documents(self, chat: ChatSession, document_ids: list[str]) -> ChatSession:
        seen = set(chat.document_ids)
        for document_id in document_ids:
            if document_id not in seen:
                chat.document_ids.append(document_id)
                seen.add(document_id)
        return self.save_chat(chat)

    def detach_document(self, chat: ChatSession, document_id: str) -> ChatSession:
        chat.document_ids = [item for item in chat.document_ids if item != document_id]
        return self.save_chat(chat)

    def append_message(self, chat: ChatSession, message: ChatMessage) -> ChatSession:
        chat.messages.append(message)
        if chat.title == "New chat" and message.role == "user":
            chat.title = infer_title(message.content)
        return self.save_chat(chat)

    def _path(self, chat_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", chat_id)
        return self.chats_dir / f"{safe_id}.json"


def infer_title(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "New chat"
    return normalized[:58] + ("..." if len(normalized) > 58 else "")
