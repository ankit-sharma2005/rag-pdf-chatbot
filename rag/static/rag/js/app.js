(function () {
  "use strict";

  // ---------------------------------------------------------------- elements
  const $ = (id) => document.getElementById(id);
  const el = {
    shelf: $("shelf"),
    backdrop: $("backdrop"),
    openShelf: $("open-shelf"),
    closeShelf: $("close-shelf"),
    uploadForm: $("upload-form"),
    fileInput: $("file-input"),
    drop: $("drop"),
    uploadStatus: $("upload-status"),
    uploadText: $("upload-text"),
    toggleAll: $("toggle-all"),
    bookList: $("book-list"),
    shelfEmpty: $("shelf-empty"),
    scope: $("scope-note"),
    thread: $("thread"),
    welcome: $("welcome"),
    welcomeTitle: $("welcome-title"),
    welcomeText: $("welcome-text"),
    starters: $("starters"),
    askForm: $("ask-form"),
    question: $("question"),
    askBtn: $("ask-btn"),
    toast: $("toast"),
  };

  const MAX_MB = parseInt(document.body.dataset.maxMb || "50", 10);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const SPINES = ["#b5523b", "#2f8f83", "#c8922b", "#7a4a8c", "#4f7d4a", "#3f6fb0", "#a8456e", "#6b7280"];

  const state = { books: [], selected: new Set(), asking: false, uploading: false };
  let toastTimer = null;

  // ----------------------------------------------------------------- helpers
  function toast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, 4500);
  }

  async function api(url, options = {}) {
    const headers = Object.assign({ "X-CSRFToken": csrf }, options.headers || {});
    const res = await fetch(url, Object.assign({}, options, { headers, credentials: "same-origin" }));
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) throw new Error(data.error || "Something went wrong. Try again.");
    return data;
  }

  function spineColor(text) {
    let h = 0;
    for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
    return SPINES[h % SPINES.length];
  }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Small, safe Markdown subset: **bold**, *italic*, `code`, lists, paragraphs.
  function renderMarkdown(text) {
    const inline = (s) => escapeHtml(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");

    const out = [];
    let list = null; // "ul" | "ol"
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };

    text.replace(/\r\n/g, "\n").split("\n").forEach((raw) => {
      const line = raw.trimEnd();
      const bullet = line.match(/^\s*[*\-•]\s+(.*)/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)/);
      if (bullet || numbered) {
        const kind = bullet ? "ul" : "ol";
        if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
        out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
      } else if (line.trim() === "") {
        closeList();
      } else {
        closeList();
        out.push(`<p>${inline(line.trim())}</p>`);
      }
    });
    closeList();
    return out.join("");
  }

  function scrollToEnd() {
    el.thread.scrollTop = el.thread.scrollHeight;
  }

  // -------------------------------------------------------------- shelf (UI)
  function openShelf() { el.shelf.classList.add("is-open"); el.backdrop.hidden = false; }
  function closeShelf() { el.shelf.classList.remove("is-open"); el.backdrop.hidden = true; }

  function renderBooks() {
    el.bookList.innerHTML = "";
    const has = state.books.length > 0;
    el.shelfEmpty.hidden = has;
    el.toggleAll.hidden = !has;

    state.books.forEach((book) => {
      const on = state.selected.has(book.id);
      const li = document.createElement("li");
      li.className = "book" + (on ? " is-on" : "");
      li.style.setProperty("--spine", spineColor(book.title));

      const label = document.createElement("label");
      label.className = "book-pick";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = on;
      box.setAttribute("aria-label", "Search " + book.title);
      box.addEventListener("change", () => {
        box.checked ? state.selected.add(book.id) : state.selected.delete(book.id);
        renderBooks();
        updateScope();
      });
      const text = document.createElement("span");
      const t = document.createElement("span");
      t.className = "book-title";
      t.textContent = book.title;
      const m = document.createElement("span");
      m.className = "book-meta";
      m.textContent = book.pages + (book.pages === 1 ? " page" : " pages");
      text.append(t, m);
      label.append(box, text);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "book-remove";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", "Remove " + book.title);
      remove.addEventListener("click", () => removeBook(book));

      li.append(label, remove);
      el.bookList.append(li);
    });

    el.toggleAll.textContent = state.selected.size === state.books.length ? "Select none" : "Select all";
    updateScope();
  }

  function updateScope() {
    const total = state.books.length;
    const picked = state.books.filter((b) => state.selected.has(b.id));
    let note;
    if (total === 0) note = "Add a book to begin";
    else if (picked.length === 0) note = "No books selected";
    else if (picked.length === total) note = total === 1 ? "Searching " + picked[0].title : "Searching all " + total + " books";
    else if (picked.length === 1) note = "Searching " + picked[0].title;
    else note = "Searching " + picked.length + " of " + total + " books";
    el.scope.textContent = note;

    const canAsk = picked.length > 0 && !state.asking;
    el.question.disabled = picked.length === 0;
    el.askBtn.disabled = !canAsk;
    el.question.placeholder = total === 0
      ? "Add a book to start asking"
      : picked.length === 0 ? "Select a book to search" : "Ask a question about your books";

    // Welcome message follows what the person can do next
    if (total === 0) {
      el.welcomeTitle.textContent = "Put a book on the shelf";
      el.welcomeText.textContent = "Upload a PDF on the left. Answers come only from your books, and each one shows the pages it used.";
      el.starters.hidden = true;
    } else {
      el.welcomeTitle.textContent = "What do you want to know?";
      el.welcomeText.textContent = "Ask in your own words. If the books don't cover it, you'll be told so instead of getting a guess.";
      el.starters.hidden = false;
    }
  }

  async function loadBooks(selectId) {
    try {
      const data = await api("/api/books/");
      const previous = new Set(state.books.map((b) => b.id));
      state.books = data.books;
      const ids = new Set(state.books.map((b) => b.id));
      // keep earlier choices, select books we haven't seen before
      state.selected = new Set([...state.selected].filter((id) => ids.has(id)));
      state.books.forEach((b) => { if (!previous.has(b.id)) state.selected.add(b.id); });
      if (selectId) state.selected.add(selectId);
      renderBooks();
    } catch (err) {
      toast(err.message);
    }
  }

  async function removeBook(book) {
    if (!window.confirm('Remove "' + book.title + '" and its searchable text?')) return;
    try {
      await api("/api/books/" + book.id + "/delete/", { method: "POST" });
      state.selected.delete(book.id);
      toast("Removed " + book.title);
      await loadBooks();
    } catch (err) {
      toast(err.message);
    }
  }

  // ------------------------------------------------------------------ upload
  function setUploadStatus(text, isError) {
    el.uploadStatus.hidden = !text;
    el.uploadStatus.classList.toggle("is-error", !!isError);
    el.uploadText.textContent = text || "";
  }

  async function uploadFile(file) {
    if (state.uploading) return;
    if (!/\.pdf$/i.test(file.name)) { setUploadStatus("Only PDF files can be added.", true); return; }
    if (file.size > MAX_MB * 1024 * 1024) { setUploadStatus("This file is larger than " + MAX_MB + " MB.", true); return; }

    state.uploading = true;
    el.drop.setAttribute("aria-busy", "true");
    setUploadStatus("Reading " + file.name + ". Large books can take a few minutes.");

    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api("/api/books/upload/", { method: "POST", body: form });
      setUploadStatus("");
      toast("Added " + data.book.title + " (" + data.book.pages + " pages)");
      await loadBooks(data.book.id);
    } catch (err) {
      setUploadStatus(err.message, true);
    } finally {
      state.uploading = false;
      el.drop.removeAttribute("aria-busy");
      el.fileInput.value = "";
    }
  }

  el.fileInput.addEventListener("change", () => {
    if (el.fileInput.files[0]) uploadFile(el.fileInput.files[0]);
  });
  el.drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.fileInput.click(); }
  });
  ["dragenter", "dragover"].forEach((ev) =>
    el.drop.addEventListener(ev, (e) => { e.preventDefault(); el.drop.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    el.drop.addEventListener(ev, (e) => { e.preventDefault(); el.drop.classList.remove("is-over"); }));
  el.drop.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
  el.uploadForm.addEventListener("submit", (e) => e.preventDefault());

  el.toggleAll.addEventListener("click", () => {
    if (state.selected.size === state.books.length) state.selected.clear();
    else state.books.forEach((b) => state.selected.add(b.id));
    renderBooks();
  });

  // -------------------------------------------------------------------- chat
  function addQuestion(text) {
    el.welcome.hidden = true;
    const div = document.createElement("div");
    div.className = "q";
    div.textContent = text;
    el.thread.append(div);
    scrollToEnd();
  }

  function addReading() {
    const wrap = document.createElement("div");
    wrap.className = "a";
    const span = document.createElement("span");
    span.className = "reading";
    span.textContent = "Reading your books";
    wrap.append(span);
    el.thread.append(wrap);
    scrollToEnd();
    return wrap;
  }

  function fillAnswer(wrap, data, isError) {
    wrap.innerHTML = "";
    wrap.classList.toggle("is-error", !!isError);
    const body = document.createElement("div");
    body.className = "a-body";
    body.innerHTML = renderMarkdown(data.answer);
    wrap.append(body);

    if (data.sources && data.sources.length) {
      const cites = document.createElement("div");
      cites.className = "cites";
      const label = document.createElement("span");
      label.className = "cites-label";
      label.textContent = "From";
      cites.append(label);
      data.sources.forEach((s) => {
        const c = document.createElement("span");
        c.className = "cite";
        const b = document.createElement("span");
        b.className = "cite-book";
        b.textContent = s.book || "Book";
        c.append(b, document.createTextNode(s.page ? ", page " + s.page : ""));
        cites.append(c);
      });
      wrap.append(cites);
    }
    scrollToEnd();
  }

  async function ask(text) {
    const question = text.trim();
    if (!question || state.asking) return;
    const ids = state.books.filter((b) => state.selected.has(b.id)).map((b) => b.id);
    if (!ids.length) { toast("Select at least one book to search."); return; }

    state.asking = true;
    el.askBtn.disabled = true;
    el.question.value = "";
    autosize();
    addQuestion(question);
    const pending = addReading();

    try {
      const data = await api("/api/chat/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, book_ids: ids }),
      });
      fillAnswer(pending, data, false);
    } catch (err) {
      fillAnswer(pending, { answer: err.message, sources: [] }, true);
    } finally {
      state.asking = false;
      updateScope();
      el.question.focus();
    }
  }

  function autosize() {
    el.question.style.height = "auto";
    el.question.style.height = Math.min(el.question.scrollHeight, 180) + "px";
  }

  el.askForm.addEventListener("submit", (e) => { e.preventDefault(); ask(el.question.value); });
  el.question.addEventListener("input", autosize);
  el.question.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(el.question.value); }
  });
  el.starters.addEventListener("click", (e) => {
    const btn = e.target.closest(".starter");
    if (btn) ask(btn.textContent);
  });

  el.openShelf.addEventListener("click", openShelf);
  el.closeShelf.addEventListener("click", closeShelf);
  el.backdrop.addEventListener("click", closeShelf);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeShelf(); });

  loadBooks();
})();
