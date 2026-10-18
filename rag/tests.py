"""Endpoint tests. The Gemini / Chroma calls are mocked, so no API key is needed.

Run with:  python manage.py test
"""
import json
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from rag import services
from rag.models import Book

TMP_MEDIA = tempfile.mkdtemp()
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/")  # sets the csrftoken cookie
        self.token = self.client.cookies["csrftoken"].value

    def post(self, url, **kwargs):
        return self.client.post(url, HTTP_X_CSRFTOKEN=self.token, **kwargs)

    def upload(self, name="Atomic_Habits.pdf", data=PDF_BYTES):
        return self.post("/api/books/upload/", data={"file": SimpleUploadedFile(name, data)})

    def test_home_page_loads(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Ask your books")

    def test_post_without_csrf_is_rejected(self):
        res = Client(enforce_csrf_checks=True).post("/api/chat/", data="{}", content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_upload_indexes_book(self):
        with mock.patch.object(services, "ingest_book", return_value=(12, 30)) as ingest:
            res = self.upload()
        self.assertEqual(res.status_code, 201)
        book = res.json()["book"]
        self.assertEqual(book["title"], "Atomic Habits")
        self.assertEqual((book["pages"], book["chunks"]), (12, 30))
        ingest.assert_called_once()
        self.assertEqual(Book.objects.count(), 1)

    def test_upload_rejects_non_pdf(self):
        self.assertEqual(self.upload("notes.txt", b"hello").status_code, 400)
        self.assertEqual(self.upload("fake.pdf", b"not really a pdf").status_code, 400)
        self.assertEqual(Book.objects.count(), 0)

    def test_upload_failure_cleans_up(self):
        with mock.patch.object(services, "ingest_book", side_effect=services.IngestError("No readable text")), \
             mock.patch.object(services, "delete_book_vectors"):
            res = self.upload()
        self.assertEqual(res.status_code, 422)
        self.assertIn("No readable text", res.json()["error"])
        self.assertEqual(Book.objects.count(), 0)

    def test_upload_unexpected_error_is_generic(self):
        with mock.patch.object(services, "ingest_book", side_effect=RuntimeError("boom secret")), \
             mock.patch.object(services, "delete_book_vectors"):
            res = self.upload()
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("secret", res.json()["error"])
        self.assertEqual(Book.objects.count(), 0)

    def test_list_and_delete(self):
        with mock.patch.object(services, "ingest_book", return_value=(5, 9)):
            book_id = self.upload().json()["book"]["id"]
        self.assertEqual(len(self.client.get("/api/books/").json()["books"]), 1)
        with mock.patch.object(services, "delete_book_vectors") as gone:
            res = self.post(f"/api/books/{book_id}/delete/")
        self.assertEqual(res.status_code, 200)
        gone.assert_called_once_with(book_id)
        self.assertEqual(Book.objects.count(), 0)

    def test_chat_requires_a_book(self):
        res = self.post("/api/chat/", data=json.dumps({"question": "Hi"}), content_type="application/json")
        self.assertEqual(res.status_code, 400)

    def test_chat_returns_answer_and_sources(self):
        with mock.patch.object(services, "ingest_book", return_value=(5, 9)):
            book_id = self.upload().json()["book"]["id"]
        fake = {"answer": "Habits compound.", "sources": [{"book": "Atomic Habits", "page": 4}]}
        with mock.patch.object(services, "answer_question", return_value=fake) as ask:
            res = self.post(
                "/api/chat/",
                data=json.dumps({"question": "What is the main idea?", "book_ids": [book_id]}),
                content_type="application/json",
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), fake)
        ask.assert_called_once_with("What is the main idea?", [book_id])

    def test_chat_validates_input(self):
        with mock.patch.object(services, "ingest_book", return_value=(1, 1)):
            self.upload()
        for body in ({"question": "   "}, {"question": "x" * 2001}, {"question": "ok", "book_ids": [999]},
                     {"question": "ok", "book_ids": ["abc"]}):
            res = self.post("/api/chat/", data=json.dumps(body), content_type="application/json")
            self.assertEqual(res.status_code, 400, body)

    def test_chat_model_error_is_friendly(self):
        with mock.patch.object(services, "ingest_book", return_value=(1, 1)):
            self.upload()
        with mock.patch.object(services, "answer_question", side_effect=RuntimeError("API key leak?")):
            res = self.post("/api/chat/", data=json.dumps({"question": "Hello?"}), content_type="application/json")
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("leak", res.json()["error"])


class AnswerQuestionTests(TestCase):
    """answer_question() with a fake retriever and LLM."""

    def _doc(self, text, title, page):
        return mock.Mock(page_content=text, metadata={"book_title": title, "page": page})

    def test_sources_are_deduplicated_and_sorted(self):
        docs = [self._doc("a", "B", 3), self._doc("b", "A", 9), self._doc("c", "B", 3)]
        store = mock.Mock()
        store.as_retriever.return_value.invoke.return_value = docs
        llm = mock.Mock()
        llm.invoke.return_value = "An answer."
        prompt = mock.Mock()
        prompt.invoke.return_value.to_string.return_value = "final prompt"
        with mock.patch.object(services, "get_vectorstore", return_value=store), \
             mock.patch.object(services, "get_llm", return_value=llm), \
             mock.patch.object(services, "get_prompt", return_value=prompt):
            result = services.answer_question("q", [1, 2])
        self.assertEqual(result["sources"], [{"book": "A", "page": 9}, {"book": "B", "page": 3}])
        kwargs = store.as_retriever.call_args.kwargs
        self.assertEqual(kwargs["search_type"], "mmr")
        self.assertEqual(kwargs["search_kwargs"]["filter"], {"book_id": {"$in": [1, 2]}})

    def test_not_found_answer_has_no_sources(self):
        store = mock.Mock()
        store.as_retriever.return_value.invoke.return_value = [self._doc("a", "A", 1)]
        llm = mock.Mock()
        llm.invoke.return_value = "I could not find the answer in the document"
        prompt = mock.Mock()
        prompt.invoke.return_value.to_string.return_value = "p"
        with mock.patch.object(services, "get_vectorstore", return_value=store), \
             mock.patch.object(services, "get_llm", return_value=llm), \
             mock.patch.object(services, "get_prompt", return_value=prompt):
            result = services.answer_question("q")
        self.assertEqual(result["sources"], [])
