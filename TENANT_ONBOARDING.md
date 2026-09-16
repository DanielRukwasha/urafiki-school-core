# Intégrer une nouvelle école

Cette procédure ne demande aucune intervention en base de données et
aucune modification de code. Si l'intégration d'une école a besoin de l'un
ou l'autre, c'est un bug — voir ARCHITECTURE_MULTITENANT.md, règle
absolue.

## Prérequis

- Un sous-domaine réservé pour l'école (`<ecole>.urafiki.org`) ou un
  domaine personnalisé déjà pointé vers l'infrastructure Urafiki.
- Les informations de la première année scolaire de l'école (libellé,
  dates de début/fin) et l'identité de la personne DIRECTION initiale
  (nom, prénom, email).

## 1. Provisionner le tenant

```bash
flask tenant create \
  --name "Institut Exemple" \
  --short-code IEX \
  --domain iex.urafiki.org \
  --direction-email direction@iex.example \
  --direction-first-name Prénom \
  --direction-last-name Nom \
  --academic-year-label "2026-2027" \
  --academic-year-start 2026-09-01 \
  --academic-year-end 2027-06-30 \
  --timezone "Africa/Lubumbashi" \
  --locale fr
```

La commande affiche un mot de passe à usage unique pour le compte
DIRECTION. **Il n'est jamais stocké en clair et n'est affiché qu'une seule
fois** — transmettez-le à l'école par un canal sécurisé (jamais par ce
log, jamais par email en clair). Si vous le perdez, réinitialisez le mot
de passe du compte DIRECTION par les moyens habituels (pas par cette
commande).

Ce que la commande crée, automatiquement, en une seule transaction :

- L'`Institution` (le tenant), avec son domaine de résolution.
- Sa `TenantConfig` par défaut (stratégie de calcul `STANDARD`, arrondi à
  2 décimales, aucune mention/cours éliminatoire configuré — l'école les
  ajoutera elle-même).
- La première `AcademicYear`, marquée courante.
- Le compte DIRECTION initial.

## 2. Pointer le domaine

Si `--domain` est un sous-domaine `*.urafiki.org`, le DNS wildcard existant
suffit — rien à faire. Pour un domaine personnalisé, configurez le CNAME
côté client puis renseignez-le comme `custom_domain` de l'`Institution`
(actuellement via `flask shell` — une commande CLI dédiée est un ajout
naturel, non encore fait, si ce cas devient fréquent).

## 3. Vérifier

```bash
curl -I https://iex.urafiki.org/auth/login
```

Doit répondre `200`. Connectez-vous avec le compte DIRECTION et le mot de
passe à usage unique — le mot de passe doit être changé dès la première
connexion (mécanisme de changement de mot de passe forcé : à vérifier
côté Frontend, non couvert par ce document backend).

## 4. L'école configure le reste elle-même

Une fois connectée, DIRECTION configure sections, classes, cours,
enseignants, périodes d'évaluation, seuils de passage — aucune de ces
étapes ne nécessite d'intervention Urafiki. La configuration avancée
(mentions, cours éliminatoires, échecs tolérés, identité visuelle du
bulletin) vit dans `TenantConfig` ; son édition via l'interface
d'administration est un travail Frontend en cours (voir les issues
Design-System-Base / WeasyPrint-Templates du dépôt).

## Exporter les données d'une école (réversibilité)

```bash
flask tenant export --domain iex.urafiki.org --output-dir ./export-iex
```

Écrit un fichier JSON par table (`students.json`, `grades.json`, …) dans
le répertoire donné — un export intégral et exploitable, pas un dump
binaire propriétaire. Urafiki opère l'infrastructure mais ne retient
jamais une école : voir GOUVERNANCE.md.

## Suspendre / réactiver un accès

Pas encore exposé en CLI ni en API à ce stade (`Institution.is_active`
existe déjà en base et est le champ que ces commandes manipuleront — voir
l'issue de suivi « Console de super-administration » du jalon
Multi-Tenant). En attendant, un accès administrateur direct à la base
reste le seul chemin, ce qui est précisément ce que cette section devra
éliminer.
