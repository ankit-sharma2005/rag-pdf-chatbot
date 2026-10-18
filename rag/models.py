from django.db import models


class Book(models.Model):
    """A PDF the user uploaded. Its text lives in Chroma, tagged with book_id."""

    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="books/")
    pages = models.PositiveIntegerField(default=0)
    chunks = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title

    def as_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "pages": self.pages,
            "chunks": self.chunks,
            "uploaded_at": self.uploaded_at.isoformat(),
        }

    def delete(self, *args, **kwargs):
        # Remove the PDF from disk together with the database row.
        if self.file:
            self.file.delete(save=False)
        return super().delete(*args, **kwargs)
