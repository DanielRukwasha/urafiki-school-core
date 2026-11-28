# Périmètres et permissions contextuelles

## Règle absolue

Toute vérification d'autorisation contextuelle (« cet utilisateur a-t-il
le droit sur CETTE classe / CETTE ligne / CETTE période ») passe par
`app.services.authorization_service` — jamais une comparaison
`current_user.role == ...` dans une route. `@roles_required(...)` reste
utilisé, mais uniquement pour la porte grossière « ce rôle a-t-il accès
à cet endpoint, en général » (ex. `/portal/audit` est DIRECTION
uniquement) ; jamais pour trancher l'accès à une ressource précise.

## Titulariat : un périmètre par classe, jamais un rôle global

Un compte enseignant ne porte aucune information de titulariat.
`SchoolClass.titulaire_id` est une lecture rapide dénormalisée du
titulaire *courant* ; la source de vérité est `TitulaireHistorique`
(historisée, `date_fin=None` = ligne courante). Un même enseignant peut
être titulaire d'une classe et simple attributaire de cours dans une
autre — rien ne « voyage » avec le compte.

`DelegationTitulariat` accorde temporairement les droits du titulaire à
un autre enseignant (remplacement, congé), sur une fenêtre de dates
bornée, sans jamais toucher `TitulaireHistorique` ni
`SchoolClass.titulaire_id` — le titulaire de référence ne change pas,
seul l'exercice effectif des droits est délégué le temps de la fenêtre.
`titulaire_effectif(school_class, at=None)` résout l'un ou l'autre :

- **sans `at`** (le présent) : une délégation ACTIVE couvrant maintenant
  prime sur `SchoolClass.titulaire` ;
- **avec une date `at`** : la réponse est lue dans l'historique, jamais
  dans le présent. La ligne de `TitulaireHistorique` qui couvre `at`
  (intervalle semi-ouvert `date_debut <= at < date_fin` : le jour du
  changement appartient au nouveau titulaire), puis une délégation en
  vigueur à `at` qui prime. Une délégation expirée depuis compte pour sa
  fenêtre ; une délégation révoquée ne compte que si elle a été révoquée
  après `at`. Une date qu'aucune ligne d'historique ne couvre renvoie
  `None`, jamais le titulaire actuel (#84).

La migration `14efd3eb110e` n'a pas reconstitué d'historique pour les
titulaires affectés avant elle : pour ces classes, une date antérieure à
la première ligne d'historique renvoie `None`.

## Droits du titulaire (rappel du périmètre exact)

- Lecture seule de **toutes** les matières de sa classe, y compris
  celles qu'il n'enseigne pas lui-même.
- Jamais le droit d'écrire une cote qu'il n'a pas lui-même en charge
  (`TeacherAssignment` sur la ligne précise) — voir plus bas, ce droit
  n'est **pas** élargi par la titularité, intentionnellement : un droit
  global élevé serait une faille de sécurité, pas une simplification.
- Seul rôle habilité à soumettre sa classe pour consolidation
  (`peut_soumettre_classe`) — jamais Direction directement, jamais un
  attributaire ordinaire.

## Contrat du portail enseignant

- Le titulaire effectif consulte les cotes et l'état d'avancement de sa classe. Chaque cote hors de ses attributions reste en lecture seule.
- Le POST `consolidation/submit` vérifie le titulariat pour la classe. Le service enregistre l'état soumis, l'horodatage et l'événement d'audit. Les étapes `consolidate`, `validate` et `publish` relèvent de la Direction.
- Le serveur fournit les classes, les actions et les droits d'écriture que l'interface affiche. L'accès à chaque ressource et chaque transition reste vérifié côté serveur.

## Fonctions publiées

```python
# app/services/authorization_service.py
titulaire_effectif(school_class, at=None) -> User | None
est_titulaire_effectif(user, school_class, at=None) -> bool
est_attributaire(user, school_class, ligne) -> bool
    # assignation exacte (enseignant, classe, ligne) — jamais élargie
    # par la titularité, jamais par une assignation sur la même ligne
    # dans une AUTRE classe.

peut_lire_cotes_classe(user, school_class) -> bool
    # Direction, ou titulaire effectif de la classe.
peut_encoder_ligne(user, school_class, ligne, period) -> bool
    # attributaire exact ET période non verrouillée — refusé pour
    # quiconque, titulaire inclus, dès SUBMITTED.
peut_soumettre_classe(user, school_class, period) -> bool
    # titulaire effectif uniquement.
peut_rouvrir_periode(user) -> bool        # Direction uniquement
peut_valider_bulletin(user) -> bool       # Direction uniquement
peut_gerer_grille(user) -> bool           # Direction uniquement

require_lecture_classe(user, school_class) -> None       # lève 404
require_encodage_ligne(user, school_class, ligne, period) -> None  # lève 404
require_soumission_classe(user, school_class, period) -> None      # lève 404
require_direction(user) -> None                          # lève 404

affecter_titulaire(school_class, teacher, *, motif, actor) -> TitulaireHistorique
    # clôt la ligne d'historique ouverte s'il y en a une, en ouvre une
    # nouvelle, met à jour SchoolClass.titulaire_id — jamais deux lignes
    # ouvertes en même temps pour une même classe.
```

## 404, jamais 403, pour un périmètre refusé

Toute ressource hors du périmètre de l'utilisateur renvoie **404**, sans
message — une classe qui existe mais n'est pas la sienne répond exactement
comme une classe qui n'existe pas, pour ne jamais permettre à une requête
de sonder l'existence d'une ressource hors périmètre. Cela vaut pour :

- les routes gérées par `authorization_service` (`require_*`) ;
- `@roles_required` : un rôle jamais admis sur une route reçoit 404,
  comme si la route n'existait pas (`app/security/rbac.py`) ;
- une session d'une école présentée sur le domaine d'une autre école :
  session fermée, événement journalisé, puis 404 sans description
  (`app/security/tenant.py`).

## 403 légitimes

Un 403 n'est admis que si l'utilisateur a un lien légitime avec la
ressource et que seule l'action demandée lui est refusée. Chaque 403
restant figure ici avec le test qui établit ce lien.

| Site | Lien légitime | Test |
|---|---|---|
| `app/blueprints/portal/routes.py:session_check` — compte désactivé (`is_active` faux), requête autre que `POST` | le compte est celui de l'utilisateur ; seule son utilisation est refusée (un `POST` reçoit 401 pour que l'interface conserve les brouillons) | `tests/integration/test_portal.py:test_inactive_account_still_gets_403`, `tests/integration/test_tenant_isolation.py:test_inactive_account_of_another_school_never_gets_the_403` |

