from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/books/", views.book_list, name="book_list"),
    path("api/books/upload/", views.book_upload, name="book_upload"),
    path("api/books/<int:pk>/delete/", views.book_delete, name="book_delete"),
    path("api/chat/", views.chat, name="chat"),
]
