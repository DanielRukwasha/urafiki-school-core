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
une délégation ACTIVE couvrant `at` (par défaut maintenant) prime sur le
titulaire enregistré.

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

Toute route gérée par `authorization_service` renvoie **404** (pas 403)
quand l'utilisateur n'a pas le droit sur la ressource demandée — une
classe qui existe mais n'est pas la sienne répond exactement comme une
classe qui n'existe pas, pour ne jamais permettre à une requête de
sonder l'existence d'une ressource hors périmètre. 403 reste réservé à
`@roles_required` (mauvais rôle, en général) et au compte désactivé
(`session_check`).

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
