"""Validated report presentation; no school-specific strings or database access."""

from dataclasses import dataclass

from app.ui.theming import text

LABELS = {
    "fr": {
        "bulletin_title": "Bulletin de période",
        "ranking_title": "Palmarès de période",
        "student": "Élève",
        "student_id": "Matricule",
        "course": "Cours",
        "code": "Code",
        "coefficient": "Coefficient",
        "maximum": "Maximum",
        "score": "Cote",
        "weighted": "Points pondérés",
        "total": "Total pondéré",
        "result": "Résultat",
        "rank": "Rang",
        "entered": "Cotes saisies",
        "complete": "Complet",
        "provisional": "Résultat provisoire",
        "not_evaluated": "Non évalué",
        "empty": "Aucun élève inscrit.",
        "missing": "Les cotes manquantes sont exclues du calcul.",
        "preview": "APERÇU - NON OFFICIEL",
        "back": "Retour aux résultats",
        "download": "Télécharger le PDF A4",
        "page": "Page",
        "period_note": "Ce document de période ne constitue pas une décision de passage annuel.",
        "ranking_note": "Les ex æquo partagent le même rang. Les élèves sans cote ne sont pas classés.",
    },
    "en": {
        "bulletin_title": "Period report",
        "ranking_title": "Period ranking",
        "student": "Student",
        "student_id": "Student ID",
        "course": "Subject",
        "code": "Code",
        "coefficient": "Weight",
        "maximum": "Maximum",
        "score": "Score",
        "weighted": "Weighted points",
        "total": "Weighted total",
        "result": "Result",
        "rank": "Rank",
        "entered": "Scores entered",
        "complete": "Complete",
        "provisional": "Provisional result",
        "not_evaluated": "Not assessed",
        "empty": "No students enrolled.",
        "missing": "Missing scores are excluded from calculations.",
        "preview": "PREVIEW - NOT OFFICIAL",
        "back": "Back to results",
        "download": "Download A4 PDF",
        "page": "Page",
        "period_note": "This period report is not an annual promotion decision.",
        "ranking_note": "Tied students share a rank. Students without scores are not ranked.",
    },
}
COLUMN_LABELS = {
    "course": "course",
    "code": "code",
    "coefficient": "coefficient",
    "max_score": "maximum",
    "score": "score",
    "weighted": "weighted",
}
DEFAULT_COLUMNS = ("course", "coefficient", "max_score", "score")
RANKING_COLUMNS = ("rank", "student", "student_id", "entered", "result")


class ReportConfigError(ValueError):
    """Invalid presentation input; never evaluate user HTML, CSS or Jinja."""


@dataclass(frozen=True)
class ReportLayout:
    locale: str
    labels: dict
    columns: tuple
    ranking_columns: tuple
    header_lines: tuple
    legal_text: str
    signatures: tuple
    orientation: str
    header_alignment: str
    show_logo: bool
    font_size: int


def build_report_layout(configuration=None, locale="fr"):
    configuration = configuration if isinstance(configuration, dict) else {}
    locale = configuration.get("locale", locale)
    if locale not in LABELS:
        locale = "fr"
    labels = dict(LABELS[locale])
    overrides = configuration.get("labels", {})
    if not isinstance(overrides, dict):
        raise ReportConfigError("Les libellés doivent former un objet.")
    # Preview marking is a system guarantee, not an editable school label.
    for key, value in overrides.items():
        if key in labels and key != "preview":
            labels[key] = text(value, labels[key], 300)
    columns = configuration.get("columns", DEFAULT_COLUMNS)
    if (
        not isinstance(columns, tuple | list)
        or not 2 <= len(columns) <= len(COLUMN_LABELS)
        or any(not isinstance(key, str) or key not in COLUMN_LABELS for key in columns)
        or len(set(columns)) != len(columns)
        or not {"course", "score"}.issubset(columns)
    ):
        raise ReportConfigError("Choisissez des colonnes distinctes, incluant le cours et la cote.")
    ranking = configuration.get("ranking_columns", RANKING_COLUMNS)
    if (
        not isinstance(ranking, tuple | list)
        or not 2 <= len(ranking) <= len(RANKING_COLUMNS)
        or any(not isinstance(key, str) or key not in RANKING_COLUMNS for key in ranking)
        or len(set(ranking)) != len(ranking)
        or not {"student", "result"}.issubset(ranking)
    ):
        raise ReportConfigError("Le palmarès doit inclure l’élève et le résultat.")
    header = configuration.get("header_lines", [])
    signatures = configuration.get("signatures", [])
    for values in (header, signatures):
        if (
            not isinstance(values, tuple | list)
            or len(values) > 4
            or any(not isinstance(value, str) for value in values)
        ):
            raise ReportConfigError("Quatre lignes de texte maximum par bloc.")
    orientation = configuration.get("orientation", "portrait")
    alignment = configuration.get("header_alignment", "left")
    if orientation not in {"portrait", "landscape"} or alignment not in {"left", "center"}:
        raise ReportConfigError("Disposition non prise en charge.")
    size = configuration.get("font_size", 10)
    if type(size) is not int or not 9 <= size <= 12:
        raise ReportConfigError("La taille du texte doit être comprise entre 9 et 12 points.")
    return ReportLayout(
        locale,
        labels,
        tuple(columns),
        tuple(ranking),
        tuple(text(value, limit=300) for value in header),
        text(configuration.get("legal_text"), limit=2000),
        tuple(text(value, limit=150) for value in signatures),
        orientation,
        alignment,
        bool(configuration.get("show_logo", True)),
        size,
    )


def report_configuration(layout):
    return {
        "locale": layout.locale,
        "labels": layout.labels,
        "columns": list(layout.columns),
        "ranking_columns": list(layout.ranking_columns),
        "header_lines": list(layout.header_lines),
        "legal_text": layout.legal_text,
        "signatures": list(layout.signatures),
        "orientation": layout.orientation,
        "header_alignment": layout.header_alignment,
        "show_logo": layout.show_logo,
        "font_size": layout.font_size,
    }
