"""Garde-fou (#88) : dans chaque école fictive, au moins deux niveaux dont
les grilles divergent — nombre de cours, nombre de groupes, maxima qui
varient selon la période, au moins un cours hors du total général et un
cours par appréciation. Sans cette divergence, aucune affirmation de
généricité du moteur, des sous-totaux ou du rendu n'est prouvée.

Les grilles sont lues par le service réel (`colonnes_grille`), période
par période, et non dans la spécification des fixtures : le test mesure
ce que le moteur voit."""

import pytest

from app.security.tenant import resolve_tenant
from app.services.contenu_bulletin import colonnes_grille
from tests.conftest import TENANT_A_COURSES, TENANT_A_NIVEAUX, build_niveaux

EXIGENCES_PAR_GRILLE = ("maxima variables selon la période", "cours hors du total général",
                        "cours par appréciation")
DIVERGENCES_ENTRE_NIVEAUX = ("nombre de cours", "nombre de groupes", "maxima par période")


def _mesure(app, institution, niveau_grid, periods):
    with app.test_request_context("/", base_url=f"http://{institution.domain}"):
        resolve_tenant()
        par_periode = [colonnes_grille(niveau_grid.school_class, period) for period in periods]
    colonnes = par_periode[0]
    maxima = tuple(tuple(c.max_score for c in cols) for cols in par_periode)
    return {
        "nombre de cours": len(colonnes),
        "nombre de groupes": len({c.groupe_id for c in colonnes}),
        "maxima par période": maxima,
        "maxima variables selon la période": len(set(maxima)) > 1,
        "cours hors du total général": any(not c.included for c in colonnes),
        "cours par appréciation": any(c.is_appreciation for c in colonnes),
    }


def ecarts(mesures: dict) -> list[str]:
    """Every requirement of #88 that a school's niveaux fail; empty when
    the divergence holds."""
    problemes = []
    if len(mesures) < 2:
        problemes.append("moins de deux niveaux")
    for niveau, mesure in mesures.items():
        problemes += [f"{niveau} : aucun {e}" for e in EXIGENCES_PAR_GRILLE if not mesure[e]]
    valeurs = list(mesures.values())
    for axe in DIVERGENCES_ENTRE_NIVEAUX:
        if len({v[axe] for v in valeurs}) < len(valeurs):
            problemes.append(f"niveaux identiques sur « {axe} »")
    return problemes


def test_tenant_a_niveaux_diverge(app, tenant_a, tenant_a_structure, tenant_a_niveaux):
    mesures = {
        libelle: _mesure(app, tenant_a, grid, tenant_a_structure)
        for libelle, grid in tenant_a_niveaux.items()
    }
    assert ecarts(mesures) == []


def test_tenant_b_niveaux_diverge(app, tenant_b_world, tenant_b_niveaux):
    world = tenant_b_world
    mesures = {
        libelle: _mesure(app, world.institution, grid, world.periods)
        for libelle, grid in tenant_b_niveaux.items()
    }
    assert ecarts(mesures) == []


def test_the_two_schools_do_not_share_their_grids(
    app, tenant_a, tenant_a_structure, tenant_a_niveaux, tenant_b_world, tenant_b_niveaux
):
    a = {_mesure(app, tenant_a, g, tenant_a_structure)["maxima par période"]
         for g in tenant_a_niveaux.values()}
    b = {_mesure(app, tenant_b_world.institution, g, tenant_b_world.periods)["maxima par période"]
         for g in tenant_b_niveaux.values()}
    assert not a & b


def test_identical_grids_are_reported(app, db, tenant_a, tenant_a_structure, academic_year,
                                      section):
    """Réfutation de #88 : ramener les deux niveaux à une grille identique
    fait échouer le garde-fou, sur chacun des trois axes de divergence."""
    meme_grille = TENANT_A_NIVEAUX["5eme"]["groupes"]
    clones = build_niveaux(
        db, ecole_id=tenant_a.id, academic_year_id=academic_year.id, section_id=section.id,
        periods=tenant_a_structure, courses=TENANT_A_COURSES,
        spec={"5eme": {"ordre": 5, "groupes": meme_grille},
              "3eme": {"ordre": 3, "groupes": meme_grille}},
    )
    mesures = {
        libelle: _mesure(app, tenant_a, grid, tenant_a_structure)
        for libelle, grid in clones.items()
    }
    problemes = ecarts(mesures)
    for axe in DIVERGENCES_ENTRE_NIVEAUX:
        assert f"niveaux identiques sur « {axe} »" in problemes
    with pytest.raises(AssertionError):
        assert problemes == []


def test_a_grid_without_exclusion_or_appreciation_is_reported(
    app, db, tenant_a, tenant_a_structure, academic_year, section
):
    """Réfutation des exigences par grille : une grille sans cours exclu,
    sans appréciation et à maxima constants est signalée."""
    plate = [("Tout", True, [("FRA", "1", ("20", "20", "20"), True)])]
    grids = build_niveaux(
        db, ecole_id=tenant_a.id, academic_year_id=academic_year.id, section_id=section.id,
        periods=tenant_a_structure, courses=TENANT_A_COURSES,
        spec={"5eme": {"ordre": 5, "groupes": plate},
              "3eme": dict(TENANT_A_NIVEAUX["4eme"], ordre=3)},
    )
    mesures = {
        libelle: _mesure(app, tenant_a, grid, tenant_a_structure)
        for libelle, grid in grids.items()
    }
    assert sorted(p for p in ecarts(mesures) if p.startswith("5eme")) == sorted(
        f"5eme : aucun {e}" for e in EXIGENCES_PAR_GRILLE
    )
