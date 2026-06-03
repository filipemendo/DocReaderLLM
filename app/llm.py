from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.config import Settings


@dataclass
class LLMAnswer:
    text: str
    provider: str
    model: str | None


class BaseProvider:
    provider = "base"

    def model_name(self, requested_model: str | None) -> str | None:
        return requested_model

    async def answer(
        self,
        *,
        question: str,
        selected_text: str,
        context_chunks: list[str],
        document_title: str,
        chat_history: list[dict[str, str]] | None,
        location: str | None,
        model: str | None,
    ) -> LLMAnswer:
        raise NotImplementedError

    async def stream_answer(self, **kwargs) -> AsyncIterator[str]:
        answer = await self.answer(**kwargs)
        yield answer.text


class FallbackProvider(BaseProvider):
    provider = "fallback"

    def model_name(self, requested_model: str | None) -> str | None:
        return None

    async def answer(
        self,
        *,
        question: str,
        selected_text: str,
        context_chunks: list[str],
        document_title: str,
        chat_history: list[dict[str, str]] | None,
        location: str | None,
        model: str | None,
    ) -> LLMAnswer:
        selected = selected_text.strip()
        context = "\n\n".join(context_chunks[:2]).strip()
        recent_history = chat_history[-4:] if chat_history else []
        parts = [
            "No external LLM provider is configured, so this is an extractive local response.",
            f"Question: {question.strip()}",
        ]
        if recent_history:
            parts.append(
                "Recent conversation:\n"
                + "\n".join(f"{item['role']}: {item['content']}" for item in recent_history)
            )
        if selected:
            parts.append(f"Selected passage:\n{selected}")
        if context:
            parts.append(f"Most relevant retrieved document context from {document_title}:\n{context}")
        parts.append("Add an API key in .env and choose a provider for full explanatory answers.")
        return LLMAnswer("\n\n".join(parts), self.provider, None)


class OpenAIProvider(BaseProvider):
    provider = "openai"

    def __init__(self, api_key: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)

    def model_name(self, requested_model: str | None) -> str | None:
        return requested_model or "gpt-4.1-mini"

    async def answer(self, **kwargs) -> LLMAnswer:
        model = self.model_name(kwargs["model"])
        messages = build_messages(**kwargs)
        response = await self.client.chat.completions.create(model=model, messages=messages)
        text = response.choices[0].message.content or ""
        return LLMAnswer(text.strip(), self.provider, model)

    async def stream_answer(self, **kwargs) -> AsyncIterator[str]:
        model = self.model_name(kwargs["model"])
        messages = build_messages(**kwargs)
        stream = await self.client.chat.completions.create(model=model, messages=messages, stream=True)
        async for chunk in stream:
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content
            if text:
                yield text


class AnthropicProvider(BaseProvider):
    provider = "anthropic"

    def __init__(self, api_key: str):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key)

    def model_name(self, requested_model: str | None) -> str | None:
        return requested_model or "claude-3-5-sonnet-latest"

    async def answer(self, **kwargs) -> LLMAnswer:
        model = self.model_name(kwargs["model"])
        messages = build_messages(**kwargs)
        system = messages[0]["content"]
        conversation = messages[1:]
        response = await self.client.messages.create(
            model=model,
            max_tokens=1200,
            system=system,
            messages=conversation,
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return LLMAnswer(text.strip(), self.provider, model)


class GeminiProvider(BaseProvider):
    provider = "gemini"

    def __init__(self, api_key: str):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self.genai = genai

    def model_name(self, requested_model: str | None) -> str | None:
        return requested_model or "gemini-1.5-flash"

    async def answer(self, **kwargs) -> LLMAnswer:
        model_name = self.model_name(kwargs["model"])
        messages = build_messages(**kwargs)
        prompt = "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)

        def run() -> str:
            model = self.genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text or ""

        text = await asyncio.to_thread(run)
        return LLMAnswer(text.strip(), self.provider, model_name)


def build_llm_provider(name: str, settings: Settings) -> BaseProvider:
    provider = (name or "fallback").lower()
    if provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key)
    if provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key)
    if provider == "gemini" and settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key)
    return FallbackProvider()


def build_messages(
    *,
    question: str,
    selected_text: str,
    context_chunks: list[str],
    document_title: str,
    chat_history: list[dict[str, str]] | None,
    location: str | None,
    model: str | None,
) -> list[dict[str, str]]:
    context = "\n\n---\n\n".join(context_chunks)
    selected = selected_text.strip() or "(No text was selected.)"
    place = location or "Unknown location"
    system = (
        "You are an expert reading companion for technical documents. "
        "Explain precisely, use the supplied document context, distinguish inference from source content, "
        "and say when the context is insufficient. Keep answers concise but useful. "
        "Wrap inline mathematical expressions in \\( ... \\) and display equations in \\[ ... \\]."
    )
    user = f"""Document scope: {document_title}
Location: {place}

Selected passage:
{selected}

Relevant document context:
{context or "(No additional context found.)"}

User question:
{question.strip()}

Answer the user's question about the selected passage. If useful, define notation, unpack assumptions, and relate the passage to the surrounding context."""
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in (chat_history or [])[-10:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": user}]
