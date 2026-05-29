from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config import Settings


@dataclass
class LLMAnswer:
    text: str
    provider: str
    model: str | None


class BaseProvider:
    provider = "base"

    async def answer(
        self,
        *,
        question: str,
        selected_text: str,
        context_chunks: list[str],
        document_title: str,
        location: str | None,
        model: str | None,
    ) -> LLMAnswer:
        raise NotImplementedError


class FallbackProvider(BaseProvider):
    provider = "fallback"

    async def answer(
        self,
        *,
        question: str,
        selected_text: str,
        context_chunks: list[str],
        document_title: str,
        location: str | None,
        model: str | None,
    ) -> LLMAnswer:
        selected = selected_text.strip()
        context = "\n\n".join(context_chunks[:2]).strip()
        parts = [
            "No external LLM provider is configured, so this is an extractive local response.",
            f"Question: {question.strip()}",
        ]
        if selected:
            parts.append(f"Selected passage:\n{selected}")
        if context:
            parts.append(f"Most relevant nearby document context from {document_title}:\n{context}")
        parts.append("Add an API key in .env and choose a provider for full explanatory answers.")
        return LLMAnswer("\n\n".join(parts), self.provider, None)


class OpenAIProvider(BaseProvider):
    provider = "openai"

    def __init__(self, api_key: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)

    async def answer(self, **kwargs) -> LLMAnswer:
        model = kwargs["model"] or "gpt-4.1-mini"
        messages = build_messages(**kwargs)
        response = await self.client.chat.completions.create(model=model, messages=messages)
        text = response.choices[0].message.content or ""
        return LLMAnswer(text.strip(), self.provider, model)


class AnthropicProvider(BaseProvider):
    provider = "anthropic"

    def __init__(self, api_key: str):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key)

    async def answer(self, **kwargs) -> LLMAnswer:
        model = kwargs["model"] or "claude-3-5-sonnet-latest"
        messages = build_messages(**kwargs)
        system = messages[0]["content"]
        user = messages[1]["content"]
        response = await self.client.messages.create(
            model=model,
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return LLMAnswer(text.strip(), self.provider, model)


class GeminiProvider(BaseProvider):
    provider = "gemini"

    def __init__(self, api_key: str):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self.genai = genai

    async def answer(self, **kwargs) -> LLMAnswer:
        model_name = kwargs["model"] or "gemini-1.5-flash"
        messages = build_messages(**kwargs)
        prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"

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
    user = f"""Document: {document_title}
Location: {place}

Selected passage:
{selected}

Relevant document context:
{context or "(No additional context found.)"}

User question:
{question.strip()}

Answer the user's question about the selected passage. If useful, define notation, unpack assumptions, and relate the passage to the surrounding context."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
