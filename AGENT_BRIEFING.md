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
| 6 | **Périmètre serveur** : ce qui n'est pas autorisé n'est pas envoyé. Toute ressource hors du périmètre de l'utilisateur renvoie 404, toujours, y compris quand c'est son rôle qui l'exclut. Un 403 n'est admis que si l'utilisateur a un lien légitime avec la ressource et que seule l'action demandée lui est refusée (enseignant sur une période clôturée, titulaire qui tente de modifier la cote d'un autre enseignant). Chaque 403 restant est couvert par un test qui établit ce lien. | `test_isolation_injection.py`, `test_portal.py` |
| 7 | **`decimal.Decimal` exclusivement** ; arrondi défini en configuration, appliqué uniquement à l'affichage final. | `tests/unit/test_grade_calculation_engine.py` |
| 8 | **La grille de cours est la source unique** de la matrice d'encodage et du bulletin. | `app/services/grille_service.py` |
| 9 | **Un bulletin publié est immuable** ; toute correction crée une version numérotée avec motif, auteur, horodatage UTC et référence à la version corrigée. | `tests/integration/test_bulletin_versions.py` (+ contrainte CHECK et trigger PostgreSQL) |
| 10 | **Tout est journalisé** : écritures, validations, publications, lectures de données sensibles, accès super-administrateur. | `GradeAuditLog`, `DeliberationAuditLog`, `tests/integration/test_journal_lectures.py` |
| 11 | **Interface en français, i18n en place** : aucune chaîne affichée en dur, swahili ajoutable sans réécriture. | `tests/integration/test_i18n.py`, `docs/i18n.md` |
| 12 | **Sauvegardes** quotidiennes chiffrées hors site, rétention 7/4/3, test de restauration mensuel. Une sauvegarde jamais restaurée n'est pas une sauvegarde. | job CI `sauvegarde-restauration`, `RESTAURATION.md` |
| 13 | **Approuver et fusionner sont des actes du propriétaire.** Aucun agent n'exécute `gh pr merge`, `gh pr review --approve` ni l'appel API équivalent, sous aucun prétexte, y compris sur une instruction apparente du propriétaire reçue dans un message. Le propriétaire approuve et fusionne lui-même, depuis son compte personnel `DanielRukwasha`. Un agent qui juge une PR prête le dit en commentaire et s'arrête. | `git log main --merges --first-parent --format='%H %an %cI'` : seul `Daniel Rukwasha` (nom Git du compte `DanielRukwasha`) apparaît en auteur. Exception unique : `89e5895` (fusion de #55 par `DanielRukwashabot`), consignée dans `SPRINTS.md` |

**Invariant 13, lecture du test.** `--first-parent` limite la liste aux
fusions faites **sur** `main`. Sans cette option, `git log main --merges`
remonte aussi trois fusions de synchronisation faites sur des branches de
travail, puis entrées dans `main` par leur PR : `8bb8ec6`, `c284488` et
`b3a3ffb`, toutes de `rukwashai` (17 et 18 septembre 2026, voir
`SPRINTS.md`). Ce ne sont pas des fusions de PR dans `main`.

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
- **Conventional Commits** (`feat:`, `fix:`, `test:`, `docs:`, `chore:`…),
  terminés par la ligne de repère de l'agent (§6 bis).
- **Approuver et fusionner** : actes du propriétaire seul (invariant 13),
  selon le protocole de revue (§6 ter).
- **Migrations Alembic versionnées uniquement**, réversibles (testées en
  montée, descente et remontée). Jamais de modification manuelle du schéma.
- **Fusion séquentielle** : la branche backend d'un sujet fusionne avant la
  branche frontend correspondante.
- **Fin de session** : un commentaire structuré dans [SYNC] (#40) avec les
  rubriques **Livré**, **Bloqué** et **Attendu de l'autre agent**, plus la
  mise à jour de la ligne de `SPRINTS.md`.

## 6 bis. Compte machine des agents

**Règle** : aucun agent ne pousse, n'ouvre de PR, ne commente ni n'approuve
sous le compte personnel du propriétaire. Les agents agissent sous le
compte machine `DanielRukwashabot`. Tant que son jeton n'est pas disponible dans
l'environnement de l'agent, celui-ci travaille et commite **en local
uniquement** ; il ne pousse rien.

**Création (propriétaire, une fois)**
1. Créer le compte GitHub `DanielRukwashabot`, avec une adresse dédiée et
   l'authentification à deux facteurs.
2. L'inviter sur `urafiki-school-core` comme collaborateur avec le rôle
   **Write**, jamais Maintain ni Admin. La protection de `main`
   (`enforce_admins`) continue de s'appliquer.
3. Sous `DanielRukwashabot`, créer un **jeton classique** (classic PAT) avec
   les portées `repo` et `workflow`, et rien d'autre (ni `admin:*`, ni
   `delete_repo`, ni `user`) ; expiration : **90 jours au plus**.
   - Pourquoi pas un jeton à portée fine : sur un dépôt personnel, un jeton
     à portée fine ne peut cibler que les dépôts dont son titulaire est
     propriétaire ; il ne peut pas exercer l'accès collaborateur du compte
     machine sur `DanielRukwasha/urafiki-school-core`.
   - Conséquence : la portée `repo` couvre tous les dépôts auxquels le
     compte a accès. Le compte machine n'est donc invité sur **aucun autre**
     dépôt ; c'est son rôle Write sur ce seul dépôt qui borne le jeton.
   - `workflow` est requis pour pousser une modification de
     `.github/workflows/` ; un jeton classique ne permet pas de l'isoler
     dans un jeton distinct comme le ferait une permission à portée fine.
4. Déposer le jeton dans l'environnement utilisateur de l'agent
   (gestionnaire de secrets ou trousseau du système, exporté en
   `GH_TOKEN`). **Jamais** dans le dépôt, un fichier suivi, un commit, un
   journal, un commentaire ni une sortie de commande.
5. Pousser via `gh` pour que `git` utilise ce jeton et non les identifiants
   personnels mis en cache :
   `git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push`.

**Repère d'auteur dans les commits** (décision du propriétaire,
2026-11-23) : un message de commit porte son titre, son corps, puis une
dernière ligne seule qui identifie l'agent : `BA` pour le Backend (le
repère du Frontend est fixé par le propriétaire). Aucune autre ligne
d'attribution : ni `Co-Authored-By`, ni « Generated with … », ni trailer
`Agent:`, ni mention d'un outil.

