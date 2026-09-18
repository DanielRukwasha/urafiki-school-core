"""Presentation adapters for server-owned consolidation payloads.

This module deliberately performs no grade arithmetic. It validates shape and
normalizes display metadata while totals, percentages, ranks and decisions are
owned by the consolidation API.
"""

from dataclasses import dataclass


class ConsolidationPayloadError(ValueError):
    """Raised when a backend payload cannot be rendered safely."""


def _list(value, field):
    if not isinstance(value, list):
        raise ConsolidationPayloadError(f"{field} must be a list")
    return value


def _text(value, field, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > 500:
        raise ConsolidationPayloadError(f"{field} must be text")
    return value


def normalize_consolidation(payload):
    """Return a template-safe view without deriving any metric."""
    if not isinstance(payload, dict):
        raise ConsolidationPayloadError("consolidation payload must be an object")
    courses = _list(payload.get("courses", []), "courses")
    students = _list(payload.get("students", []), "students")
    decisions = _list(payload.get("decisions", []), "decisions")
    distribution = _list(payload.get("distribution", []), "distribution")
    for item in courses:
        if not isinstance(item, dict):
            raise ConsolidationPayloadError("course summary must be an object")
        _text(item.get("name"), "course.name", True)
        _text(item.get("status"), "course.status", True)
    for item in decisions:
        if not isinstance(item, dict):
            raise ConsolidationPayloadError("decision must be an object")
        for field in ("student_name", "automatic_decision"):
            _text(item.get(field), f"decision.{field}", True)
    return {
        "class_name": _text(payload.get("class_name"), "class_name", True),
        "period_name": _text(payload.get("period_name"), "period_name", True),
        "academic_year": _text(payload.get("academic_year"), "academic_year"),
        "courses": courses,
        "students": students,
        "decisions": decisions,
        "distribution": distribution,
        "class_average": payload.get("class_average"),
        "encoding_rate": payload.get("encoding_rate"),
        "students_without_grade": payload.get("students_without_grade"),
        "blocking_items": _list(payload.get("blocking_items", []), "blocking_items"),
        "publication": payload.get("publication", {}),
        "pagination": payload.get("pagination", {}),
    }


@dataclass(frozen=True)
class PublicationTransition:
    action: str
    label: str
    consequence: str
    irreversible: bool


TRANSITIONS = (
    PublicationTransition(
        "submit",
        "Soumettre pour consolidation",
        "Signale à la direction que l'encodage de la classe est prêt à être consolidé.",
        False,
    ),
    PublicationTransition(
        "consolidate", "Consolider", "Fige les données de la période pour la validation.", False
    ),
    PublicationTransition(
        "validate", "Valider", "Autorise la publication de la version prête.", False
    ),
    PublicationTransition(
        "publish", "Publier", "Rend cette version officielle et interdit sa modification.", True
    ),
)
