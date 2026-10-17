"""Invariant 1, test de réfutation : aucun nom d'établissement réel dans
app/ (code, gabarits, feuilles de style, scripts JS) ni dans tests/.

Les scripts de démonstration (scripts/) et les migrations de données
(migrations/) en sont exemptés. La liste des noms réels vit hors des
chemins contrôlés, dans .github/noms-etablissements-reels.txt, pour que ce
test ne contienne lui-même aucun nom réel.
"""

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DENYLIST = ROOT / ".github" / "noms-etablissements-reels.txt"
CONTROLLED_PATHS = ("app", "tests")
SKIPPED_DIRS = {"__pycache__", ".pytest_cache"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".pdf", ".mo"}


def _normalize(text: str) -> str:
    """Casse, accents, espaces et ponctuation neutralisés : "Val-Fictif",
    "VAL FICTIF" et "valfictif" donnent tous "valfictif"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if c.isalnum()).casefold()


def _load_denylist() -> tuple[list[tuple[str, str]], list[str]]:
    names, codes = [], []
    for raw in DENYLIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("code:"):
            codes.append(line.removeprefix("code:").strip())
        else:
            names.append((line, _normalize(line)))
    return names, codes


def _controlled_files():
    for folder in CONTROLLED_PATHS:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and not SKIPPED_DIRS.intersection(path.parts):
                yield path


def test_denylist_is_present_and_not_empty():
    names, codes = _load_denylist()
    assert names, f"{DENYLIST} ne contient aucun nom : le contrôle serait vide."
    assert codes


def test_no_real_institution_name_in_app_or_tests():
    names, codes = _load_denylist()
    code_patterns = [(code, re.compile(rf"\b{re.escape(code)}\b")) for code in codes]
    violations = []
    for path in _controlled_files():
        relative = path.relative_to(ROOT).as_posix()
        normalized_path = _normalize(relative)
        violations += [
            f"{relative} : nom de fichier contient « {name} »"
            for name, token in names
            if token in normalized_path
        ]
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            normalized = _normalize(line)
            violations += [
                f"{relative}:{number} : « {name} »" for name, token in names if token in normalized
            ]
            violations += [
                f"{relative}:{number} : code « {code} »"
                for code, pattern in code_patterns
                if pattern.search(line)
            ]
    assert not violations, "Nom d'établissement réel interdit (invariant 1) :\n" + "\n".join(
        violations
    )


def test_normalization_catches_variants():
    token = _normalize("Val Fictif")
    for variant in ("VAL-FICTIF", "val_fictif", "valfictif.urafiki.org", "Vâl Fïctif"):
        assert token in _normalize(variant)
