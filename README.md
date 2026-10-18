# Ask your books (Django + RAG)

A web interface for your PDF question-answering app. People can upload books (PDFs),
choose which books to search, and ask questions. Each answer shows the book and page it came from.

It uses the same pipeline as your `create_database.py` and `main.py`:
PyPDFLoader, RecursiveCharacterTextSplitter (1000 / 100), Gemini embeddings, Chroma,
MMR retriever (k=4, fetch_k=10, lambda_mult=0.5) and your system prompt.

## Run it (Windows)

```bash
cd rag_django
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env      # then open .env and set GOOGLE_API_KEY

python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000

## How to use

1. Drop a PDF on **Add a book** (left panel). Indexing takes from a few seconds to a few minutes, depending on the book size.
2. Tick the books you want to search. Untick to leave a book out.
3. Ask a question. Press Enter to send, Shift+Enter for a new line.
4. Use **Remove** to delete a book. Its PDF and its text in Chroma are both deleted.

## Project layout

```
rag_django/
  manage.py
  requirements.txt
  .env.example
  config/            settings, urls
  rag/
    models.py        Book (title, file, pages, chunks)
    services.py      ingest_book, delete_book_vectors, answer_question
    views.py         upload, list, delete, chat endpoints
    urls.py
    templates/rag/index.html
    static/rag/css/style.css
    static/rag/js/app.js
    tests.py         python manage.py test
```

Created when you run it: `db.sqlite3`, `media/books/` (uploaded PDFs) and `chroma_db/` (vectors).

## Notes

- **Model names** are in `.env` (`RAG_CHAT_MODEL`, `RAG_EMBEDDING_MODEL`). The chat model defaults to the name from your `main.py` (`gemini-3.8-flash`). If Gemini says the model is not found, change it there.
- **Scanned PDFs** (photos of pages) have no text, so they are rejected with a clear message. Run OCR on them first.
- **Old data:** the books you already put into `chroma_db` with `create_database.py` have no `book_id`, so this app can't filter or delete them. Upload them again here, or point `RAG_CHROMA_DIR` at a new folder.
- **Who can upload:** every visitor can upload and remove books. Before putting this online, protect those two endpoints with login (`@login_required`) or Django permissions.
- **Production:** set `DJANGO_DEBUG=0`, a real `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`, and serve media files with a real web server.
