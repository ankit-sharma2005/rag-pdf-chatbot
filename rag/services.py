"""RAG logic, taken from create_database.py and main.py.

Heavy imports (langchain, chroma) are done lazily inside functions so Django
starts fast and the rest of the app can be tested without them.
"""
import logging
import time
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger("rag")

NOT_FOUND = "I could not find the answer in the document"
EMBED_BATCH_SIZE = 50
MAX_RETRIES = 3


class IngestError(Exception):
    """Raised when a PDF can't be turned into searchable text."""


# ------------------------------------------------------------------ components
@lru_cache(maxsize=1)
def get_embeddings():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(model=settings.RAG_EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_vectorstore():
    from langchain_chroma import Chroma

    return Chroma(
        persist_directory=str(settings.RAG_CHROMA_DIR),
        embedding_function=get_embeddings(),
    )


@lru_cache(maxsize=1)
def get_llm():
    from langchain_google_genai import GoogleGenerativeAI

    return GoogleGenerativeAI(model=settings.RAG_CHAT_MODEL)


@lru_cache(maxsize=1)
def get_prompt():
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """you are a helpful AI assistant.
            use only the provided context to answer the question.
            IF the answer is not present in the context,
            say : 'I could not find the answer in the document'
            """,
            ),
            (
                "human",
                """context: {context}
        Question : {question}
        """,
            ),
        ]
    )


def _with_retry(fn):
    """Embedding APIs rate-limit sometimes; wait and try again."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 2 ** (attempt + 1)
            logger.warning("Embedding call failed, retrying in %ss", wait)
            time.sleep(wait)


# ------------------------------------------------------------------- ingestion
def ingest_book(book):
    """Load the PDF, split it, embed it and store it in Chroma.

    Returns (page_count, chunk_count).
    """
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    pages = PyPDFLoader(book.file.path).load()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.RAG_CHUNK_SIZE,
        chunk_overlap=settings.RAG_CHUNK_OVERLAP,
    )
    chunks = [c for c in splitter.split_documents(pages) if c.page_content.strip()]
    if not chunks:
        raise IngestError(
            "No readable text found in this PDF. If it is a scanned book, run OCR on it first."
        )

    for chunk in chunks:
        chunk.metadata = {
            "book_id": book.id,
            "book_title": book.title,
            "page": int(chunk.metadata.get("page", 0)) + 1,  # PyPDF pages start at 0
        }

    store = get_vectorstore()
    ids = [f"book{book.id}-{i}" for i in range(len(chunks))]
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        end = start + EMBED_BATCH_SIZE
        batch, batch_ids = chunks[start:end], ids[start:end]
        _with_retry(lambda: store.add_documents(batch, ids=batch_ids))

    return len(pages), len(chunks)


def delete_book_vectors(book_id):
    get_vectorstore().delete(where={"book_id": book_id})


# -------------------------------------------------------------------- answering
def answer_question(question, book_ids=None):
    """Retrieve with MMR (as in main.py), ask Gemini, return answer + sources."""
    search_kwargs = {
        "k": settings.RAG_RETRIEVER_K,
        "fetch_k": settings.RAG_RETRIEVER_FETCH_K,
        "lambda_mult": settings.RAG_RETRIEVER_LAMBDA,
    }
    if book_ids:
        search_kwargs["filter"] = {"book_id": {"$in": list(book_ids)}}

    retriever = get_vectorstore().as_retriever(search_type="mmr", search_kwargs=search_kwargs)
    docs = retriever.invoke(question)
    if not docs:
        return {"answer": NOT_FOUND + ".", "sources": []}

    context = "\n\n".join(doc.page_content for doc in docs)
    final_prompt = get_prompt().invoke({"context": context, "question": question})
    answer = get_llm().invoke(final_prompt.to_string())

    if NOT_FOUND.lower() in answer.lower():
        return {"answer": answer, "sources": []}

    sources, seen = [], set()
    for doc in docs:
        key = (doc.metadata.get("book_title"), doc.metadata.get("page"))
        if key not in seen:
            seen.add(key)
            sources.append({"book": key[0], "page": key[1]})
    sources.sort(key=lambda s: (s["book"] or "", s["page"] or 0))
    return {"answer": answer, "sources": sources}
