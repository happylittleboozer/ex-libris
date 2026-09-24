from django.conf import settings


def google_login(request):
    return {"google_login": settings.GOOGLE_LOGIN_ENABLED}
