# Sauvegardes et restauration

Invariant 12 : sauvegardes quotidiennes chiffrées hors site, rétention de
7 quotidiennes, 4 hebdomadaires et 3 mensuelles, test de restauration
mensuel. **Une sauvegarde jamais restaurée n'est pas une sauvegarde.**

Outil : `ops/sauvegarde/urafiki_sauvegarde.py` (Python standard, `pg_dump`,
`pg_restore`, `gpg`, `boto3` pour le stockage S3).

## État au 2026-10-03

| Élément | État |
|---|---|
| Mécanisme de sauvegarde, chiffrement, manifeste, rétention 7/4/3 | Livré |
| Procédure de restauration avec contrôle d'intégrité | Livrée, **testée en CI** sur PostgreSQL 16 à chaque push (job `sauvegarde-restauration`) |
| Planification (cron quotidien et test mensuel) | Livrée : `ops/sauvegarde/urafiki-sauvegarde.cron` |
| **Stockage objet hors site** | **NON APPROVISIONNÉ** : aucun seau ni identifiant n'existe encore. Blocage signalé dans [SYNC]. |
| Mise en service sur le serveur de production | À faire après approvisionnement du stockage |

Tant que le stockage hors site n'est pas approvisionné et que la première
restauration réelle n'a pas été faite selon la section 4, **la production
n'a pas de sauvegarde**.

## 1. Ce que fait une sauvegarde

1. Relevé de la révision Alembic et du nombre de lignes de chaque table.
2. `pg_dump --format=custom`.
3. Chiffrement GPG symétrique AES-256. La phrase de passe suffit à
   déchiffrer, sans ce code (section 5).
4. Envoi vers le stockage hors site de deux objets :
   `urafiki-AAAAMMJJTHHMMSSZ.dump.gpg` et son `.manifest.json`, qui contient
   l'empreinte SHA-256, la taille, la révision et les nombres de lignes.
5. Relecture de l'objet envoyé (taille et SHA-256). Seulement si elle
   réussit, application de la rétention. Une sauvegarde non vérifiée ne
   déclenche jamais de suppression.

Rétention : on garde la plus récente de chacun des 7 derniers jours, des 4
dernières semaines ISO et des 3 derniers mois, soit entre 7 et 14 sauvegardes.

## 2. Mise en service (une fois le stockage approvisionné)

1. **Stockage** : créer un seau S3 ou compatible S3 (Cloudflare R2
   recommandé, Cloudflare étant déjà en frontal), dans un compte distinct du
   serveur applicatif. Créer une clé d'accès limitée à ce seau. Si le
   fournisseur le permet, activer le verrouillage d'objet ou le
   versionnage, pour qu'une compromission du serveur ne puisse pas effacer
   l'historique.
2. **Rôle PostgreSQL de sauvegarde** : propriétaire des tables, ou rôle doté
   de `BYPASSRLS`. Avec un rôle soumis à la Row Level Security, `pg_dump`
   refuse de lire les tables, ce qui est voulu.
3. **Phrase de passe** :
   ```bash
   openssl rand -base64 48 | sudo tee /etc/urafiki/sauvegarde.passphrase
   sudo chmod 600 /etc/urafiki/sauvegarde.passphrase
   ```
   **Copier immédiatement cette phrase dans le coffre de l'exploitation,
   hors du serveur.** Si le serveur est perdu avec elle, toutes les
   sauvegardes sont illisibles.
4. **Configuration** : copier `ops/sauvegarde/sauvegarde.env.exemple` vers
   `/etc/urafiki/sauvegarde.env` (`chmod 600`) et le compléter.
5. **Dépendances** : `sudo apt-get install postgresql-client-16 gnupg`,
   puis `pip install -r requirements-ops.txt` dans le virtualenv.
6. **Première sauvegarde manuelle** :
   ```bash
   cd /srv/urafiki && set -a && . /etc/urafiki/sauvegarde.env && set +a
   .venv/bin/python -m ops.sauvegarde.urafiki_sauvegarde sauvegarder
   ```
7. **Première restauration réelle** : section 4. Elle est obligatoire avant
   de considérer les sauvegardes comme opérationnelles.
