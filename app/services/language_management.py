"""Helpers for managing learner language preferences."""

from __future__ import annotations

from .. import db
from ..i18n import ensure_language_code, language_label, normalise_language_code, translate_text
from ..models import Student


class LanguageSwitchError(RuntimeError):
    """Base class for language switching problems."""


class LanguageSwitchPermissionError(LanguageSwitchError):
    """Raised when a user attempts to update another student's language."""


class LanguageSwitchValidationError(LanguageSwitchError):
    """Raised when language switching input is invalid."""


def switch_student_language(
    student: Student,
    new_language: str,
    *,
    acting_student: Student | None = None,
) -> str:
    """Update the student's preferred language and return a summary message."""

    if student.id is None:
        raise LanguageSwitchValidationError("Student must be saved before changing language.")

    desired = normalise_language_code(new_language)
    if not desired:
        raise LanguageSwitchValidationError("Unsupported language requested.")

    if acting_student and acting_student.id != student.id:
        raise LanguageSwitchPermissionError("Students may only update their own language preference.")

    student.preferred_language = ensure_language_code(desired)
    db.session.commit()

    label = language_label(desired)
    return translate_text("Language switched to {label}.", ensure_language_code(desired), label=label)


__all__ = [
    "LanguageSwitchError",
    "LanguageSwitchPermissionError",
    "LanguageSwitchValidationError",
    "switch_student_language",
]
