from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from library.models import COVER_MAX_BYTES, Author, Book, Loan, Member


def cover_upload(image_format, name):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue())


class LendingRuleTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.author = Author.objects.create(name="Ada Lovelace")
        self.member = Member.objects.create(
            name="Ada",
            email="ada@exlibris.test",
            joined_on=today,
        )
        self.other = Member.objects.create(
            name="Grace",
            email="grace@exlibris.test",
            joined_on=today,
        )

    def make_book(self, copies, title="The Book"):
        book = Book.objects.create(title=title, copies=copies)
        book.authors.add(self.author)
        return book

    def make_loan(self, book, member, due_on=None):
        today = timezone.localdate()
        due_on = today + timedelta(days=14) if due_on is None else due_on
        return Loan.objects.create(
            book=book,
            member=member,
            borrowed_on=due_on - timedelta(days=7),
            due_on=due_on,
        )

    def test_loan_is_refused_when_every_copy_is_out(self):
        book = self.make_book(copies=1)
        self.make_loan(book, self.member)

        with self.assertRaises(ValidationError) as raised:
            self.make_loan(book, self.other)

        self.assertIn("already on loan", raised.exception.message_dict["book"][0])

    def test_returned_loan_frees_the_copy(self):
        book = self.make_book(copies=1)
        loan = self.make_loan(book, self.member)
        loan.mark_returned()

        second = self.make_loan(book, self.other)

        self.assertIsNone(second.returned_at)

    def test_editing_an_open_loan_does_not_count_it_twice(self):
        book = self.make_book(copies=1)
        loan = self.make_loan(book, self.member)
        loan.due_on = loan.due_on + timedelta(days=1)

        loan.save()

        self.assertEqual(loan.status, "open")

    def test_member_cannot_hold_more_than_five_open_loans(self):
        book = self.make_book(copies=10, title="Shelf")
        for _ in range(Loan.MEMBER_OPEN_LOAN_LIMIT):
            self.make_loan(book, self.member)

        with self.assertRaises(ValidationError) as raised:
            self.make_loan(book, self.member)

        self.assertIn("5 open loans", raised.exception.message_dict["member"][0])

    def test_return_is_recorded_once(self):
        book = self.make_book(copies=1)
        loan = self.make_loan(book, self.member)

        loan.mark_returned()
        loan.refresh_from_db()

        self.assertIsNotNone(loan.returned_at)
        self.assertEqual(loan.status, "returned")
        with self.assertRaises(ValidationError) as raised:
            loan.mark_returned()
        self.assertIn("already been returned", raised.exception.message_dict["returned_at"][0])

        loan.returned_at = timezone.now()
        with self.assertRaises(ValidationError):
            loan.save()

    def test_overdue_starts_the_day_after_the_due_date(self):
        today = timezone.localdate()
        book = self.make_book(copies=2)
        overdue = self.make_loan(book, self.member, due_on=today - timedelta(days=1))
        due_today = self.make_loan(book, self.other, due_on=today)

        self.assertTrue(overdue.is_overdue)
        self.assertEqual(overdue.status, "overdue")
        self.assertFalse(due_today.is_overdue)
        self.assertEqual(due_today.status, "open")

        overdue.mark_returned()
        overdue.refresh_from_db()

        self.assertFalse(overdue.is_overdue)
        self.assertEqual(overdue.status, "returned")


class StaffLoanAdminTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        author = Author.objects.create(name="Ada Lovelace")
        self.book = Book.objects.create(title="The Book", copies=1)
        self.book.authors.add(author)
        member = Member.objects.create(name="Ada", email="ada@exlibris.test", joined_on=today)
        self.loan = Loan.objects.create(
            book=self.book,
            member=member,
            borrowed_on=today - timedelta(days=2),
            due_on=today + timedelta(days=7),
        )
        self.staff = get_user_model().objects.create_user(
            "staff",
            "staff@exlibris.test",
            "password",
            is_staff=True,
        )
        self.staff.groups.add(Group.objects.get(name="Staff"))

    def test_staff_sees_a_read_only_loan_page(self):
        self.client.force_login(self.staff)

        loan_list = self.client.get("/admin/library/loan/")
        loan_page = self.client.get(f"/admin/library/loan/{self.loan.pk}/change/")

        self.assertEqual(loan_list.status_code, 200)
        self.assertNotContains(loan_list, "Mark selected loans returned")
        self.assertNotContains(loan_list, "addlink")
        self.assertContains(loan_page, "View loan")
        self.assertNotContains(loan_page, 'name="due_on"')
        self.assertNotContains(loan_page, 'name="_save"')

        self.client.post(
            "/admin/library/loan/",
            {"action": "mark_selected_returned", "_selected_action": [self.loan.pk]},
        )
        self.loan.refresh_from_db()
        self.assertIsNone(self.loan.returned_at)

    def test_admin_still_sees_the_bulk_return_action(self):
        admin = get_user_model().objects.create_superuser("librarian", "librarian@exlibris.test", "password")
        self.client.force_login(admin)

        loan_list = self.client.get("/admin/library/loan/")

        self.assertContains(loan_list, "Mark selected loans returned")


class CoverValidationTests(TestCase):
    def setUp(self):
        self.author = Author.objects.create(name="Ada Lovelace")
        self.librarian = get_user_model().objects.create_superuser(
            "librarian",
            "librarian@exlibris.test",
            "password",
        )

    def save_book(self, upload, title="The Book"):
        book = Book(title=title, copies=1)
        if upload is not None:
            book.cover = upload
        book.save()
        book.authors.add(self.author)
        return book

    def test_jpeg_png_and_webp_covers_are_stored(self):
        for image_format, name in (("JPEG", "cover.jpg"), ("PNG", "cover.png"), ("WEBP", "cover.webp")):
            book = self.save_book(cover_upload(image_format, name), title=name)
            self.assertTrue(book.cover.name.endswith(name))
            self.assertGreater(book.cover.size, 0)

    def test_cover_with_the_wrong_extension_is_refused(self):
        with self.assertRaises(ValidationError) as raised:
            self.save_book(cover_upload("GIF", "cover.gif"))

        self.assertIn("JPEG, PNG, or WebP", raised.exception.messages[0])
        self.assertFalse(Book.objects.exists())

    def test_renamed_gif_is_refused(self):
        with self.assertRaises(ValidationError) as raised:
            self.save_book(cover_upload("GIF", "cover.jpg"))

        self.assertIn("JPEG, PNG, or WebP", raised.exception.messages[0])

    def test_file_pillow_cannot_read_is_refused(self):
        upload = SimpleUploadedFile("notes.png", b"not an image")

        with self.assertRaises(ValidationError) as raised:
            self.save_book(upload)

        self.assertIn("JPEG, PNG, or WebP", raised.exception.messages[0])

    def test_cover_over_2_mb_is_refused(self):
        upload = SimpleUploadedFile("cover.jpg", b"x" * (COVER_MAX_BYTES + 1))

        with self.assertRaises(ValidationError) as raised:
            self.save_book(upload)

        self.assertIn("2 MB", raised.exception.messages[0])

    def test_a_book_can_be_saved_without_a_cover(self):
        book = self.save_book(None)

        self.assertFalse(book.cover)

    def test_admin_rejects_a_gif_and_keeps_the_catalogue(self):
        self.client.force_login(self.librarian)
        response = self.client.post(
            "/admin/library/book/add/",
            {
                "title": "Bad cover",
                "copies": "1",
                "authors": str(self.author.pk),
                "isbn": "",
                "loans-TOTAL_FORMS": "0",
                "loans-INITIAL_FORMS": "0",
                "loans-MIN_NUM_FORMS": "0",
                "loans-MAX_NUM_FORMS": "1000",
                "cover": cover_upload("GIF", "cover.gif"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cover must be a JPEG, PNG, or WebP file.")
        self.assertFalse(Book.objects.filter(title="Bad cover").exists())

    def test_admin_file_input_offers_jpeg_png_and_webp(self):
        self.client.force_login(self.librarian)
        response = self.client.get("/admin/library/book/add/")

        self.assertContains(response, 'accept="image/jpeg,image/png,image/webp"')
