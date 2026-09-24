from django.db import migrations

CATALOGUE_MODELS = ("author", "book", "member", "loan")
PERMISSION_ACTIONS = ("add", "change", "delete", "view")


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    staff, _created = Group.objects.get_or_create(name="Staff")
    admin, _created = Group.objects.get_or_create(name="Admin")
    for model in CATALOGUE_MODELS:
        content_type, _created = ContentType.objects.get_or_create(
            app_label="library",
            model=model,
        )
        for action in PERMISSION_ACTIONS:
            permission, _created = Permission.objects.get_or_create(
                codename=f"{action}_{model}",
                content_type=content_type,
                defaults={"name": f"Can {action} {model}"},
            )
            admin.permissions.add(permission)
            if action == "view":
                staff.permissions.add(permission)


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["Staff", "Admin"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0003_alter_loan_due_on_alter_loan_returned_at"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]
