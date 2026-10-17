"""Rétention des sauvegardes : 7 quotidiennes, 4 hebdomadaires, 3 mensuelles."""

from datetime import UTC, datetime, timedelta

import pytest

from ops.sauvegarde.urafiki_sauvegarde import (
    SauvegardeError,
    StockageFichier,
    a_conserver,
    appliquer_retention,
    horodatage_de,
    nom_sauvegarde,
    ouvrir_stockage,
    url_libpq,
)

DEBUT = datetime(2026, 1, 1, 2, 30, tzinfo=UTC)


def _quotidiennes(jours):
    return [DEBUT + timedelta(days=n) for n in range(jours)]


def test_one_year_of_daily_backups_keeps_7_4_3():
    sauvegardes = _quotidiennes(365)
    garder = a_conserver(sauvegardes)
    plus_recente = max(sauvegardes)

    quotidiennes = {h for h in garder if plus_recente - h < timedelta(days=7)}
    assert len(quotidiennes) == 7
    assert len({h.isocalendar()[:2] for h in garder}) >= 4
    assert len({(h.year, h.month) for h in garder}) == 3
    # 7 days + at most 4 weeks + 3 months, overlapping: never more than 14.
    assert 7 < len(garder) <= 14
    assert plus_recente in garder


def test_each_weekly_and_monthly_keeps_the_newest_of_its_period():
    garder = a_conserver(_quotidiennes(120))
    for h in garder:
        meme_mois = [x for x in _quotidiennes(120) if (x.year, x.month) == (h.year, h.month)]
        meme_semaine = [x for x in _quotidiennes(120) if x.isocalendar()[:2] == h.isocalendar()[:2]]
        assert h in (max(meme_mois), max(meme_semaine)) or max(_quotidiennes(120)) - h < timedelta(days=7)


def test_few_backups_are_all_kept():
    assert a_conserver(_quotidiennes(3)) == set(_quotidiennes(3))
    assert a_conserver([]) == set()


def test_names_round_trip():
    assert horodatage_de(nom_sauvegarde(DEBUT) + ".dump.gpg") == DEBUT


def test_retention_deletes_dump_and_manifest_together(tmp_path):
    stockage = StockageFichier(tmp_path)
    for h in _quotidiennes(40):
        for suffixe in (".dump.gpg", ".manifest.json"):
            (tmp_path / (nom_sauvegarde(h) + suffixe)).write_text("x")
    supprimees = appliquer_retention(stockage)
    restantes = {n.split(".")[0] for n in stockage.lister()}
    assert supprimees and not set(supprimees) & restantes
    for nom in restantes:
        assert {nom + ".dump.gpg", nom + ".manifest.json"} <= set(stockage.lister())


def test_incomplete_backup_without_manifest_is_never_counted(tmp_path):
    stockage = StockageFichier(tmp_path)
    (tmp_path / (nom_sauvegarde(DEBUT) + ".dump.gpg")).write_text("x")
    assert appliquer_retention(stockage) == []


def test_destination_and_url_parsing(tmp_path):
    assert isinstance(ouvrir_stockage(tmp_path.as_uri()), StockageFichier)
    assert url_libpq("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    with pytest.raises(SauvegardeError):
        url_libpq("sqlite:///x.db")
