import random
from datetime import datetime, time, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from faker import Faker
from PIL import Image

from library.models import Author, Book, Loan, Member

DEMO_PASSWORD = "exlibris-local"
AUTHOR_COUNT = 60
BOOK_COUNT = 200
MEMBER_COUNT = 120
RETURNED_LOAN_COUNT = 300
OPEN_LOAN_COUNT = 150
OVERDUE_LOAN_COUNT = 50


class Command(BaseCommand):
    help = "Delete the catalogue and load a demo library with covers and loans."

    def handle(self, *args, **options):
        random.seed(22)
        Faker.seed(22)
        fake = Faker()
        today = timezone.localdate()

        with transaction.atomic():
            self._clear()
            authors = self._create_authors(fake)
            books = self._create_books(fake, authors)
            members = self._create_members(fake, today)
            self._create_loans(books, members, today)
            self._create_users()

        self._report(today)

    def _clear(self):
        for book in Book.objects.exclude(cover=""):
            book.cover.delete(save=False)
        Loan.objects.all().delete()
        Book.objects.all().delete()
        Author.objects.all().delete()
        Member.objects.all().delete()
        get_user_model().objects.filter(username__in=["librarian", "staff"]).delete()

    def _create_authors(self, fake):
        authors = [Author(name=fake.unique.name()) for _ in range(AUTHOR_COUNT)]
        return Author.objects.bulk_create(authors)

    def _create_books(self, fake, authors):
        books = []
        for index in range(BOOK_COUNT):
            copies = random.choice((1, 1, 2, 2, 3))
            book = Book(
                title=fake.unique.sentence(nb_words=4).rstrip("."),
                isbn=f"978{index:010d}",
                copies=copies,
            )
            book.save()
            image = Image.new(
                "RGB",
                (60, 90),
                ((index * 47) % 256, (index * 91) % 256, (index * 13) % 256),
            )
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            book.cover.save(f"{index}.png", ContentFile(buffer.getvalue()), save=True)
            book.authors.add(*random.sample(authors, k=random.choice((1, 1, 2, 3))))
            books.append(book)
        return books

    def _create_members(self, fake, today):
        members = [
            Member(
                name=fake.unique.name(),
                email=fake.unique.email(),
                joined_on=today - timedelta(days=random.randint(30, 900)),
            )
            for _ in range(MEMBER_COUNT)
        ]
        return Member.objects.bulk_create(members)

    def _create_loans(self, books, members, today):
        slots = [book for book in books for _ in range(book.copies)]
        random.shuffle(slots)
        if len(slots) < OPEN_LOAN_COUNT + OVERDUE_LOAN_COUNT:
            raise CommandError("Not enough copies for the open loans.")

        open_loans = []
        member_open_counts = {member.pk: 0 for member in members}
        cursor = 0
        shuffled_members = members[:]
        random.shuffle(shuffled_members)
        needed = OPEN_LOAN_COUNT + OVERDUE_LOAN_COUNT
        for book in slots[:needed]:
            member, cursor = self._next_member(shuffled_members, member_open_counts, cursor)
            member_open_counts[member.pk] += 1
            overdue = len(open_loans) < OVERDUE_LOAN_COUNT
            open_loans.append(self._open_loan(book, member, today, overdue))

        returned = [
            self._returned_loan(random.choice(books), random.choice(members), today)
            for _ in range(RETURNED_LOAN_COUNT)
        ]
        Loan.objects.bulk_create(open_loans + returned)
        self._check_member_cap()

    def _next_member(self, members, counts, start):
        for offset in range(len(members)):
            index = (start + offset) % len(members)
            member = members[index]
            if counts[member.pk] < Loan.MEMBER_OPEN_LOAN_LIMIT:
                return member, (index + 1) % len(members)
        raise CommandError("Every member is already at the open-loan cap.")

    def _open_loan(self, book, member, today, overdue):
        if overdue:
            due_on = today - timedelta(days=random.randint(1, 21))
        else:
            due_on = today + timedelta(days=random.randint(0, 21))
        borrowed_on = due_on - timedelta(days=14)
        return Loan(book=book, member=member, borrowed_on=borrowed_on, due_on=due_on)

    def _returned_loan(self, book, member, today):
        borrowed_on = today - timedelta(days=random.randint(30, 200))
        due_on = borrowed_on + timedelta(days=21)
        returned_on = borrowed_on + timedelta(days=random.randint(1, 28))
        returned_at = timezone.make_aware(
            datetime.combine(returned_on, time(15, 0)),
            timezone.get_current_timezone(),
        )
        return Loan(
            book=book,
            member=member,
            borrowed_on=borrowed_on,
            due_on=due_on,
            returned_at=returned_at,
        )

    def _create_users(self):
        User = get_user_model()
        librarian = User.objects.create_superuser(
            "librarian",
            "librarian@exlibris.test",
            DEMO_PASSWORD,
        )
        librarian.groups.add(self._group("Admin"))
        staff = User.objects.create_user(
            "staff",
            "staff@exlibris.test",
            DEMO_PASSWORD,
            is_staff=True,
        )
        staff.groups.add(self._group("Staff"))

    def _group(self, name):
        try:
            return Group.objects.get(name=name)
        except Group.DoesNotExist as exc:
            raise CommandError("Run migrations before seeding. The Staff and Admin groups are missing.") from exc

    def _check_member_cap(self):
        over_cap = (
            Member.objects.annotate(
                open_loans=Count("loans", filter=Q(loans__returned_at__isnull=True))
            )
            .filter(open_loans__gt=Loan.MEMBER_OPEN_LOAN_LIMIT)
            .exists()
        )
        if over_cap:
            raise CommandError("Seed created a member with too many open loans.")

    def _report(self, today):
        overdue = Q(returned_at__isnull=True, due_on__lt=today)
        open_now = Q(returned_at__isnull=True, due_on__gte=today)
        self.stdout.write(f"Authors: {Author.objects.count()}")
        self.stdout.write(f"Books: {Book.objects.count()}")
        self.stdout.write(f"Members: {Member.objects.count()}")
        self.stdout.write(f"Returned loans: {Loan.objects.filter(returned_at__isnull=False).count()}")
        self.stdout.write(f"Open loans: {Loan.objects.filter(open_now).count()}")
        self.stdout.write(f"Overdue loans: {Loan.objects.filter(overdue).count()}")
        self.stdout.write("Sign in as librarian or staff. Password: " + DEMO_PASSWORD)
