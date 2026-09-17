# Architecture multi-tenant

Urafiki School Core est un produit multi-tenant : une seule base de code, un
seul déploiement, plusieurs écoles ("tenants") isolées par donnée. Institut
Mont Carmel est le premier tenant, pas le modèle du code. Aucun nom
d'établissement n'apparaît dans le code source — uniquement en base, dans
`institutions` et `tenant_configs`.

## Règle absolue

Toute variabilité entre établissements vit dans des tables de
configuration. Une exception métier propre à une école devient une option
configurable que toute autre école peut activer — jamais un
`if ecole.nom == ...`, une branche, un module ou une constante par école.

## 1. Isolation des données

### `ecole_id`, partout

Les 11 tables métier (`academic_years`, `sections`, `school_classes`,
`evaluation_periods`, `courses`, `students`, `enrollments`,
`teacher_assignments`, `users`, `grades`, `grade_audit_logs`) plus
`tenant_configs` et `tenant_access_audit_logs` portent une colonne
`ecole_id` non nulle, indexée, `FOREIGN KEY` vers `institutions.id`.

Toutes les contraintes d'unicité qui étaient globales avant la migration
`9d31d5bff2f2` (matricule élève, email utilisateur, libellé d'année
scolaire, code de section, etc.) ont `ecole_id` en tête de la contrainte
composite. Deux écoles peuvent avoir le même matricule élève, le même
libellé d'année, le même code de section — sans collision.

### `TenantScopedModel` — l'isolation ne dépend pas de la vigilance du développeur

`app/models/tenant_scope.py` définit le mixin `TenantScopedModel`, dont
héritent les 13 modèles ci-dessus. Deux mécanismes automatiques :

1. **Lecture** : un event SQLAlchemy `do_orm_execute` injecte
   `WHERE ecole_id = <tenant courant>` sur **toute** requête ORM
   (SELECT, UPDATE, DELETE) contre un modèle `TenantScopedModel`, via
   `with_loader_criteria`. Aucune route, aucun service n'a besoin d'ajouter
   ce filtre lui-même.
2. **Écriture** : la colonne `ecole_id` a un `default=` Python résolu à
   partir de `g.current_ecole_id` au moment du flush — une ligne créée sans
   préciser `ecole_id` explicitement hérite automatiquement du tenant de la
   requête courante.

**Fail-closed par construction** : si aucun tenant n'est résolu pour la
requête courante (`g.current_ecole_id` absent), le critère injecté est
`false()` — la requête renvoie zéro ligne, jamais toutes les lignes de tous
les tenants.

⚠️ **Piège SQLAlchemy documenté dans le code** (`app/models/tenant_scope.py`,
fonction `_apply_tenant_isolation`) : le critère passé à
`with_loader_criteria` doit capturer `ecole_id` comme une **vraie variable
de closure** (nom libre résolu depuis la portée englobante), jamais comme
argument par défaut (`def f(cls, _id=ecole_id)`) ni via un appel de
fonction imbriqué. Le mécanisme de cache de requêtes compilées de
SQLAlchemy suit les variables de closure au niveau bytecode ; s'il ne peut
pas les suivre, il fige silencieusement la première valeur vue et la
réutilise pour tous les tenants suivants avec la même forme de requête —
un bug de fuite inter-tenants silencieux, pas une erreur bruyante. Le test
de non-régression est `tests/integration/test_tenant_isolation.py::
test_orm_query_cannot_see_other_tenants_rows`.

### Contourner le filtre : `skip_tenant_filter`

Quelques cas légitimes ont besoin d'une requête non filtrée : l'export
d'un tenant (`flask tenant export`), les requêtes cross-tenant d'un
super-admin, les assertions de test qui vérifient un état sans passer par
une requête HTTP. Ils utilisent
`Model.query.execution_options(skip_tenant_filter=True)`. Cette option
doit toujours être combinée à un filtre explicite (`filter_by(ecole_id=...)`)
côté appelant — elle désactive le filet de sécurité automatique, elle ne
remplace pas un filtre réfléchi.

### PostgreSQL Row Level Security — second rideau

La migration `9d31d5bff2f2` active RLS sur les 13 tables tenant-scopées et
crée une policy `tenant_isolation` par table :

```sql
CREATE POLICY tenant_isolation ON <table>
USING (
    current_setting('app.current_ecole_id', true) IS NOT NULL
    AND current_setting('app.current_ecole_id', true) <> ''
    AND ecole_id = current_setting('app.current_ecole_id', true)::integer
);
```

