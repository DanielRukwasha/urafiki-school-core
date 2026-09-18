# Gouvernance des données — Urafiki opère, l'école possède

## Règle opposable

**Urafiki opère l'infrastructure de la plateforme School Core ; Urafiki
n'est jamais propriétaire des données d'une école cliente.** Chaque école
("tenant") reste seule propriétaire des données qu'elle saisit : élèves,
notes, dossiers, configuration. Cette règle est opposable — elle engage
Urafiki contractuellement envers chaque établissement, pas seulement
techniquement.

Trois conséquences concrètes, chacune adossée à un mécanisme technique
réel documenté dans ARCHITECTURE_MULTITENANT.md, pas seulement à une
promesse :

### 1. Urafiki n'accède aux données d'une école qu'à sa demande explicite, et de façon journalisée

- Le rôle `super_admin` (`app/models/platform.py::SuperAdmin`) est
  structurellement distinct des comptes `DIRECTION`/`ENSEIGNANT`/
  `SECRETARIAT` d'une école — il n'appartient à aucun tenant
  (`ecole_id` n'existe pas sur ce modèle).
- Tout accès d'un super-admin aux données d'un tenant doit être
  journalisé dans `TenantAccessAuditLog` (`event_type=
  SUPER_ADMIN_ACCESS`), avec un motif (`reason`) obligatoire, non vide, et
  rattaché à l'école concernée — l'entrée est visible dans le journal
  d'audit de **cette école**, pas dans un journal Urafiki séparé auquel
  l'école n'aurait pas accès.
- **État d'implémentation** : le modèle de données et la contrainte
  (`reason` obligatoire) existent. L'application effective de cette règle
  — c'est-à-dire une API super-admin qui *force* l'écriture d'une entrée
  d'audit avant toute lecture cross-tenant, plutôt que de compter sur la
  discipline de qui écrit le code de la console — reste à construire (voir
  l'issue de suivi « Console de super-administration »). Ce document
  décrit la règle que cette API devra respecter, pas encore une garantie
  automatique de bout en bout.

### 2. Toute école peut repartir avec l'intégralité de ses données

- `flask tenant export` (voir TENANT_ONBOARDING.md) produit un export
  complet et exploitable — JSON, une table par fichier, aucun format
  propriétaire — de toutes les données d'un tenant, généré automatiquement
  à partir de chaque modèle `TenantScopedModel` sans liste à maintenir à
  la main.
- Ce n'est pas seulement une exigence éthique : c'est un argument
  commercial. Une école qui peut vérifier qu'elle peut partir à tout
  moment avec ses données intactes a moins de raisons de ne pas essayer
  la plateforme.

### 3. Aucune école ne peut jamais interroger directement les données d'une autre

- Ce n'est pas une politique — c'est une propriété du schéma
  (`TenantScopedModel`, isolation automatique par `ecole_id`) et de la
  base (PostgreSQL Row Level Security), documentées et testées dans
  `tests/integration/test_tenant_isolation.py`. Ce test suite est
  bloquant en CI.
- Un futur échange de données entre deux écoles (Phase 3, non implémentée
  — voir ci-dessous) ne contournera jamais cette isolation : il passera
  par un flux explicite, jamais par une requête cross-tenant directe.

## Modèle cible des échanges inter-écoles (Phase 3 — non implémenté)

Préparé dès maintenant (`Student.global_student_uid`, voir
ARCHITECTURE_MULTITENANT.md §6) mais aucun mécanisme d'échange n'existe à
ce stade. Le modèle cible, pour quand il sera construit :

1. **Demande formelle** de l'école destinataire (celle qui veut recevoir
   des données sur un élève, typiquement lors d'un transfert d'élève
   entre deux écoles clientes Urafiki), identifiant précisément l'élève
   visé — via son `global_student_uid`, jamais via un `matricule` interne
   à une autre école, qui n'a aucun sens hors de son tenant d'origine.
2. **Approbation explicite de l'école d'origine** — aucun transfert
   automatique, aucun délai qui vaudrait approbation tacite. L'école
   d'origine voit précisément quelles données seraient transférées avant
   d'approuver.
3. **Transfert daté et journalisé** — l'événement (quoi, quand, approuvé
   par qui, reçu par qui) est conservé dans les journaux d'audit des
   **deux** écoles concernées, pas uniquement chez Urafiki.

Ce que ce modèle exclut explicitement : une école interrogeant à la
demande les données d'une autre sans passer par ce flux ; un accès
« lecture seule » permanent d'une école sur les données d'une autre ; un
transfert initié unilatéralement par Urafiki sans le consentement de
l'école d'origine.

## Ce que ce document n'est pas

Ce n'est pas une politique de confidentialité destinée aux parents ou aux
élèves (un document distinct, hors périmètre de ce dépôt technique), et ce
n'est pas un accord de traitement de données formel avec chaque école
(également hors périmètre ici). C'est la règle interne qui contraint la
conception du logiciel — la raison pour laquelle certaines fonctionnalités
(accès super-admin, échanges inter-écoles) sont délibérément construites
plus lentement, avec journalisation et consentement explicite en premier,
plutôt que la fonctionnalité en premier et la gouvernance ajoutée après
coup.
