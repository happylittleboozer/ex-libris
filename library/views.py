from django.http import JsonResponse
from django.views.decorators.http import require_POST

from library.assistant import ASSISTANT_MODELS, ASSISTANT_UNAVAILABLE, AssistantInputError, ask


@require_POST
def form_assistant(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return _unavailable(status=403)
    model_name = (request.POST.get("model") or "").strip().lower()
    if model_name not in ASSISTANT_MODELS:
        return _unavailable(status=404)
    if not request.user.has_perm(f"library.view_{model_name}"):
        return _unavailable(status=403)
    try:
        answer = ask(model_name, request.POST.get("question"))
    except AssistantInputError as exc:
        return JsonResponse({"answer": str(exc)}, status=400)
    return JsonResponse({"answer": answer})


def _unavailable(status):
    return JsonResponse({"answer": ASSISTANT_UNAVAILABLE}, status=status)
