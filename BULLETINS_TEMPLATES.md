# Bulletins, consolidation et délibération

Cette branche prépare les vues direction sans inventer de contrat backend. Les
modèles et migrations restent inchangés. Les routes `consolidation` et
`deliberation` attendent un payload placé par le backend dans `g` ; en son
absence elles renvoient `503` afin de ne jamais afficher une synthèse fabriquée.

## Contrat d'affichage

Le payload de consolidation doit contenir `class_name`, `period_name`,
`academic_year`, `courses`, `students`, `decisions`, `distribution`,
`class_average`, `encoding_rate`, `students_without_grade`, `blocking_items` et
`publication`. Les métriques sont déjà calculées par le serveur et sont
affichées telles quelles. Le frontend ne calcule ni moyenne, ni pourcentage, ni
rang, ni décision.

Chaque ligne de décision porte le total, le pourcentage, le rang, la décision
automatique, le libellé de celle-ci, les motifs, et éventuellement la décision
manuelle et son motif. Les deux décisions sont toujours affichées ensemble.
Une décision manuelle doit être accompagnée d'un motif obligatoire côté serveur.

La publication expose au minimum `version`, `state`, `published`, `published_at`
et `history`. Une version publiée n'affiche aucune action d'édition. Toute
correction doit ouvrir une nouvelle version ; le bouton de publication doit
décrire l'irréversibilité de la transition et demander confirmation dans le
contrat backend à venir.

## Gabarit WeasyPrint

`portal/print.html` reçoit `ui_theme`, `report_layout`, `rows`, `courses`,
`grades` et `ranks`. L'identité, la langue, le logo, les libellés, les colonnes,
les signatures, les mentions et l'orientation viennent de `report_layout` et
du contexte tenant. Le filigrane `APERÇU - NON OFFICIEL` est imposé au mode
prévisualisation et ne peut pas être retiré par la configuration.

Les tableaux utilisent des en-têtes répétables, `break-inside: avoid` pour les
lignes et `break-before: page` entre bulletins. Le même document fonctionne pour
des périodes nommées trimestre, semestre ou toute autre structure renvoyée par
le serveur. Les rangs ex aequo sont affichés tels qu'ils arrivent dans `ranks`.

## Audit

`portal/audit_log.html` n'offre que des filtres et une pagination serveur :
utilisateur, élève, action et dates. Il ne parcourt ni ne filtre un journal côté
navigateur. Les vues d'audit et de délibération sont réservées à la direction.

## Suite après le backend

Le contrat de [l'issue SPEC](https://github.com/DanielRukwasha/urafiki-school-core/issues/42)
doit fournir les endpoints GET de synthèse/délibération/audit, le POST de
surcharge avec motif, et les transitions consolider/valider/publier avec leur
version et leur historique. Après fusion de la branche backend correspondante,
il faudra raccorder ces endpoints, ajouter les confirmations de transition,
tester l'isolation réelle de deux tenants et intégrer la grille existante aux
clés du tenant résolu.

## Moteur descriptif multi-grilles

Le template `portal/print.html` accepte aussi `report_document`, structure pure de rendu fournie par le serveur. Il ne conna�t aucun niveau, groupe, cours ou nombre de p�riodes. La structure contient `density`, `title`, `period_columns`, `learners`, puis pour chaque �l�ve des `groups`, `lines`, `periods`, `subtotal`, `synthesis` et `notes`. Chaque colonne et chaque libell� sont fournis par le serveur.

Toutes les valeurs num�riques (`display`, `total`, `subtotal`, rangs et synth�ses) sont d�j� produites par le serveur. Une ligne d�appr�ciation fournit `appreciation` et ne fournit pas de maximum. Une ligne ou un groupe exclu du total fournit `included: false` et un libell� explicite ; le rendu ne d�pend jamais de la couleur seule. Les groupes et les sous-totaux sont prot�g�s par `break-inside: avoid`, les en-t�tes de tableau sont r�p�t�s par WeasyPrint, et la classe de densit� est choisie c�t� serveur pour les bulletins longs.

Le contexte Flask peut injecter cette structure dans `g.report_document`. L�adaptateur de route la transmet telle quelle � Jinja ; il ne compl�te ni ne calcule de champ. En l�absence de cette structure, le rendu historique reste disponible pendant la migration du contrat.
