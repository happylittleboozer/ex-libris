from django.contrib import admin
from django.db.models import Q
from django.utils import timezone

from library.models import Author, Book, Loan, Member

admin.site.site_header = "Ex Libris"
admin.site.site_title = "Ex Libris"
admin.site.index_title = "Catalogue"


class LoanStateFilter(admin.SimpleListFilter):
    title = "state"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("open", "Open"), ("returned", "Returned")]

    def queryset(self, request, queryset):
        if self.value() == "open":
            return queryset.filter(returned_at__isnull=True)
        if self.value() == "returned":
            return queryset.filter(returned_at__isnull=False)
        return queryset


class OverdueFilter(admin.SimpleListFilter):
    title = "overdue"
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return [("yes", "Overdue"), ("no", "Not overdue")]

    def queryset(self, request, queryset):
        today = timezone.localdate()
        overdue = Q(returned_at__isnull=True, due_on__lt=today)
        if self.value() == "yes":
            return queryset.filter(overdue)
        if self.value() == "no":
            return queryset.exclude(overdue)
        return queryset


class LoanOnBookInline(admin.TabularInline):
    model = Loan
    fk_name = "book"
    extra = 0
    fields = ("member", "borrowed_on", "due_on", "returned_at", "status_label")
    readonly_fields = ("status_label",)
    autocomplete_fields = ("member",)

    @admin.display(description="Status")
    def status_label(self, loan):
        if not loan.pk:
            return "—"
        return loan.status


class LoanOnMemberInline(admin.TabularInline):
    model = Loan
    fk_name = "member"
    extra = 0
    fields = ("book", "borrowed_on", "due_on", "returned_at", "status_label")
    readonly_fields = ("status_label",)
    autocomplete_fields = ("book",)

    @admin.display(description="Status")
    def status_label(self, loan):
        if not loan.pk:
            return "—"
        return loan.status


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    list_display = ("name",)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author_names", "copies")
    list_filter = ("authors",)
    search_fields = ("title", "authors__name", "isbn")
    filter_horizontal = ("authors",)
    inlines = (LoanOnBookInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("authors")

    @admin.display(description="Authors")
    def author_names(self, book):
        return ", ".join(author.name for author in book.authors.all())


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "joined_on")
    search_fields = ("name", "email")
    inlines = (LoanOnMemberInline,)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("book", "member", "borrowed_on", "due_on", "status_label", "returned_at")
    list_filter = (LoanStateFilter, OverdueFilter, "due_on")
    search_fields = ("book__title", "book__authors__name", "member__name", "member__email")
    autocomplete_fields = ("book", "member")
    date_hierarchy = "due_on"
    actions = ("mark_selected_returned",)

    @admin.display(description="Status")
    def status_label(self, loan):
        return loan.status

    @admin.action(permissions=["change"], description="Mark selected loans returned")
    def mark_selected_returned(self, request, queryset):
        returned = 0
        skipped = 0
        for loan in queryset:
            if loan.returned_at is not None:
                skipped += 1
                continue
            loan.mark_returned()
            returned += 1
        self.message_user(
            request,
            f"Marked {returned} loans returned. Skipped {skipped} already returned.",
        )
