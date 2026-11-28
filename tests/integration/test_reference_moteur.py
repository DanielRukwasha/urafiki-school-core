"""Non-régression du moteur sur un fichier de valeurs attendues (#89).

`tests/fixtures/reference_moteur.json` donne, sur les niveaux divergents
des deux écoles fictives (#88), les cotes d'entrée et les résultats
attendus par élève et par période : points pondérés et possibles de
chaque ligne, total, pourcentage au centime, pourcentage affiché à la
précision de l'école, rang et décision automatique. Ces valeurs ont été
calculées indépendamment du moteur, en fractions exactes.

Le test passe par les chemins de production : `calculer_contenu` (le
contenu figé d'un bulletin) et `compute_class_consolidation` (la
délibération). Toute différence est listée avec sa valeur attendue et la
valeur obtenue, au centime près, en `Decimal`.

Les sous-totaux par groupe entreront dans le fichier avec #90."""

import datetime
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import pytest

from app.models.grading import Grade
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum, User
from app.security.tenant import resolve_tenant
from app.services.contenu_bulletin import calculer_contenu, inscriptions_actives
from app.services.deliberation_service import compute_class_consolidation
from app.services.grille_service import lignes_actives, resoudre_grille

REFERENCE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "reference_moteur.json").read_text("utf-8")
)
CENTIME = Decimal("0.01")


def _saisir(db, institution, year_id, grids, cotes_par_niveau, auteur):
    """Students, enrollments and grades of the reference, for one school."""
    for niveau, par_eleve in cotes_par_niveau.items():
        grid = grids[niveau]
        for matricule, periodes in par_eleve.items():
            student = Student(ecole_id=institution.id, matricule=matricule,
                              first_name="Élève", last_name=matricule)
            db.session.add(student)
            db.session.flush()
            enrollment = Enrollment(
                ecole_id=institution.id, student_id=student.id,
                school_class_id=grid.school_class.id, academic_year_id=year_id,
                enrollment_date=datetime.date(2025, 9, 1),
            )
            db.session.add(enrollment)
            db.session.flush()
            for period, cotes in zip(grid.periods, periodes, strict=True):
                for code, valeur in cotes.items():
                    ligne = grid.lignes[code]
                    numerique = not ligne.note_par_appreciation
                    db.session.add(Grade(
                        ecole_id=institution.id, enrollment_id=enrollment.id,
                        grille_cours_ligne_id=ligne.id, period_id=period.id,
                        score=Decimal(valeur) if numerique else None,
                        appreciation=None if numerique else valeur,
                        entered_by_id=auteur.id,
                    ))
    db.session.commit()


def _mesurer(app, institution, grid):
    """What the production paths compute, in the reference's shape."""
    codes = {ligne.id: code for code, ligne in grid.lignes.items()}
    periodes = []
    with app.test_request_context("/", base_url=f"http://{institution.domain}"):
        resolve_tenant()
        klass = grid.school_class
        for period in grid.periods:
            contenu = calculer_contenu(klass, period, {})
            consolidation = compute_class_consolidation(
                klass, period, lignes_actives(resoudre_grille(klass)), inscriptions_actives(klass)
            )
            decisions = {d["student_id"]: d["automatic_decision"]
                         for d in consolidation["decisions"]}
            obtenu = {}
            for eleve in contenu["eleves"]:
                total = eleve["total"]
                obtenu[eleve["matricule"]] = {
                    "lignes": {
                        codes[b["ligne_id"]]: {
                            "points": b["points"], "possible": b["possible"],
                            "inclus": b["inclus"],
                        }
                        for b in total["detail"]
                    },
                    "total": {
                        "points": total["points"],
                        "possible": total["possible"],
                        "pourcentage": None if total["pourcentage"] is None
                        else str(Decimal(total["pourcentage"]).quantize(
                            CENTIME, rounding=ROUND_HALF_UP)),
                        "pourcentage_affiche": total["pourcentage_affiche"],
                    },
                    "rang": eleve["rang"],
                    "decision": decisions[eleve["matricule"]],
                }
            periodes.append(obtenu)
    return periodes


def _egal(attendu, obtenu, cle):
    if isinstance(attendu, str) and isinstance(obtenu, str) and cle != "pourcentage_affiche":
        try:
            return Decimal(attendu) == Decimal(obtenu)
        except InvalidOperation:
            pass
    # pourcentage_affiche is compared as text: its number of decimals is
    # part of what is displayed.
    return attendu == obtenu


def ecarts(attendu, obtenu, chemin=""):
    """Every difference between the reference and what was computed, as
    « chemin : attendu X, obtenu Y »."""
    if isinstance(attendu, dict) and isinstance(obtenu, dict):
        lignes = []
        for cle in sorted(attendu.keys() | obtenu.keys(), key=str):
            sous = f"{chemin}/{cle}" if chemin else str(cle)
            if cle not in obtenu:
                lignes.append(f"{sous} : attendu {attendu[cle]!r}, absent du calcul")
            elif cle not in attendu:
                lignes.append(f"{sous} : absent de la référence, obtenu {obtenu[cle]!r}")
            else:
                lignes += ecarts(attendu[cle], obtenu[cle], sous)
        return lignes
    if isinstance(attendu, list) and isinstance(obtenu, list) and len(attendu) == len(obtenu):
        lignes = []
        for index, (a, o) in enumerate(zip(attendu, obtenu, strict=True), start=1):
            lignes += ecarts(a, o, f"{chemin}/période {index}")
        return lignes
    if _egal(attendu, obtenu, chemin.rsplit("/", 1)[-1]):
        return []
    return [f"{chemin} : attendu {attendu!r}, obtenu {obtenu!r}"]


