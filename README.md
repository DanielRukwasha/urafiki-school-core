# Urafiki School Core

Backend générique et réutilisable pour la plateforme de gestion scolaire **Urafiki** : structure pédagogique, notation, délibérations. Conçu pour être **déployé en une instance distincte par école cliente** (sa propre base de données, sa propre installation) — le même code sert au premier déploiement (**Institut Mont Carmel**) et à tous les suivants, sans réécriture. Aucune donnée spécifique à une école (nom, barème, coefficient, seuil de passage) n'est codée en dur : tout vient de la base, configuré/seedé par déploiement.

## Sommaire

- [Architecture](#architecture)
- [Modèle de données](#modèle-de-données)
- [Moteur de quotation](#moteur-de-quotation)
- [Sécurité](#sécurité)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Variables d'environnement](#variables-denvironnement)
- [Tests](#tests)
- [Feuille de route](#feuille-de-route)

## Architecture

Application Factory Flask, découpée en blueprints, avec une couche `services/` pure (sans dépendance HTTP/DB) pour toute la logique métier critique.

```
app/
├── __init__.py                 # create_app() — Application Factory
├── config.py                   # Dev / Test / Prod (lu depuis l'environnement)
├── extensions.py                # db, migrate, login_manager, bcrypt, csrf
├── models/                      # SQLAlchemy — un module par domaine
├── security/rbac.py             # roles_required(*roles) — RBAC serveur
├── services/
│   ├── grade_calculation_engine.py   # pur, Decimal, testable sans DB
│   └── audit_service.py              # écrit GradeAuditLog à chaque mutation
└── blueprints/
    ├── auth/                     # login/logout (Flask-Login + bcrypt)
    └── admin/                    # routes démo protégées par rôle
```

## Modèle de données

Toutes les tables métier portent `created_at`/`updated_at` (UTC) et `archived_at` (soft delete), sauf `grade_audit_logs`, immuable.

```mermaid
erDiagram
    Institution ||--o{ AcademicYear : configure
    AcademicYear ||--o{ SchoolClass : contient
    AcademicYear ||--o{ EvaluationPeriod : decoupe
    AcademicYear ||--o{ DeliberationPolicy : definit
    Section ||--o{ SchoolClass : regroupe
    SchoolClass ||--o{ Course : propose
    SchoolClass ||--o{ Enrollment : accueille
    Student ||--o{ Enrollment : possede
    User ||--o{ TeacherAssignment : est_assigne
    Course ||--o{ TeacherAssignment : assigne_a
    Enrollment ||--o{ Grade : recoit
    Course ||--o{ Grade : concerne
    EvaluationPeriod ||--o{ Grade : pour
    User ||--o{ Grade : saisit
    Grade ||--o{ GradeAuditLog : trace
    User ||--o{ GradeAuditLog : effectue
```

Contraintes structurantes :

- `grades` : **UNIQUE(enrollment_id, course_id, period_id)** — une seule note par élève, par cours, par période, garantie en base.
- `courses.max_score` et `courses.coefficient` : `CheckConstraint > 0`.
- `evaluation_periods.weight_percent` et `deliberation_policies.passing_threshold_percent` : configurables en base, jamais en dur dans le code.
- `grade_audit_logs` : conserve `grade_id` (nullable, `ON DELETE SET NULL`) **et** des colonnes de snapshot (`enrollment_id`, `course_id`, `period_id`) pour survivre à la suppression d'une note.

## Moteur de quotation

`app/services/grade_calculation_engine.py` — fonctions pures, arithmétique `decimal.Decimal` exclusivement (jamais de `float`).

Pipeline : `compute_period_total` → `compute_annual_total` → `rank_students` → `decide_promotion`.

Règles métier confirmées :

- **Note manquante** : exclue du numérateur *et* du dénominateur pondéré — un élève est quoté sur son travail réellement fourni, jusqu'à preuve du contraire.
- **Ex æquo** : rang standard de compétition (1-2-2-4).
- **Données insuffisantes** : un classement ou une décision de passage sans aucune note renvoie `None` / `UNDETERMINED`, jamais une décision silencieuse.
- **Arrondi** : `ROUND_HALF_UP` à 2 décimales, uniquement au moment de la présentation du résultat final.

## Sécurité

- Authentification par session via **Flask-Login** ; mots de passe hachés avec **bcrypt** (`BCRYPT_LOG_ROUNDS` configurable).
- **RBAC serveur** (`app/security/rbac.py`) : décorateur `@roles_required(...)` sur chaque route métier — trois rôles structurels : `DIRECTION`, `ENSEIGNANT`, `SECRETARIAT`.
- **CSRF** via Flask-WTF, activé globalement.
- Toutes les requêtes passent par l'ORM SQLAlchemy — aucun SQL brut.
- Chaque création/modification/suppression de note est tracée dans `GradeAuditLog` (`user_id`, `old_value`, `new_value`, `ip_address`, horodatage UTC).

## Prérequis

- Python **3.11+**
- PostgreSQL **14+** pour un déploiement réel (les tests locaux tournent sur SQLite, portable)
- `pip`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env             # puis renseigner les valeurs de CE déploiement
export FLASK_APP=wsgi.py         # Windows : set FLASK_APP=wsgi.py

flask db upgrade                 # applique les migrations Alembic
flask run
```

Jeu de données de démonstration (Institut Mont Carmel) :

```bash
flask shell
>>> from scripts.seed_dev_data import seed; seed()
```

## Variables d'environnement

| Variable | Description | Exemple |
|---|---|---|
| `FLASK_ENV` | `development` / `testing` / `production` | `development` |
| `SECRET_KEY` | Clé de session Flask | valeur aléatoire longue |
| `DATABASE_URL` | Connexion PostgreSQL de ce déploiement | `postgresql+psycopg://user:pass@host:5432/db` |
| `BCRYPT_LOG_ROUNDS` | Coût du hachage bcrypt | `12` |
| `SESSION_COOKIE_SECURE` | Cookie de session en HTTPS uniquement | `true` en production |

## Tests

```bash
pytest --cov=app --cov-report=term-missing
ruff check .
```

La CI (`.github/workflows/ci.yml`) exécute la suite contre un vrai service PostgreSQL et fait échouer le build sur toute régression de lint ou de test.

## Feuille de route

- **P1-Socle** : Application Factory, modèle relationnel complet, authentification, RBAC, CI/CD. ✅
- **P2-Quotation-Engine** : moteur de calcul déterministe (moyennes, classement, délibération), audit des notes. ✅
- **P3+** (backlog) : routes CRUD complètes de saisie des notes, tableaux de bord par rôle, bulletins, provisioning automatisé d'une nouvelle instance école.

Suivi détaillé via les [Issues](../../issues) et [Milestones](../../milestones) GitHub.


## Portail frontend

Le portail enseignant et direction est accessible sur /portal/ apres connexion.
Il comprend les attributions, la saisie avec brouillons locaux et synchronisation HTMX,
les resultats de periode et les bulletins/palmares A4.
Voir [architecture, fonctionnement et verification](docs/frontend.md).
Pour les PDF : pip install -r requirements-pdf.txt et installer les bibliotheques natives Pango.
Pour les tests navigateur : pip install -r requirements-browser.txt, puis
python -m playwright install chromium et pytest tests/browser -q.
