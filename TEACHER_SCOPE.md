# Périmètre enseignant par classe

Les droits d’un enseignant sont résolus par le backend pour chaque requête.
Le compte ne porte aucun droit global de titulaire. Le backend porte le
titulariat sur `SchoolClass.titulaire_id` et le portail vérifie ce périmètre
avec `is_titulaire()` / `require_direction_or_titulaire()`.

```python
class SchoolClass:
    titulaire_id: int | None
```

Le titulariat autorise la consultation de toutes les cotes et de l’état
d’avancement de la classe. L’écriture reste bornée aux `TeacherAssignment`.
Une cote saisie par un autre enseignant reste en lecture seule.

La transition POST `consolidation/submit` est disponible au titulaire de la
classe. Le service serveur persiste l’état **soumis par le titulaire**, son
horodatage et son entrée d’audit. Les transitions `consolidate`, `validate` et
`publish` restent réservées à la direction.

La navigation est construite à partir de ce contexte côté serveur. Le client
ne filtre ni les classes ni les droits : il ne fait qu’afficher les actions
que le serveur lui a accordées.