`app/models/tenant_scope.py::sync_rls_tenant_context()` pousse le tenant
courant dans la session PostgreSQL via `set_config('app.current_ecole_id', ...)`
juste après que `g.current_ecole_id` change dans
`app/security/tenant.py::resolve_tenant`. C'est un appel explicite, pas un
event `after_begin` : la requête de résolution du tenant elle-même
s'exécute avant que le tenant soit connu, ce qui figerait une variable de
session vide pour le reste de la transaction si on utilisait `SET LOCAL`
sur begin.

**⚠️ Point d'attention déploiement — RLS ne protège que si le rôle
applicatif ne possède pas les tables.** PostgreSQL n'applique jamais RLS au
rôle propriétaire d'une table, quelle que soit l'activation de RLS. Un
déploiement doit donc créer **deux rôles distincts** :

- un rôle propriétaire (`urafiki_migrator` par exemple), qui exécute les
  migrations Alembic et les commandes `flask tenant create`/`export` —
  RLS ne le concerne pas, et ce sont précisément les seuls contextes
  légitimement cross-tenant ;
- un rôle applicatif non-propriétaire (`urafiki_app`), avec uniquement les
  privilèges `SELECT`/`INSERT`/`UPDATE`/`DELETE`, utilisé par le processus
  web en production — RLS s'applique automatiquement à lui.

Sans ce second rôle, RLS est activé et les policies existent, mais elles
n'ont aucun effet : c'est un gap connu de la CI actuelle (un seul rôle
`urafiki` propriétaire et exécutant à la fois), documenté plutôt que caché.
No-op complet sur SQLite (confort de développement local uniquement).

## 2. Résolution du tenant

`app/security/tenant.py::resolve_tenant` tourne en `before_request` sur
chaque requête :

1. Extrait l'hôte de la requête (`request.host`, port retiré).
2. Hôtes `admin.*` / `console.*` → contexte super-admin
   (`g.is_platform_admin_context = True`), aucun tenant résolu — la
   console super-admin n'a par construction accès à aucune donnée d'école
   sans passer par un mécanisme explicite et journalisé.
3. Sinon, recherche `Institution` dont `domain` **ou** `custom_domain`
   correspond exactement à l'hôte. Absence ou `is_active=False` → 404
   explicite, jamais de tenant par défaut.
4. `g.current_ecole_id = institution.id`, puis `sync_rls_tenant_context()`.
5. Si un utilisateur est authentifié et que `current_user.ecole_id !=
   institution.id` : rejet — déconnexion, `403`, et une entrée
   `TenantAccessAuditLog` (`event_type=CROSS_TENANT_SESSION_REJECTED`)
   journalisée sur le tenant **résolu** (celui présenté dans l'URL, pas
   celui de la session).

`ecole_id` n'est **jamais** accepté depuis un paramètre d'URL, un champ de
formulaire, un en-tête ou un cookie modifiable par le client — il est
systématiquement déduit du domaine puis recroisé avec le compte
authentifié.

Point d'implémentation à connaître : le `user_loader` Flask-Login
(`app/__init__.py::load_user`) charge l'utilisateur avec
`skip_tenant_filter=True` **volontairement** — sinon, un utilisateur de
l'école B chargé pendant la résolution du tenant A serait silencieusement
filtré à `None` par `TenantScopedModel`, et la requête ressemblerait à une
simple déconnexion au lieu de déclencher le rejet audité de l'étape 5.

## 3. Configuration comme produit

- `app/models/tenant_config.py::TenantConfig` — une ligne par école
  (contrainte unique sur `ecole_id`) : barème d'arrondi
  (`percentage_decimal_places`), mentions, cours éliminatoires, échecs
  tolérés, en-tête/mentions légales/signatures/logo/couleur de bulletin,
  feature flags (`JSON`), et `calculation_strategy_key`.
- `app/models/platform.py::CalculationStrategy` — catalogue partagé des
  règles de calcul nommées. Une règle réellement spécifique à une école
  s'enregistre ici sous une clé stable ; le catalogue s'enrichit, il ne se
  fragmente jamais par école.
- `app/services/calculation_strategies.py` — registre côté code
  (`STRATEGY_REGISTRY`) faisant correspondre chaque clé à son
  implémentation. Aujourd'hui : `STANDARD` → `grade_calculation_engine`
  (le pipeline livré en P2, inchangé).
- `app/services/tenant_calculation.py::resolve_tenant_calculation(ecole_id)`
  — point d'entrée obligatoire avant tout calcul. Lève
  `IncompleteTenantConfigError` explicitement si `TenantConfig` est
  absent, si `calculation_strategy_key` ne correspond à aucune
  implémentation enregistrée, ou si `percentage_decimal_places` est nul.
  **Aucune valeur par défaut silencieuse.**
