from django.db import models


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
        help_text="How many physical copies the library owns, including copies that are currently on loan.",
    )
    cover = models.ImageField(
        upload_to="covers/",
        blank=True,
        help_text="A JPEG, PNG, or WebP of the front cover. Used on the book list.",
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
        help_text="The member who has the book. A member with loans cannot be deleted.",
    )
    borrowed_on = models.DateField(
        help_text="The day the member took the book.",
    )
    due_on = models.DateField(
        help_text="The day the book is expected back. Must be on or after the day it was borrowed.",
    )
    returned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the book came back. Leave empty while the loan is still open.",
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
