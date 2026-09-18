# La grille de cours par niveau

## Le problème que ça résout

Avant cette évolution, un `Course` appartenait à une seule classe
(`school_class_id`) et portait lui-même son coefficient et sa note
maximale. Deux classes du même niveau (deux « 6ème » parallèles, par
exemple) avaient donc chacune leur propre ligne « Mathématiques », sans
rien qui garantisse qu'elles restent identiques — et rien qui empêche un
même cours d'avoir un poids différent d'une classe à l'autre par simple
oubli de synchronisation. L'encodage des notes et le bulletin lisaient
la même donnée par coïncidence, pas par construction.

## Le modèle

```
Niveau            (libellé configurable par école : "6ème", "Terminale S"…)
GroupeCours        (regroupement d'affichage : "Sciences", "Langues"…)
GrilleCours        (une grille = une (section, niveau, année scolaire))
  └─ GrilleCoursLigne   (une matière dans cette grille : poids, groupe,
                          mode de notation)
       └─ GrilleCoursLigneMaximum  (le maximum, PAR PÉRIODE d'évaluation)
```

- **`Course`** est désormais un simple catalogue, propre à l'école
  (`ecole_id` + `code` unique) : nom et code, rien d'autre. Il ne porte
  ni poids ni maximum — la même matière peut apparaître dans plusieurs
  grilles (niveaux différents) avec un poids différent dans chacune.
- **`GrilleCours`** est unique par `(ecole_id, section_id, niveau_id,
  academic_year_id)`. Toute `SchoolClass` partageant ce triplet partage
  la même grille — elle n'est jamais dupliquée par classe. C'est la
  garantie structurelle que l'encodage et le bulletin lisent la même
  source : les deux passent par `resoudre_grille(school_class)`.
- **`GrilleCoursLigne.ponderation`** remplace `Course.coefficient`.
  `entre_dans_total_general` (sur la ligne ET sur son `GroupeCours`) dit
  si la ligne compte dans la moyenne générale ; l'exclusion au niveau du
  groupe exclut toutes ses lignes, quel que soit leur propre indicateur.
- **`GrilleCoursLigneMaximum`** est **par période d'évaluation**, jamais
  une valeur unique par cours. Une école dont le maximum est
  effectivement constant le configure identiquement à chaque période —
  c'est un choix délibéré : l'inverse (partir d'un maximum unique puis
  devoir le faire varier plus tard) casserait rétroactivement tout ce
  qui a déjà été encodé.
- **`note_par_appreciation`** (sur la ligne) marque une matière notée en
  appréciation textuelle plutôt qu'en note chiffrée. Une telle ligne
  n'entre jamais dans un total numérique, quelle que soit la valeur de
  `entre_dans_total_general` — voir `grade_calculation_engine.py`.
- **`Grade`** référence désormais `grille_cours_ligne_id` (plus
  `course_id`). Il porte soit `score` (numérique), soit `appreciation`
  (texte), jamais les deux (`CHECK ck_grade_score_xor_appreciation`) ; un
  `statut` (`ABSENCE_JUSTIFIEE`, `DISPENSE`) explique une absence de note
  sans que ce soit une case « pas encore encodée ».
- **`TeacherAssignment`** référence désormais `(teacher_id,
  school_class_id, grille_cours_ligne_id)`. La classe est nécessaire car
  une même ligne de grille est partagée par plusieurs classes — « cet
  enseignant enseigne cette matière » est ambigu sans préciser dans
  quelle classe (une classe parallèle peut avoir un autre enseignant sur
  la même ligne).

## Reconduction d'une grille d'une année sur l'autre

`app.services.grille_service.dupliquer_grille(grille, academic_year_id=…)`
copie les lignes (matière, poids, groupe, ordre, mode de notation) vers
une nouvelle grille pour l'année cible. **Les maxima par période ne sont
jamais copiés** : ils sont liés aux lignes `EvaluationPeriod` précises de
l'année source, qui n'ont aucun sens dans la nouvelle année — chaque
année configure ses propres maxima. Ce choix a un effet recherché :
aucune donnée de la grille source n'est jamais mutée par cette opération,
donc un bulletin déjà publié une année reste reproductible à l'identique
même après reconduction de la grille pour l'année suivante.

## Signatures publiées (contrat Frontend)

```python
# app/services/grille_service.py
resoudre_grille(school_class, academic_year_id=None) -> GrilleCours
    # lève GrilleConfigError (503 côté routes) si aucune grille n'est
    # configurée pour ce (section, niveau, année) — jamais une grille
    # vide silencieuse.
lignes_actives(grille) -> list[GrilleCoursLigne]
maximum_pour_periode(ligne, periode_id) -> Decimal
    # lève GrilleConfigError si le maximum n'est pas configuré pour
    # cette ligne à cette période.
grille_complete_pour_periode(grille, periode_id) -> bool
dupliquer_grille(grille, *, academic_year_id, created_by=None) -> GrilleCours
```

```python
# app/services/grade_calculation_engine.py — CourseGradeInput
ligne_id: int
groupe_id: int
coefficient: Decimal        # = GrilleCoursLigne.ponderation
max_score: Decimal | None   # None pour une ligne à appréciation
score: Decimal | None
appreciation: str | None = None
included: bool = True       # résolu par l'appelant : ligne ET groupe
is_numeric: bool = True     # False pour une ligne à appréciation

compute_group_subtotals(course_breakdown) -> tuple[GroupSubtotal, ...]
    # sous-totaux par groupe — pour l'affichage du bulletin par
    # rubrique, sans que le moteur connaisse le nom d'aucun groupe.
```

Le moteur de calcul ne connaît toujours aucun nom de niveau, section, ou
matière — il ne lit que ces indicateurs et valeurs numériques, résolus
en amont par l'appelant (le service de délibération ou la vue portail).

## Ce qui n'est pas encore livré

Le rendu du bulletin par groupe (sous-totaux affichés dans le PDF) et
l'éditeur d'interface pour construire/éditer une grille (Niveau,
GroupeCours, GrilleCoursLigne, maxima) restent à construire côté
Frontend — le contrat de service ci-dessus est ce sur quoi s'appuyer.