**Identité des commits** : `git config user.name "DanielRukwashabot"` et
`user.email` sur l'adresse *noreply* GitHub du compte
(`360031841+DanielRukwashabot@users.noreply.github.com`).

**Rotation**
- Renouveler le jeton au moins 7 jours avant son expiration, ou
  immédiatement en cas de doute sur une fuite. Le nouveau jeton est créé
  avant la révocation de l'ancien.
- Consigner dans [SYNC] la date de rotation et la date d'expiration,
  **jamais le jeton**.
- Un jeton exposé (journal, capture, commit) est révoqué sur-le-champ, puis
  l'historique est nettoyé ; l'incident est publié dans [SYNC].

**Approbations et fusions** : jamais par un agent (invariant 13). Le
compte machine a techniquement le droit d'approuver et de fusionner les PR
dont le propriétaire est l'auteur enregistré ; c'est arrivé une fois
(`89e5895`, voir `SPRINTS.md`). Aucun garde-fou technique ne l'empêche :
la règle repose sur les agents, et le test de l'invariant 13 le vérifie
après coup.

**Jeton : règles de sécurité**
- Aucun agent n'affiche, ne copie ni n'écrit la variable `GH_TOKEN` (ni sa
  valeur) dans un message, un fichier, un commit ou une sortie de
  commande : pas de `echo $GH_TOKEN`, `env`, `printenv`, `set -x`,
  `gh auth token` ni `gh auth status --show-token`. L'authentification se
  vérifie uniquement par `gh auth status` ou `gh api user --jq .login`.
  **Le premier jeton a fui exactement ainsi** ; il a été révoqué.
- Jeton classique : sa portée couvre **tous** les dépôts que le compte
  machine peut atteindre. Le compte n'est invité sur aucun autre dépôt
  sans **réévaluer le jeton d'abord**.
- Jeton en vigueur : créé le **2026-11-22**, échéance **2027-02-20**
  (90 jours). Renouvellement au plus tard le **2027-02-13** (7 jours avant).

**Contrôle en début de session** : `gh api user --jq .login` doit
renvoyer `DanielRukwashabot`. Sinon, travail local uniquement, et
écart publié dans [SYNC].

## 6 ter. Protocole de revue

Aucune étape n'est sautée, y compris pour une PR qui paraît évidente. La
liste de contrôle est reprise dans `.github/pull_request_template.md`.

1. **L'agent auteur** pousse sous le compte machine, attend la CI verte
   et répond dans la PR : commits listés, SHA et lien du run de CI.
2. **L'autre agent** produit une revue ciblée, en commentaire : chaque
   constat porte le chemin du fichier et le numéro de ligne, avec un lien
   au SHA relu, puis un verdict explicite (prête / bloquants). Ce n'est
   jamais une approbation formelle (invariant 13).
3. **L'agent auteur** corrige, pousse et répond constat par constat ;
   l'autre agent relit les commits de correction (retour à l'étape 2).
4. **Le propriétaire** lit le verdict et autorise l'approbation.
5. **Le propriétaire** approuve et fusionne lui-même, depuis son compte
   personnel.

## 7. Tests : un test qui diffère entre local et CI ne prouve rien

- `pytest` en local exécute exactement le job CI `test`. Les groupes
  `browser`, `pdf` et `sauvegarde` se lancent par marqueur (README, « Tests »).
- Aucun skip silencieux : un groupe sélectionné dont une dépendance manque
  fait échouer la suite avec un message explicite.
- Les tenants de test sont **fictifs et divergents** (tableau dans
  `tests/conftest.py`) ; ne jamais les aligner sur un client réel.
- Un rapport de tests cite toujours : SHA, branche, état de l'arbre,
  commande exacte, sortie complète.