class _Grid:
    def __init__(self, niveau_grid, periods):
        self.school_class = niveau_grid.school_class
        self.lignes = niveau_grid.lignes
        self.periods = periods


@pytest.fixture()
def ecoles(db, make_user, tenant_a, tenant_a_structure, academic_year, tenant_a_niveaux,
           tenant_b_world, tenant_b_niveaux):
    """Both fictitious schools with the reference grades entered."""
    auteur_a, _ = make_user(email="saisie@alpha.example", role=RoleEnum.DIRECTION)
    world = tenant_b_world
    resultat = {}
    for cle, institution, year_id, niveaux, periods, auteur in (
        ("tenant_a", tenant_a, academic_year.id, tenant_a_niveaux, tenant_a_structure, auteur_a),
        ("tenant_b", world.institution, world.academic_year.id, tenant_b_niveaux,
         world.periods, world.direction),
    ):
        grids = {niveau: _Grid(grid, periods) for niveau, grid in niveaux.items()}
        assert grids.keys() == REFERENCE["ecoles"][cle]["niveaux"].keys(), cle
        cotes = {n: v["cotes"] for n, v in REFERENCE["ecoles"][cle]["niveaux"].items()}
        _saisir(db, institution, year_id, grids, cotes, auteur)
        resultat[cle] = (institution, grids)
    assert isinstance(auteur_a, User) and isinstance(world.direction, User)
    return resultat


AFFICHE = "/pourcentage_affiche : "


def _tous_les_ecarts(app, ecoles):
    lignes = []
    for cle, (institution, grids) in ecoles.items():
        for niveau, grid in grids.items():
            attendu = REFERENCE["ecoles"][cle]["niveaux"][niveau]["periodes"]
            lignes += ecarts(attendu, _mesurer(app, institution, grid), f"{cle}/{niveau}")
    return lignes


def _rapport(lignes):
    return "Écarts avec tests/fixtures/reference_moteur.json :\n" + "\n".join(lignes)


def test_engine_matches_the_reference_file(app, ecoles):
    lignes = [ligne for ligne in _tous_les_ecarts(app, ecoles) if AFFICHE not in ligne]
    assert not lignes, _rapport(lignes)


@pytest.mark.xfail(
    strict=True,
    reason="#129 : le contenu figé arrondit encore à 2 décimales, et non à la "
           "précision configurée de l'école (Beta : 1). Ce test passera à la "
           "fusion de #129 ; retirer alors ce marqueur (strict : un XPASS échoue).",
)
def test_displayed_percentage_uses_the_school_precision(app, ecoles):
    lignes = [ligne for ligne in _tous_les_ecarts(app, ecoles) if AFFICHE in ligne]
    assert not lignes, _rapport(lignes)


def test_a_changed_ponderation_is_reported_with_the_gap(app, db, ecoles):
    """Réfutation de #89 : une pondération modifiée (ALG en 5eme, 5 → 6)
    fait échouer la comparaison, avec l'écart affiché."""
    _, grids = ecoles["tenant_a"]
    grids["5eme"].lignes["ALG"].ponderation = Decimal("6")
    db.session.commit()
    lignes = _tous_les_ecarts(app, ecoles)
    lignes = [ligne for ligne in lignes if AFFICHE not in ligne]
    assert "tenant_a/5eme/période 1/EFA-5-01/lignes/ALG/points : attendu '60', obtenu '72.00000'" \
        in lignes, _rapport(lignes)
    assert ("tenant_a/5eme/période 1/EFA-5-01/total/pourcentage : attendu '68.18', obtenu '67.50'"
            in lignes)
    assert all(ligne.startswith("tenant_a/5eme/") for ligne in lignes)


def test_the_reference_covers_the_divergent_cases():
    """The file exercises what #88 made divergent and what the engine
    decides: a tie, an ungraded student, an excluded line or group, an
    appreciation, every automatic decision, both display precisions."""
    def periodes(cle):
        for niveau in REFERENCE["ecoles"][cle]["niveaux"].values():
            yield from niveau["periodes"]

    resultats = [a for cle in REFERENCE["ecoles"] for p in periodes(cle) for a in p.values()]
    assert {a["decision"] for a in resultats} == {"ADMITTED", "DEFERRED", "MANUAL"}
    assert any(a["rang"] is None for a in resultats)
    assert any(
        [a["rang"] for a in p.values()].count(1) > 1 or [a["rang"] for a in p.values()].count(2) > 1
        for cle in REFERENCE["ecoles"] for p in periodes(cle)
    )
    assert any(not ligne["inclus"] for a in resultats for ligne in a["lignes"].values())
    affiches = {len(a["total"]["pourcentage_affiche"].split(".")[1])
                for a in resultats if a["total"]["pourcentage_affiche"]}
    assert affiches == {1, 2}