**Décision du propriétaire (2026-11-27, #125)** : le 403 du compte
désactivé est conservé et rendu atteignable. Avant #125, il ne l'était
pas : Flask-Login définit `is_authenticated` comme `is_active`, si bien
qu'un compte désactivé n'était jamais « authentifié » et recevait 302
(redirection vers la connexion) ou 401, jamais 403. Le périmètre retenu :

- **portail seulement** (`session_check` du blueprint `portal`) ; `/admin`
  et `/auth` gardent le chemin non authentifié ;
- **école du domaine seulement** : un compte désactivé d'une autre école
  n'est pas reconnu et ne reçoit jamais ce 403 ;
- **connexion inchangée** : `is_authenticated` n'est pas surchargé, et un
  compte désactivé ne passe jamais `login_required`.

## Verrouillage d'écriture et machine à états

L'écriture d'une cote est refusée dès que la période a dépassé l'état
`DRAFT` (`PeriodPublication.status`), y compris pour l'attributaire
exact de la ligne — la soumission par le titulaire ferme l'encodage
côté serveur, pas seulement côté interface. Un appel direct à l'API de
synchronisation après soumission est refusé exactement comme un clic
dans une interface obsolète : le verrou est vérifié en service
(`peut_encoder_ligne`), jamais seulement masqué côté client.

## Ce qui n'est pas encore livré

Les routes pour la réouverture journalisée d'une période par Direction,
la dérogation motivée pour soumission incomplète, et le workflow complet
de `DemandeCorrection` (création / acceptation / refus / traitement) ont
leurs modèles et une partie du service d'autorisation en place, mais pas
encore de routes portail dédiées — prochaine tranche de ce chantier.
