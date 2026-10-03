# Briefing des agents — Plateforme Urafiki

À lire **en entier** au début de chaque session, avant toute ligne de code.
Ce document remplace le re-briefing manuel : si une consigne d'une
conversation le contredit, signaler l'écart dans [SYNC] et faire trancher ;
ne pas trancher seul.

## 0. Reprise de session : l'état réel avant toute parole

Ne jamais se fier à sa mémoire de session. Le dépôt fait foi.

1. `git fetch --all --prune`, puis l'état des branches (fusionnées ou non,
   date du dernier commit), des PR ouvertes et des issues par jalon.
2. Lire `SPRINTS.md` et le dernier commentaire de l'issue **[SYNC] Journal
   de session** (#40).
3. Exécuter les tests du groupe concerné (voir README, section « Tests ») et
   noter : SHA testé, branche, état de l'arbre (`git status --porcelain`),
   commande exacte, sortie complète.
4. Si ce constat contredit ce qui était présumé livré, le publier dans
   [SYNC] **avant** de produire du code.

## 1. Le projet

**Urafiki** : plateforme de gestion scolaire **multi-tenant**, opérée par
Urafiki. Elle comprend un site institutionnel public et un portail de
gestion des cotes et des bulletins. Le premier établissement client est un
tenant parmi d'autres, **jamais le modèle du code**.

**Condition de mise en service** : des bulletins réels d'une période déjà
clôturée seront réencodés et comparés ligne à ligne aux bulletins
officiels. Tant qu'un seul écart subsiste, le système n'est pas prêt. Toute
décision d'implémentation sert cet objectif : reproduire fidèlement le
calcul de l'établissement, de façon vérifiable et traçable.

## 2. Stack imposée, sans substitution

Python 3.11+, Flask avec des blueprints distincts (public, portail),
PostgreSQL 15+, SQLAlchemy et Alembic, Flask-WTF/WTForms, Flask-Login et
bcrypt, Jinja2 en rendu serveur, HTMX et Bootstrap 5, WeasyPrint (PDF),
Flask-Babel (i18n), Gunicorn derrière Nginx, Cloudflare en frontal,
APScheduler ou cron pour les tâches planifiées.

**Sobriété non négociable** : aucun framework front lourd (ni React, ni Vue,
ni build JavaScript). Rendu serveur, interactivité ponctuelle, pages légères
pour des connexions irrégulières.

## 3. Invariants non négociables

Pour chacun : la règle, puis son **test de réfutation** dans le dépôt. Un
invariant sans test qui le réfute est un vœu, pas un invariant.

| # | Règle | Réfutation automatisée |
|---|---|---|
| 1 | **Multi-tenant** : une base de code, un déploiement, des écoles isolées par `ecole_id`. Aucun nom d'établissement réel dans `app/` ni `tests/` (les scripts de démonstration et les migrations de données en sont exemptés). Aucune condition propre à une école, une classe ou un niveau. | `tests/unit/test_aucun_nom_reel.py`, liste dans `.github/noms-etablissements-reels.txt` |
| 2 | **Configuration plutôt que code** : barèmes, maxima, pondérations, poids des périodes, seuils, mentions, libellés, périodes, identité visuelle, modules, langue, tout en base. Une configuration incomplète lève une erreur explicite, jamais une valeur par défaut silencieuse. | `test_incomplete_tenant_config_raises_explicitly`, `GrilleConfigError`, `DeliberationConfigError`, `LangueNonDisponibleError` |
| 3 | **Le bulletin est calculé, jamais saisi** : aucune requête, quel que soit le rôle, n'écrit une valeur de bulletin. | moteur de calcul `app/services/grade_calculation_engine.py` |
| 4 | **Isolation** : `ecole_id` est déduit du sous-domaine et recoupé avec le compte authentifié ; il n'est jamais accepté depuis une URL, un formulaire, un en-tête ou un cookie. | `tests/integration/test_tenant_isolation.py`, `tests/integration/test_isolation_injection.py` |
| 5 | **Le titulaire est un périmètre contextuel**, pas un rôle global. Permissions calculées par classe et par cours. Un titulaire ne modifie jamais une cote encodée par un autre enseignant. | `tests/integration/test_titulaire.py` |
| 6 | **Périmètre serveur** : ce qui n'est pas autorisé n'est pas envoyé. Un accès hors périmètre renvoie 404, jamais 403 (le 403 est réservé au rejet global d'un rôle). | `test_isolation_injection.py`, `test_portal.py` |
| 7 | **`decimal.Decimal` exclusivement** ; arrondi défini en configuration, appliqué uniquement à l'affichage final. | `tests/unit/test_grade_calculation_engine.py` |
| 8 | **La grille de cours est la source unique** de la matrice d'encodage et du bulletin. | `app/services/grille_service.py` |
| 9 | **Un bulletin publié est immuable** ; toute correction crée une version numérotée avec motif, auteur, horodatage UTC et référence à la version corrigée. | `tests/integration/test_bulletin_versions.py` (+ contrainte CHECK et trigger PostgreSQL) |
| 10 | **Tout est journalisé** : écritures, validations, publications, lectures de données sensibles, accès super-administrateur. | `GradeAuditLog`, `DeliberationAuditLog`, `tests/integration/test_journal_lectures.py` |
| 11 | **Interface en français, i18n en place** : aucune chaîne affichée en dur, swahili ajoutable sans réécriture. | `tests/integration/test_i18n.py`, `docs/i18n.md` |
| 12 | **Sauvegardes** quotidiennes chiffrées hors site, rétention 7/4/3, test de restauration mensuel. Une sauvegarde jamais restaurée n'est pas une sauvegarde. | job CI `sauvegarde-restauration`, `RESTAURATION.md` |

## 4. Où vivent les garanties (ne pas les contourner)

- **Isolation** : `TenantScopedModel` (filtre `ecole_id` sur toute requête
  ORM, fermé par défaut), `TenantScopedSession` (même contrôle pour
  `session.get` / `get_or_404`, qui sinon court-circuitent le filtre via la
  carte d'identité), RLS PostgreSQL en seconde couche. `skip_tenant_filter`
  est réservé aux usages explicitement justifiés en commentaire.
- **Toute nouvelle table propre à un tenant** hérite de `TenantScopedModel`,
  et sa migration active la RLS (même politique que `9d31d5bff2f2`).
- **Lectures sensibles** : décorer la fonction qui *produit* la donnée avec
  `journaliser_lecture` (une fois), jamais chaque route.
  `journaliser_acces_super_admin` pour toute fonction de la console
  d'exploitation.
- **Identifiant soumis mais introuvable** (chemin, champ caché, payload) :
  404, jamais une erreur de formulaire qui confirmerait son existence.

## 5. Frontières de responsabilité

| Zone | Propriétaire | Modification par l'autre agent |
|---|---|---|
| `app/models`, `migrations`, `app/services`, `app/security`, `app/i18n.py`, `requirements*.txt`, `app/config.py`, `ops/` | **Backend** | interdite ; ouvrir une issue |
| `app/templates`, `app/static` | **Frontend** | interdite ; ouvrir une issue |
| `app/blueprints/*/routes.py` (routes) | partagé | PR avec **revue croisée** obligatoire |
| `tests/` | partagé | chacun teste son périmètre ; toute modification de `tests/conftest.py` passe en revue croisée |
| Documentation racine | auteur du sujet | PR |

## 6. Discipline Git

- Branches `feat/backend-…` ou `feat/frontend-…` (ou `fix/…`). **Aucun push
  sur `main`**, qui est protégée : PR obligatoire, checks `test`,
  `browser-pdf` et `sauvegarde-restauration` requis, au moins une
  approbation d'un compte autre que l'auteur, approbations obsolètes
  rejetées après un nouveau push, règles appliquées aux administrateurs.
  Les branches fusionnées sont supprimées automatiquement.
- **Conventional Commits** (`feat:`, `fix:`, `test:`, `docs:`, `chore:`…).
- **Migrations Alembic versionnées uniquement**, réversibles (testées en
  montée, descente et remontée). Jamais de modification manuelle du schéma.
- **Fusion séquentielle** : la branche backend d'un sujet fusionne avant la
  branche frontend correspondante.
- **Fin de session** : un commentaire structuré dans [SYNC] (#40) avec les
  rubriques **Livré**, **Bloqué** et **Attendu de l'autre agent**, plus la
  mise à jour de la ligne de `SPRINTS.md`.

## 7. Tests : un test qui diffère entre local et CI ne prouve rien

- `pytest` en local exécute exactement le job CI `test`. Les groupes
  `browser`, `pdf` et `sauvegarde` se lancent par marqueur (README, « Tests »).
- Aucun skip silencieux : un groupe sélectionné dont une dépendance manque
  fait échouer la suite avec un message explicite.
- Les tenants de test sont **fictifs et divergents** (tableau dans
  `tests/conftest.py`) ; ne jamais les aligner sur un client réel.
- Un rapport de tests cite toujours : SHA, branche, état de l'arbre,
  commande exacte, sortie complète.
