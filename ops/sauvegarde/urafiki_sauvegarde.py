"""Sauvegardes chiffrées hors site et restauration vérifiée (invariant 12).

    python -m ops.sauvegarde.urafiki_sauvegarde sauvegarder
    python -m ops.sauvegarde.urafiki_sauvegarde lister
    python -m ops.sauvegarde.urafiki_sauvegarde restaurer --cible URL [--nom NOM]
    python -m ops.sauvegarde.urafiki_sauvegarde tester-restauration

Chaîne d'une sauvegarde :
1. relevé du nombre de lignes de chaque table et de la révision Alembic ;
2. pg_dump au format custom (-Fc) ;
3. chiffrement GPG symétrique AES-256 : déchiffrable par un humain avec la
   seule phrase de passe, sans ce code, en cas de sinistre ;
4. envoi vers le stockage hors site, avec un manifeste JSON (empreinte
   SHA-256, taille, révision, nombre de lignes par table) ;
5. relecture de l'objet envoyé (taille et empreinte) ; seulement ensuite,
   application de la rétention 7 quotidiennes / 4 hebdomadaires / 3
   mensuelles. Une sauvegarde non vérifiée ne déclenche jamais de
   suppression.

Restauration : téléchargement, contrôle de l'empreinte, déchiffrement,
pg_restore dans la base cible, puis comparaison de la révision Alembic et du
nombre de lignes de chaque table avec le manifeste. Un écart fait échouer la
commande. `tester-restauration` (mensuel) restaure la dernière sauvegarde
dans une base jetable, compare, puis la supprime.

Configuration, uniquement par variables d'environnement (voir
RESTAURATION.md) :
    SAUVEGARDE_DATABASE_URL       base à sauvegarder (rôle propriétaire ou
                                  BYPASSRLS, sinon pg_dump refuse : RLS)
    SAUVEGARDE_DESTINATION        s3://seau/prefixe  ou  file:///chemin
    SAUVEGARDE_PASSPHRASE_FILE    fichier contenant la phrase de passe GPG
    SAUVEGARDE_S3_ENDPOINT_URL    (optionnel) stockage compatible S3
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

PREFIXE = "urafiki-"
SUFFIXE_DUMP = ".dump.gpg"
SUFFIXE_MANIFESTE = ".manifest.json"
FORMAT_HORODATAGE = "%Y%m%dT%H%M%SZ"
RETENTION = {"quotidiennes": 7, "hebdomadaires": 4, "mensuelles": 3}


class SauvegardeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Rétention (pure, testée unitairement)
# ---------------------------------------------------------------------------


def a_conserver(horodatages: list[datetime], retention: dict[str, int] = RETENTION) -> set:
    """Grand-père / père / fils : la sauvegarde la plus récente de chacun
    des N derniers jours, des N dernières semaines ISO et des N derniers
    mois ayant une sauvegarde. La plus récente est toujours conservée."""
    tries = sorted(horodatages, reverse=True)
    conserver = set(tries[:1])
    for cle, nombre in (
        (lambda h: h.date(), retention["quotidiennes"]),
        (lambda h: h.isocalendar()[:2], retention["hebdomadaires"]),
        (lambda h: (h.year, h.month), retention["mensuelles"]),
    ):
        vus = []
        for horodatage in tries:
            periode = cle(horodatage)
            if periode in vus:
                continue
            vus.append(periode)
            if len(vus) > nombre:
                break
            conserver.add(horodatage)
    return conserver


def nom_sauvegarde(horodatage: datetime) -> str:
    return f"{PREFIXE}{horodatage.astimezone(UTC).strftime(FORMAT_HORODATAGE)}"


def horodatage_de(nom: str) -> datetime:
    brut = nom.removeprefix(PREFIXE).split(".", 1)[0]
    return datetime.strptime(brut, FORMAT_HORODATAGE).replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Stockage hors site
# ---------------------------------------------------------------------------


class Stockage:
    def envoyer(self, local: Path, nom: str) -> None: ...
    def recuperer(self, nom: str, local: Path) -> None: ...
    def lister(self) -> list[str]: ...
    def supprimer(self, nom: str) -> None: ...
    def taille(self, nom: str) -> int: ...


class StockageFichier(Stockage):
    """file:///chemin — pour les tests et un montage réseau. Ne constitue
    PAS à lui seul une sauvegarde hors site s'il pointe sur le serveur."""

    def __init__(self, racine: Path):
        self.racine = racine
        self.racine.mkdir(parents=True, exist_ok=True)

    def envoyer(self, local, nom):
        shutil.copyfile(local, self.racine / nom)

    def recuperer(self, nom, local):
        shutil.copyfile(self.racine / nom, local)

    def lister(self):
        return sorted(p.name for p in self.racine.iterdir() if p.name.startswith(PREFIXE))

    def supprimer(self, nom):
        (self.racine / nom).unlink()

    def taille(self, nom):
        return (self.racine / nom).stat().st_size


