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
  dans le présent. La ligne de `TitulaireHistorique` qui couvre `at` est
  résolue d'abord (intervalle semi-ouvert `date_debut <= at < date_fin` :
  le jour du changement appartient au nouveau titulaire) ; ensuite
  seulement, une délégation en vigueur à `at` prime sur ce titulaire.
  Une délégation expirée depuis compte pour sa fenêtre ; une délégation
  révoquée ne compte que si elle a été révoquée strictement après `at` (à l'instant exact de la révocation, elle ne
  s'applique plus). Une date qu'aucune ligne d'historique ne couvre
  renvoie `None` : jamais le titulaire actuel, et jamais un délégataire,
  même si une délégation couvre cette date — une délégation transfère les
  droits d'un titulaire enregistré, et sans ligne d'historique il n'y a
  rien à déléguer (#84).

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
peut_lire_motif_correction(user, school_class, version) -> bool
    # voir « Motifs de correction des bulletins publiés ».
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

## Motifs de correction des bulletins publiés

**Décision du propriétaire (2026-11-28, revue de #126)**. Le motif d'une
correction motivée est lisible selon `peut_lire_motif_correction(user,
school_class, version)`, seule source de la règle ; une route n'en
décide jamais elle-même.

| Qui | Motifs lisibles |
|---|---|
| Direction, titulaire effectif de la classe (au présent) | tous |
| Enseignant attributaire | seulement le motif d'une correction dont le contenu figé, comparé à la version qu'elle corrige, ne change les cotes que d'**une seule ligne**, et que cette ligne est la sienne dans cette classe |
| Tout autre utilisateur, secrétariat compris | aucun |

- Une première publication n'a pas de motif.
- Une correction qui ne se ramène pas à une seule ligne reste au
  périmètre de la classe : changement de structure, de présentation,
  d'élèves, de cotes sur plusieurs lignes, ou de **précision figée des
  pourcentages** (elle vient de la configuration de l'école, pas d'un
  cours). En cas de doute : non. La précision est comparée par la clé
  `precision_pourcentage` et par le nombre de décimales de chaque
  `pourcentage_affiche`, ce qui couvre aussi un contenu figé avant
  l'existence de la clé.
- Une version d'une autre classe : non.

**Intégrité du contenu figé — même contrat pour tous les profils :**

| Contenu figé de la version | Direction, titulaire | Attributaire | Journal |
|---|---|---|---|
| intact | oui | selon la ligne corrigée | — |
| altéré (empreinte rompue, ou contenu sans empreinte et inversement) | **non** | non | erreur d'intégrité |
| antérieur au gel (migration `d7e2b4c1a9f3` : ni contenu ni empreinte) | oui | non | — |

- Un contenu altéré n'est lu par personne : le bulletin est un incident
  d'intégrité, jamais une correction ordinaire.
- Un contenu antérieur au gel n'a rien à vérifier et rien de rompu. Le
  motif est une colonne de la version, pas une partie du contenu figé :
  le périmètre de classe le lit. L'attributaire ne le lit pas, car la
  correction ne peut pas être ramenée à une ligne.
- Pour l'attributaire, la version corrigée est vérifiée de la même
  façon : altérée → non, et journalisée ; antérieure au gel → non.
- Le motif reste un texte libre : la règle borne l'événement, pas ce
  que dit le texte. Le propriétaire l'a accepté en connaissance de cause.
- Écrans : la grille d'un attributaire affiche les motifs que la règle
  lui ouvre ; la consolidation n'affiche que les motifs du périmètre de
  classe (choix d'interface, #126).

## Précision des pourcentages dans le contenu figé

Le `pourcentage_affiche` du contenu figé d'une version est arrondi au
`percentage_decimal_places` du tenant au moment de la publication, puis
ne bouge plus, même si la configuration change ensuite (#69, partiel).
Une configuration de calcul incomplète refuse la publication avec une
erreur explicite, jamais une valeur par défaut (invariant 2).

La précision prise en charge va de **0 à 6 décimales**
(`MIN_PERCENTAGE_DECIMAL_PLACES`, `MAX_PERCENTAGE_DECIMAL_PLACES` dans
`app/services/tenant_calculation.py`). Une valeur stockée hors de ces
bornes est une configuration invalide : la publication est refusée avec
le même message explicite (réponse 409), jamais ramenée en silence à une
valeur par défaut, et jamais laissée produire une exception non traitée.
La précision appliquée est elle-même figée dans le contenu
(`precision_pourcentage`).

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
