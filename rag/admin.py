from django.contrib import admin

from .models import Book


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "pages", "chunks", "uploaded_at")
    readonly_fields = ("pages", "chunks", "uploaded_at")