class StockageS3(Stockage):
    """s3://seau/prefixe — AWS S3 ou tout stockage compatible (Cloudflare R2,
    Backblaze B2, Scaleway...) via SAUVEGARDE_S3_ENDPOINT_URL."""

    def __init__(self, seau: str, prefixe: str):
        import boto3

        self.client = boto3.client(
            "s3", endpoint_url=os.environ.get("SAUVEGARDE_S3_ENDPOINT_URL") or None
        )
        self.seau = seau
        self.prefixe = prefixe.strip("/") + "/" if prefixe.strip("/") else ""

    def _cle(self, nom):
        return f"{self.prefixe}{nom}"

    def envoyer(self, local, nom):
        self.client.upload_file(str(local), self.seau, self._cle(nom))

    def recuperer(self, nom, local):
        self.client.download_file(self.seau, self._cle(nom), str(local))

    def lister(self):
        noms = []
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.seau, Prefix=self._cle(PREFIXE)
        ):
            noms += [obj["Key"].removeprefix(self.prefixe) for obj in page.get("Contents", [])]
        return sorted(noms)

    def supprimer(self, nom):
        self.client.delete_object(Bucket=self.seau, Key=self._cle(nom))

    def taille(self, nom):
        return self.client.head_object(Bucket=self.seau, Key=self._cle(nom))["ContentLength"]


def ouvrir_stockage(destination: str) -> Stockage:
    url = urlparse(destination)
    if url.scheme == "file":
        return StockageFichier(Path(url.path.lstrip("/") if os.name == "nt" else url.path))
    if url.scheme == "s3":
        return StockageS3(url.netloc, url.path)
    raise SauvegardeError(f"Destination non prise en charge : {destination!r} (s3:// ou file://).")


# ---------------------------------------------------------------------------
# PostgreSQL, GPG
# ---------------------------------------------------------------------------