8. **Planification** :
   ```bash
   sudo cp ops/sauvegarde/urafiki-sauvegarde.cron /etc/cron.d/urafiki-sauvegarde
   sudo mkdir -p /var/log/urafiki && sudo chown urafiki /var/log/urafiki
   ```
   Vérifier que `MAILTO` désigne une boîte réellement lue.

## 3. Restaurer après un incident

Toujours restaurer dans une base **vide**, jamais par-dessus la production.

```bash
cd /srv/urafiki && set -a && . /etc/urafiki/sauvegarde.env && set +a

# 1. Choisir la sauvegarde (par défaut : la plus récente).
.venv/bin/python -m ops.sauvegarde.urafiki_sauvegarde lister

# 2. Créer une base vide.
createdb -h 127.0.0.1 -U postgres urafiki_restauree

# 3. Restaurer. La commande vérifie l'empreinte SHA-256, déchiffre, restaure,
#    puis compare la révision Alembic et le nombre de lignes de chaque table
#    avec le manifeste. Tout écart fait échouer la commande.
.venv/bin/python -m ops.sauvegarde.urafiki_sauvegarde restaurer \
  --cible postgresql://postgres@127.0.0.1:5432/urafiki_restauree \
  [--nom urafiki-20261003T023000Z]
```

4. Contrôles fonctionnels sur la base restaurée : démarrer une instance de
   l'application pointant sur `urafiki_restauree`, se connecter sur un tenant
   et consulter un bulletin publié connu. Comparer sa version et ses valeurs
   avec la dernière version connue.
5. Basculer : arrêter Gunicorn, renommer les bases
   (`ALTER DATABASE urafiki RENAME TO urafiki_incident_AAAAMMJJ;` puis
   `ALTER DATABASE urafiki_restauree RENAME TO urafiki;`), redémarrer.
   **Conserver la base sinistrée** pour l'analyse ; ne pas la supprimer.
6. Réappliquer les permissions du rôle applicatif, qui ne doit être ni
   propriétaire ni BYPASSRLS (voir ARCHITECTURE_MULTITENANT.md), puis
   vérifier que la RLS s'applique.
7. Consigner l'incident dans [SYNC] : sauvegarde utilisée, perte de données
   (intervalle entre la sauvegarde et l'incident), contrôles faits.

## 4. Test de restauration mensuel

Automatique, le 1er de chaque mois (cron). `tester-restauration` restaure la
dernière sauvegarde dans une base jetable du même serveur, compare au
manifeste, puis supprime la base. Le rôle doit avoir le droit `CREATEDB`.

Manuellement :
```bash
.venv/bin/python -m ops.sauvegarde.urafiki_sauvegarde tester-restauration
```

Chaque test, automatique ou manuel, est consigné dans le tableau ci-dessous.
Un mois sans ligne est un mois sans sauvegarde prouvée.

| Date | Sauvegarde restaurée | Tables | Lignes | Résultat | Opérateur |
|---|---|---|---|---|---|
| — | — | — | — | Aucun test en production : stockage non approvisionné | — |

## 5. Déchiffrer sans l'outil (dernier recours)

```bash
gpg --batch --pinentry-mode loopback --passphrase-file /chemin/phrase \
    --decrypt --output base.dump urafiki-AAAAMMJJTHHMMSSZ.dump.gpg
sha256sum urafiki-AAAAMMJJTHHMMSSZ.dump.gpg   # comparer au manifeste
pg_restore --no-owner --exit-on-error --single-transaction \
    --dbname postgresql://postgres@127.0.0.1/urafiki_restauree base.dump
```

## 6. Preuve continue

Le job CI `sauvegarde-restauration` exécute à chaque push, sur PostgreSQL 16
réel, `tests/sauvegarde/test_cycle_restauration.py` :

- une base migrée et peuplée est sauvegardée, chiffrée et stockée ;
- l'objet stocké n'est pas lisible en clair ;
- la restauration dans une base vide reproduit la révision Alembic et le
  nombre de lignes de chaque table ;
- le test mensuel fonctionne avec une base jetable ;
- un objet altéré d'un seul octet est refusé (SHA-256) ;
- une mauvaise phrase de passe ne restaure rien.

Ce job prouve le **mécanisme**. Il ne remplace pas la restauration réelle
mensuelle de la production (section 4).
