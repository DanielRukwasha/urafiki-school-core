# Navigation et périmètres

La navigation d’un enseignant est une projection du contexte serveur de la
requête. Elle ne fabrique aucune classe, aucun cours et ne masque pas une
action autorisée avec CSS ou JavaScript.

Le titulaire est résolu par classe (`SchoolClass.titulaire_id`, ou le service
d’autorisation du backend lorsqu’une délégation est active). Dans sa classe,
il peut consulter la grille complète, l’avancement et la consolidation ; ses
écritures restent limitées aux lignes de grille qui lui sont attribuées. Une
classe titulaire sans attribution ouvre la supervision en lecture seule. Une
classe où il est uniquement attributaire ouvre les cours attribués et la
grille d’encodage correspondante.

La transition `consolidation/submit` est réservée au titulaire effectif ou à la
direction. Elle vérifie l’avancement côté serveur, enregistre l’horodatage et
l’audit, puis fait passer la période à `SUBMITTED`. Les transitions suivantes
(`consolidate`, `validate`, `publish`) restent de la responsabilité de la
direction. Une période soumise ou fermée ne propose aucun champ d’édition.

Le fil d’Ariane et la période active doivent être alimentés par la structure de
navigation serveur dès que les issues #47 et #48 publient leur contrat. Le
gabarit actuel conserve la grille hors-ligne et ses indicateurs locaux ; ceux-ci
ne donnent jamais de droit supplémentaire.

## Contrat de navigation attendu

```python
{
    "active_period": {"label": "...", "key": "..."},
    "classes": [{
        "label": "...", "key": "...", "is_titulaire": True,
        "view": "supervision|encoding",
        "state": {"key": "...", "label": "..."},
        "courses": [{"label": "...", "key": "...", "progress": "...", "state": "..."}],
    }],
}
```

Les libellés et les indicateurs sont toujours ceux du serveur. Un nouveau
tenant ou une nouvelle grille ne demande donc aucune modification de template,
CSS ou script.