def url_libpq(url: str) -> str:
    """postgresql+psycopg://... (SQLAlchemy) -> postgresql://... (libpq)."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgresql"):
        raise SauvegardeError("Les sauvegardes ne concernent que PostgreSQL.")
    return urlunparse(parsed._replace(scheme="postgresql"))


def _executer(commande: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(commande, check=True, capture_output=True, **kwargs)
    except FileNotFoundError as error:
        raise SauvegardeError(f"Outil introuvable : {commande[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip() if error.stderr else ""
        raise SauvegardeError(f"Échec de {commande[0]} : {detail}") from error


def releve_base(url: str) -> dict:
    """Révision Alembic et nombre de lignes de chaque table du schéma public."""
    import psycopg

    with psycopg.connect(url_libpq(url)) as connexion, connexion.cursor() as curseur:
        curseur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
        tables = [ligne[0] for ligne in curseur.fetchall()]
        comptes = {}
        for table in tables:
            curseur.execute(f'SELECT count(*) FROM public."{table}"')
            comptes[table] = curseur.fetchone()[0]
        revision = None
        if "alembic_version" in tables:
            curseur.execute("SELECT version_num FROM alembic_version")
            ligne = curseur.fetchone()
            revision = ligne[0] if ligne else None
    return {"revision_alembic": revision, "lignes": comptes}


def _phrase_de_passe() -> str:
    chemin = os.environ.get("SAUVEGARDE_PASSPHRASE_FILE")
    if not chemin or not Path(chemin).is_file():
        raise SauvegardeError("SAUVEGARDE_PASSPHRASE_FILE absent : chiffrement impossible.")
    return chemin


def _sha256(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with open(chemin, "rb") as fichier:
        for bloc in iter(lambda: fichier.read(1 << 20), b""):
            empreinte.update(bloc)
    return empreinte.hexdigest()


# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------


@dataclass
class Resultat:
    nom: str
    supprimees: list[str]


def sauvegarder(database_url: str, stockage: Stockage, maintenant: datetime | None = None):
    maintenant = maintenant or datetime.now(UTC)
    nom = nom_sauvegarde(maintenant)
    phrase = _phrase_de_passe()
    releve = releve_base(database_url)
    with tempfile.TemporaryDirectory() as dossier:
        dump = Path(dossier) / "base.dump"
        chiffre = Path(dossier) / (nom + SUFFIXE_DUMP)
        _executer(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump),
                   url_libpq(database_url)])
        _executer(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
                   "--passphrase-file", phrase, "--symmetric", "--cipher-algo", "AES256",
                   "--output", str(chiffre), str(dump)])
        manifeste = {
            "nom": nom,
            "cree_le": maintenant.isoformat(),
            "sha256": _sha256(chiffre),
            "taille": chiffre.stat().st_size,
            "chiffrement": "gpg-symmetric-aes256",
            "format": "pg_dump-custom",
            **releve,
        }
        chemin_manifeste = Path(dossier) / (nom + SUFFIXE_MANIFESTE)
        chemin_manifeste.write_text(json.dumps(manifeste, indent=2), encoding="utf-8")
        stockage.envoyer(chiffre, nom + SUFFIXE_DUMP)
        stockage.envoyer(chemin_manifeste, nom + SUFFIXE_MANIFESTE)

        # Relecture : l'objet hors site doit être exactement celui produit.
        if stockage.taille(nom + SUFFIXE_DUMP) != manifeste["taille"]:
            raise SauvegardeError("Taille de l'objet envoyé différente : rétention NON appliquée.")
        relu = Path(dossier) / "relu.gpg"
        stockage.recuperer(nom + SUFFIXE_DUMP, relu)
        if _sha256(relu) != manifeste["sha256"]:
            raise SauvegardeError("Empreinte de l'objet envoyé différente : rétention NON appliquée.")

    return Resultat(nom=nom, supprimees=appliquer_retention(stockage))


def sauvegardes_disponibles(stockage: Stockage) -> list[str]:
    noms = {n.removesuffix(SUFFIXE_DUMP) for n in stockage.lister() if n.endswith(SUFFIXE_DUMP)}
    manifestes = {
        n.removesuffix(SUFFIXE_MANIFESTE)
        for n in stockage.lister()
        if n.endswith(SUFFIXE_MANIFESTE)
    }
    return sorted(noms & manifestes)


def appliquer_retention(stockage: Stockage) -> list[str]:
    noms = sauvegardes_disponibles(stockage)
    par_horodatage = {horodatage_de(n): n for n in noms}
    garder = a_conserver(list(par_horodatage))
    supprimees = []
    for horodatage, nom in sorted(par_horodatage.items()):
        if horodatage in garder:
            continue
        stockage.supprimer(nom + SUFFIXE_DUMP)
        stockage.supprimer(nom + SUFFIXE_MANIFESTE)
        supprimees.append(nom)
    return supprimees


def restaurer(stockage: Stockage, cible_url: str, nom: str | None = None) -> dict:
    disponibles = sauvegardes_disponibles(stockage)
    if not disponibles:
        raise SauvegardeError("Aucune sauvegarde disponible.")
    nom = nom or disponibles[-1]
    if nom not in disponibles:
        raise SauvegardeError(f"Sauvegarde inconnue : {nom}")
    phrase = _phrase_de_passe()
    with tempfile.TemporaryDirectory() as dossier:
        chiffre = Path(dossier) / (nom + SUFFIXE_DUMP)
        chemin_manifeste = Path(dossier) / (nom + SUFFIXE_MANIFESTE)
        stockage.recuperer(nom + SUFFIXE_DUMP, chiffre)
        stockage.recuperer(nom + SUFFIXE_MANIFESTE, chemin_manifeste)
        manifeste = json.loads(chemin_manifeste.read_text(encoding="utf-8"))
        if _sha256(chiffre) != manifeste["sha256"]:
            raise SauvegardeError("Empreinte SHA-256 invalide : sauvegarde altérée.")
        dump = Path(dossier) / "base.dump"
        _executer(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
                   "--passphrase-file", phrase, "--decrypt", "--output", str(dump),
                   str(chiffre)])
        _executer(["pg_restore", "--no-owner", "--exit-on-error", "--single-transaction",
                   "--dbname", url_libpq(cible_url), str(dump)])
    restauree = releve_base(cible_url)
    ecarts = comparer(manifeste, restauree)
    if ecarts:
        raise SauvegardeError("Restauration incohérente :\n  " + "\n  ".join(ecarts))
    return {"nom": nom, "tables": len(restauree["lignes"]),
            "lignes": sum(restauree["lignes"].values()),
            "revision_alembic": restauree["revision_alembic"]}


def comparer(manifeste: dict, restauree: dict) -> list[str]:
    ecarts = []
    if manifeste["revision_alembic"] != restauree["revision_alembic"]:
        ecarts.append(
            f"révision Alembic {restauree['revision_alembic']} "
            f"au lieu de {manifeste['revision_alembic']}"
        )
    for table, attendu in sorted(manifeste["lignes"].items()):
        obtenu = restauree["lignes"].get(table)
        if obtenu != attendu:
            ecarts.append(f"{table} : {obtenu} lignes au lieu de {attendu}")
    return ecarts


def tester_restauration(database_url: str, stockage: Stockage) -> dict:
    """Test mensuel : restaure la dernière sauvegarde dans une base jetable
    du même serveur, compare au manifeste, puis supprime la base."""
    import psycopg

    serveur = urlparse(url_libpq(database_url))
    jetable = f"urafiki_test_restauration_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    admin = urlunparse(serveur._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as connexion:
        connexion.execute(f'CREATE DATABASE "{jetable}"')
    try:
        return restaurer(stockage, urlunparse(serveur._replace(path=f"/{jetable}")))
    finally:
        with psycopg.connect(admin, autocommit=True) as connexion:
            connexion.execute(f'DROP DATABASE IF EXISTS "{jetable}"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="urafiki_sauvegarde", description=__doc__.splitlines()[0])
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("sauvegarder")
    sous.add_parser("lister")
    restauration = sous.add_parser("restaurer")
    restauration.add_argument("--cible", required=True, help="URL de la base cible (vide)")
    restauration.add_argument("--nom", help="Sauvegarde à restaurer (défaut : la dernière)")
    sous.add_parser("tester-restauration")
    args = parser.parse_args(argv)

    try:
        destination = os.environ["SAUVEGARDE_DESTINATION"]
    except KeyError:
        print("SAUVEGARDE_DESTINATION non défini.", file=sys.stderr)
        return 2
    stockage = ouvrir_stockage(destination)
    try:
        if args.commande == "sauvegarder":
            resultat = sauvegarder(os.environ["SAUVEGARDE_DATABASE_URL"], stockage)
            print(f"Sauvegarde {resultat.nom} envoyée et vérifiée.")
            for nom in resultat.supprimees:
                print(f"Rétention : {nom} supprimée.")
        elif args.commande == "lister":
            for nom in sauvegardes_disponibles(stockage):
                print(nom)
        elif args.commande == "restaurer":
            print(json.dumps(restaurer(stockage, args.cible, args.nom), indent=2))
        else:
            rapport = tester_restauration(os.environ["SAUVEGARDE_DATABASE_URL"], stockage)
            print("Test de restauration RÉUSSI :", json.dumps(rapport))
    except SauvegardeError as error:
        print(f"ÉCHEC : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
