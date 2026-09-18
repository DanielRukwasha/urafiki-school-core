# Périmètre enseignant par classe

Les droits d’un enseignant sont résolus par le backend pour chaque requête.
Le compte ne porte aucun droit global de titulaire. Le portail lit le contexte
`g.teaching_scope` (alias temporaire accepté : `g.teacher_scope`) :

```python
{
    "titular_class_ids": [12],
    "editable_course_ids": [31, 32],
    "submit_class_ids": [12],
}
```

`titular_class_ids` autorise la consultation de toutes les cotes et de l’état
d’avancement de la classe. `editable_course_ids` est la seule liste qui rend
une cellule éditable. Le portail vérifie aussi le propriétaire de la cote
existante avant toute modification : une cote saisie par un autre enseignant
reste en lecture seule.

`submit_class_ids` alimente le bouton de soumission. La route appelle le
handler serveur `g.submit_class_handler`, qui doit persister l’état
**soumis par le titulaire**, son horodatage et son entrée d’audit. Si ce
handler n’est pas installé, la route renvoie `503` et n’avance jamais la
machine à états côté client.

La navigation est construite à partir de ce contexte côté serveur. Le client
ne filtre ni les classes ni les droits : il ne fait qu’afficher les actions
que le serveur lui a accordées.
