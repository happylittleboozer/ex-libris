from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth.models import Group


class StaffSocialAccountAdapter(DefaultSocialAccountAdapter):
    """A new Google user can open the admin as Staff, and not as Admin."""

    def save_user(self, request, sociallogin, form=None):
        sociallogin.user.is_staff = True
        user = super().save_user(request, sociallogin, form)
        user.groups.add(Group.objects.get(name="Staff"))
        return user
