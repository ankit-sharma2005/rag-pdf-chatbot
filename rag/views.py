import json
import logging
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import Book

logger = logging.getLogger("rag")

MAX_QUESTION_LENGTH = 2000


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


@ensure_csrf_cookie
def index(request):
    return render(request, "rag/index.html", {"max_mb": settings.RAG_MAX_UPLOAD_MB})


@require_GET
def book_list(request):
    return JsonResponse({"books": [b.as_dict() for b in Book.objects.all()]})


@require_POST
def book_upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        return _error("Choose a PDF to upload.")

    if not upload.name.lower().endswith(".pdf"):
        return _error("Only PDF files can be added.")

    max_bytes = settings.RAG_MAX_UPLOAD_MB * 1024 * 1024
    if upload.size > max_bytes:
        return _error(f"This file is larger than {settings.RAG_MAX_UPLOAD_MB} MB.", 413)

    header = upload.read(5)
    upload.seek(0)
    if header != b"%PDF-":
        return _error("This file is not a valid PDF.")

    title = request.POST.get("title", "").strip()
    if not title:
        title = Path(upload.name).stem.replace("_", " ").replace("-", " ").strip() or "Untitled book"

    book = Book.objects.create(title=title[:255], file=upload)
    try:
        pages, chunks = services.ingest_book(book)
    except services.IngestError as exc:
        book.delete()
        return _error(str(exc), 422)
    except Exception:
        logger.exception("Could not index book %s", book.id)
        book.delete()
        try:
            services.delete_book_vectors(book.id)
        except Exception:
            pass
        return _error(
            "This book could not be indexed. Check that GOOGLE_API_KEY is set, then try again.",
            500,
        )

    book.pages, book.chunks = pages, chunks
    book.save(update_fields=["pages", "chunks"])
    return JsonResponse({"book": book.as_dict()}, status=201)


@require_POST
def book_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    try:
        services.delete_book_vectors(book.id)
    except Exception:
        logger.exception("Could not remove vectors for book %s", book.id)
        return _error("Could not remove this book from the search index. Try again.", 500)
    book.delete()
    return JsonResponse({"deleted": pk})


@require_POST
def chat(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _error("Send the question as JSON.")

    question = str(payload.get("question", "")).strip()
    if not question:
        return _error("Type a question first.")
    if len(question) > MAX_QUESTION_LENGTH:
        return _error(f"Keep the question under {MAX_QUESTION_LENGTH} characters.")

    if not Book.objects.exists():
        return _error("Add a book before asking questions.")

    requested = payload.get("book_ids")
    if requested is None:
        book_ids = list(Book.objects.values_list("id", flat=True))
    else:
        try:
            wanted = {int(i) for i in requested}
        except (TypeError, ValueError):
            return _error("book_ids must be a list of numbers.")
        book_ids = list(Book.objects.filter(id__in=wanted).values_list("id", flat=True))
        if not book_ids:
            return _error("Select at least one book to search.")

    try:
        result = services.answer_question(question, book_ids)
    except Exception:
        logger.exception("Question failed")
        return _error(
            "The assistant could not answer right now. Check GOOGLE_API_KEY and the model name, then try again.",
            500,
        )
    return JsonResponse(result)
