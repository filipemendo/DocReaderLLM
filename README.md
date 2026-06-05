# DocReaderLLM

A local browser-based reader that keeps technical documents and chatbot clarification in one UI.

The MVP supports:

- Uploading PDF, EPUB, HTML, Markdown, and plain text files
- Importing remote HTML/PDF/EPUB/Markdown/TXT documents by URL
- Importing GitHub Markdown pages from `github.com/.../blob/.../*.md` as raw Markdown
- Reading the document in the left pane
- Selecting text and asking a question in the chat pane
- Persistent chat sessions with conversational memory
- Attaching only selected saved documents to the current chat
- Whole-document lexical retrieval across attached documents
- Sending selected text plus nearby document context to OpenAI, Anthropic, Gemini, or a local fallback

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

## LLM Providers

Set one or more API keys in `.env`:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=gpt-4.1-mini
```

Supported provider values:

```text
default
fallback
openai
anthropic
gemini
```

If no key is configured, the fallback provider returns an extractive answer using the selected passage and retrieved document context. This keeps the reader usable without sending data to an external API.

## Notes

Remote HTML is fetched by the backend, sanitized, cached locally, and rendered inside a sandboxed iframe. PDF and EPUB files are served from the local cache after upload/import.

Chats are saved under `.data/chats/`. Documents are saved under `.data/documents/`. A chat can attach any subset of saved documents, and retrieval for an answer searches chunks across the whole attached set.
