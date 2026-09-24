import logging

from django.conf import settings
from django.utils.text import capfirst

from library.models import Book, Loan

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.5-flash-lite"
QUESTION_MAX_LENGTH = 500
# Gemini rejects a client deadline shorter than 10 seconds.
ASSISTANT_TIMEOUT_MS = 10_000
ASSISTANT_UNAVAILABLE = (
    "The assistant is unavailable right now. You can still save this form."
)
ASSISTANT_MODELS = {"book": Book, "loan": Loan}

SYSTEM_INSTRUCTION = (
    "You help a librarian fill in this admin form. "
    "Answer only from the field notes. "
    "If the notes do not answer the question, say so. "
    "Use a few sentences."
)


class AssistantInputError(Exception):
    """The question or form name cannot be sent to the model."""


def form_notes(model):
    """Labels, help text, and choices for the fields on this form."""
    lines = [capfirst(str(model._meta.verbose_name))]
    fields = [field for field in model._meta.fields if not field.primary_key]
    fields.extend(model._meta.many_to_many)
    for field in fields:
        requirement = "required" if not field.blank else "optional"
        line = f"- {capfirst(str(field.verbose_name))} ({requirement}): {field.help_text}"
        if field.choices:
            choices = ", ".join(capfirst(str(label)) for _value, label in field.flatchoices)
            line = f"{line} Choices: {choices}."
        lines.append(" ".join(line.split()))
    return "\n".join(lines)


def ask(model_name, question):
    model = ASSISTANT_MODELS.get(model_name)
    if model is None:
        raise AssistantInputError("This form has no assistant.")
    cleaned = (question or "").strip()
    if not cleaned:
        raise AssistantInputError("Enter a question about this form.")
    if len(cleaned) > QUESTION_MAX_LENGTH:
        raise AssistantInputError(f"Keep the question under {QUESTION_MAX_LENGTH} characters.")
    if not settings.GEMINI_API_KEY:
        return ASSISTANT_UNAVAILABLE
    try:
        return complete(form_notes(model), cleaned)
    except Exception as exc:
        logger.warning("Form assistant failed: %s", type(exc).__name__)
        return ASSISTANT_UNAVAILABLE


def complete(notes, question):
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=ASSISTANT_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"Field notes:\n{notes}\n\nQuestion: {question}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            max_output_tokens=256,
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("empty assistant response")
    return text
