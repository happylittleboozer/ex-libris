from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

COVER_MAX_BYTES = 2 * 1024 * 1024
COVER_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
COVER_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_cover(upload):
    """Reject a new cover that is not a small JPEG, PNG, or WebP."""
    if not upload or getattr(upload, "_committed", False):
        return
    extension = Path(upload.name or "").suffix.lower().lstrip(".")
    if extension not in COVER_EXTENSIONS:
        raise ValidationError("Cover must be a JPEG, PNG, or WebP file.")
    if upload.size > COVER_MAX_BYTES:
        raise ValidationError("Cover must be 2 MB or smaller.")
    file = upload if hasattr(upload, "seek") and hasattr(upload, "read") else upload.file
    try:
        file.seek(0)
        with Image.open(file) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ValidationError("Cover must be a JPEG, PNG, or WebP file.") from None
    finally:
        file.seek(0)
    if image_format not in COVER_FORMATS:
        raise ValidationError("Cover must be a JPEG, PNG, or WebP file.")


class Author(models.Model):
    name = models.CharField(
        max_length=200,
        help_text="The name as it should appear on the catalogue entry.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(
        max_length=300,
        help_text="The title printed on the title page, without a subtitle unless the subtitle is how readers look it up.",
    )
    authors = models.ManyToManyField(
        Author,
        related_name="books",
        help_text="Every person named as an author. Add the author record first if it is not in the list.",
    )
    isbn = models.CharField(
        max_length=17,
        unique=True,
        null=True,
        blank=True,
        verbose_name="ISBN",
        help_text="ISBN-13, with or without hyphens. Leave blank only when the copy has no ISBN.",
    )
    copies = models.PositiveIntegerField(
        default=1,
        help_text=(
            "How many physical copies the library owns, including copies that are currently on loan. "
            "A new loan is refused when every copy is already out."
        ),
    )
    cover = models.ImageField(
        upload_to="covers/",
        blank=True,
        validators=[validate_cover],
        help_text="A JPEG, PNG, or WebP of the front cover, at most 2 MB. Used on the book list.",
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(copies__gte=1),
                name="book_copies_at_least_one",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.cover and not self.cover._committed:
            self.cover.field.run_validators(self.cover)
        return super().save(*args, **kwargs)


class Member(models.Model):
    name = models.CharField(
        max_length=200,
        help_text="The name the member uses at the desk.",
    )
    email = models.EmailField(
        unique=True,
        help_text="Used to tell two members with the same name apart. One address per member.",
    )
    joined_on = models.DateField(
        help_text="The day the member joined the library.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Loan(models.Model):
    MEMBER_OPEN_LOAN_LIMIT = 5

    book = models.ForeignKey(
        Book,
        on_delete=models.PROTECT,
        related_name="loans",
        help_text="The book that left the shelf. A book with loans cannot be deleted.",
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="loans",
        help_text=(
            "The member who has the book. A member with loans cannot be deleted. "
            f"A member can have at most {MEMBER_OPEN_LOAN_LIMIT} open loans."
        ),
    )
    borrowed_on = models.DateField(
        help_text="The day the member took the book.",
    )
    due_on = models.DateField(
        help_text=(
            "The day the book is expected back. Must be on or after the day it was borrowed. "
            "The loan is overdue from the following day if it has not been returned."
        ),
    )
    returned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When the book came back. Leave empty while the loan is still open. "
            "A return is recorded once and cannot be changed."
        ),
    )

    class Meta:
        ordering = ["due_on", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(due_on__gte=models.F("borrowed_on")),
                name="loan_due_on_not_before_borrowed_on",
            ),
        ]
        indexes = [
            models.Index(fields=["book", "returned_at"], name="loan_book_returned_idx"),
        ]

    def __str__(self):
        return f"{self.book} — {self.member}"

    @property
    def is_overdue(self):
        """True from the day after due_on, until the book is returned."""
        if self.returned_at is not None or self.due_on is None:
            return False
        return self.due_on < timezone.localdate()

    @property
    def status(self):
        if self.returned_at is not None:
            return "returned"
        if self.is_overdue:
            return "overdue"
        return "open"

    def mark_returned(self, when=None):
        if self.pk is None:
            raise ValidationError("Save the loan before marking it returned.")
        if self.returned_at is not None:
            raise ValidationError({"returned_at": "This loan has already been returned."})
        self.returned_at = when or timezone.now()
        self.save()

    def clean(self):
        super().clean()
        self._reject_changed_return()
        if self.returned_at is not None:
            return
        errors = {}
        if self.book_id and self._other_open_for_book() >= self.book.copies:
            errors["book"] = f"All {self.book.copies} copies are already on loan."
        if self.member_id and self._other_open_for_member() >= self.MEMBER_OPEN_LOAN_LIMIT:
            errors["member"] = (
                f"This member already has {self.MEMBER_OPEN_LOAN_LIMIT} open loans."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk and connection.features.has_select_for_update:
                Loan.objects.select_for_update().get(pk=self.pk)
            if self.returned_at is None:
                self._lock_parties()
            self.full_clean()
            return super().save(*args, **kwargs)

    def _reject_changed_return(self):
        if not self.pk:
            return
        previous = Loan.objects.filter(pk=self.pk).values_list("returned_at", flat=True).first()
        if previous is not None and self.returned_at != previous:
            raise ValidationError({"returned_at": "This loan has already been returned."})

    def _other_open_for_book(self):
        return self._other_open_loans().filter(book_id=self.book_id).count()

    def _other_open_for_member(self):
        return self._other_open_loans().filter(member_id=self.member_id).count()

    def _other_open_loans(self):
        loans = Loan.objects.filter(returned_at__isnull=True)
        if self.pk:
            loans = loans.exclude(pk=self.pk)
        return loans

    def _lock_parties(self):
        if not connection.features.has_select_for_update:
            return
        if self.book_id:
            Book.objects.select_for_update().get(pk=self.book_id)
        if self.member_id:
            Member.objects.select_for_update().get(pk=self.member_id)
