from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from library.models import Author, Book, Loan, Member


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
