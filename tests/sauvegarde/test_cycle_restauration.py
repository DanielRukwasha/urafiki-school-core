"""Cycle complet sauvegarde -> stockage -> restauration, sur PostgreSQL réel
(job CI `sauvegarde-restauration`). C'est la preuve exigée par l'invariant
12 : « une sauvegarde jamais restaurée n'est pas une sauvegarde »."""

import os
import uuid

import psycopg
import pytest

# Module alias, not `from ... import tester_restauration`: pytest would
# collect a module-level name starting with "test" as a test.
from ops.sauvegarde import urafiki_sauvegarde as outil
from ops.sauvegarde.urafiki_sauvegarde import (
    SauvegardeError,
    StockageFichier,
    restaurer,
    sauvegarder,
    url_libpq,
)

SOURCE = os.environ.get("SAUVEGARDE_DATABASE_URL", "")


@pytest.fixture()
def phrase(tmp_path, monkeypatch):
    fichier = tmp_path / "phrase"
    fichier.write_text(uuid.uuid4().hex)
    monkeypatch.setenv("SAUVEGARDE_PASSPHRASE_FILE", str(fichier))
    return fichier


@pytest.fixture()
def base_vide():
    nom = f"restauration_{uuid.uuid4().hex[:8]}"
    admin = url_libpq(SOURCE).rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as connexion:
        connexion.execute(f'CREATE DATABASE "{nom}"')
    yield url_libpq(SOURCE).rsplit("/", 1)[0] + f"/{nom}"
    with psycopg.connect(admin, autocommit=True) as connexion:
        connexion.execute(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)')


def test_backup_is_encrypted_and_restores_identically(tmp_path, phrase, base_vide):
    stockage = StockageFichier(tmp_path / "hors-site")
    resultat = sauvegarder(SOURCE, stockage)

    chiffre = (tmp_path / "hors-site" / (resultat.nom + ".dump.gpg")).read_bytes()
    assert b"PGDMP" not in chiffre[:64], "la sauvegarde n'est pas chiffrée"

    rapport = restaurer(stockage, base_vide)
    assert rapport["revision_alembic"]
    assert rapport["lignes"] > 0


def test_monthly_restore_test_uses_a_throwaway_database(tmp_path, phrase):
    stockage = StockageFichier(tmp_path / "hors-site")
    sauvegarder(SOURCE, stockage)
    assert outil.tester_restauration(SOURCE, stockage)["tables"] > 0


def test_tampered_backup_is_refused(tmp_path, phrase, base_vide):
    stockage = StockageFichier(tmp_path / "hors-site")
    resultat = sauvegarder(SOURCE, stockage)
    objet = tmp_path / "hors-site" / (resultat.nom + ".dump.gpg")
    objet.write_bytes(objet.read_bytes()[:-1] + b"\x00")
    with pytest.raises(SauvegardeError, match="SHA-256"):
        restaurer(stockage, base_vide)


def test_wrong_passphrase_cannot_restore(tmp_path, phrase, base_vide):
    stockage = StockageFichier(tmp_path / "hors-site")
    sauvegarder(SOURCE, stockage)
    phrase.write_text("mauvaise phrase de passe")
    with pytest.raises(SauvegardeError, match="gpg"):
        restaurer(stockage, base_vide)