- `app/services/grade_calculation_engine.py` reste pur et
  framework-agnostic (aucune dépendance DB/HTTP) — seul
  `quantize_percentage` accepte désormais un `decimal_places` explicite
  (défaut `2`, jamais deviné).

## 4. Console de super-administration

- `app/models/platform.py::SuperAdmin` — table distincte de `users`,
  **jamais** `TenantScopedModel`, hors périmètre d'un tenant. Ne peut pas
  être créée depuis la console d'une école.
- `app/models/platform.py::TenantAccessAuditLog` — journal immuable,
  tenant-scopé par l'école **accédée** (pas par l'acteur), avec
  `event_type` (`SUPER_ADMIN_ACCESS` ou `CROSS_TENANT_SESSION_REJECTED`),
  `reason` obligatoire, et l'acteur (`actor_super_admin_id` ou
  `actor_user_id`).
- **État actuel** : le modèle de données et le principe de journalisation
  sont en place ; l'API HTTP de gestion des tenants (créer/suspendre/
  réactiver un accès sans toucher la base) **n'est pas encore
  implémentée** — seule la voie CLI (`flask tenant create`/`export`, ci-
  dessous) existe à ce stade. Voir l'issue de suivi du jalon Multi-Tenant.

## 5. Provisioning et réversibilité

- `flask tenant create` (`app/cli.py`, `app/services/tenant_provisioning.py
  ::provision_tenant`) — crée en une commande : l'`Institution`, sa
  `TenantConfig` par défaut (stratégie `STANDARD`), une `AcademicYear`, et
  un compte DIRECTION avec mot de passe à usage unique affiché une seule
  fois. Intégrer une nouvelle école ne demande aucune intervention
  développeur.
- `flask tenant export` (`export_tenant`) — parcourt automatiquement
  **toutes** les sous-classes de `TenantScopedModel` (aucune liste
  maintenue à la main : un nouveau modèle tenant-scopé est inclus
  automatiquement) et écrit un fichier JSON par table dans le répertoire
  donné.
- `scripts/seed_dev_data.py` passe désormais par `provision_tenant()` —
  il n'existe plus deux chemins divergents pour créer une école.

## 6. Préparation Phase 3 — échanges inter-écoles

- `Student.global_student_uid` (UUID, unique globalement, généré à la
  création) existe dès maintenant, distinct du `matricule` (unique par
  école). Il n'est utilisé nulle part pour résoudre un tenant et n'est
  exposé dans aucune URL.
- Rien du mécanisme d'échange lui-même n'est implémenté. Le modèle cible
  est documenté dans GOUVERNANCE.md : demande formelle de l'école
  destinataire, approbation explicite de l'école d'origine, transfert
  daté et journalisé. Aucune école ne peut interroger directement les
  données d'une autre — c'est structurellement impossible tant que
  `TenantScopedModel` et RLS tiennent, et le futur mécanisme d'échange
  devra passer par un flux explicite, jamais par une requête cross-tenant
  directe.

## Signature du contexte tenant exposé aux gabarits (pour l'agent Frontend)

Au moment où un gabarit Jinja2 est rendu, l'objet `Institution` du tenant
résolu est chargeable via :

```python
from app.models.institution import Institution
from flask import g
institution = Institution.query.get(g.current_ecole_id)  # jamais tenant-scopé, donc query directe
```

Champs utiles pour l'habillage (nom, logo, langue, en-tête de bulletin) :

| Source | Champ | Usage |
|---|---|---|
| `Institution` | `name`, `short_code` | identité de l'école |
| `Institution` | `locale` | langue de l'interface |
| `TenantConfig` (1 ligne, `ecole_id` unique) | `logo_url`, `primary_color` | identité visuelle |
| `TenantConfig` | `report_header`, `report_legal_mentions`, `report_signatures` | gabarits WeasyPrint |
| `TenantConfig` | `mentions`, `eliminatory_course_codes`, `max_allowed_failures` | affichage résultats/bulletins |
| `TenantConfig` | `feature_flags` (dict) | activer/désactiver un module par école |

Une fonction/processor de contexte Flask exposant directement
`g.current_ecole_id`, l'`Institution` et le `TenantConfig` résolus aux
templates (sans requête manuelle dans chaque vue) est **recommandée mais
pas encore implémentée** côté backend — l'agent Frontend est libre de
l'ajouter (`app/__init__.py::_register_extensions` ou un
`context_processor` dédié) tant qu'elle respecte le même filtrage
automatique (`TenantConfig` étant `TenantScopedModel`, une requête
`TenantConfig.query.first()` dans le contexte d'une requête déjà résolue
retourne naturellement la bonne ligne).
