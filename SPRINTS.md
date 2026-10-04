# Sprints

L'état du travail vit ici, dans le dépôt, jamais dans une conversation.
Une ligne par sprint. Chaque agent met à jour sa ligne dans la même PR que
le travail qu'elle décrit : `en cours` à l'ouverture, `livré` quand la PR est
prête pour la revue, `fusionné` à la fusion, avec la date du dernier
changement d'état (AAAA-MM-JJ, UTC).

Statuts : `en cours` · `livré` (PR ouverte, en attente de revue ou
d'arbitrage) · `fusionné` · `abandonné` (avec la raison en note).

| N° | Agent | Branche | Statut | Date | PR | Objet |
|---|---|---|---|---|---|---|
| 1 | Backend | (commit direct, avant protection de `main`) | fusionné | 2026-09-16 | — | P1-Socle et P2-Quotation-Engine |
| 2 | Frontend | feat/portal-grading-ui | fusionné | 2026-09-18 | #33 | Portail de saisie et bulletins A4 |
| 3 | Backend | feat/backend-multitenant-core | fusionné | 2026-09-17 | #39 | Socle d'isolation multi-tenant |
| 4 | Frontend | feat/frontend-multitenant-theming | fusionné | 2026-09-18 | #41, #45 | Thème par tenant, connexion contextualisée, aperçus |
| 5 | Frontend | feat/frontend-bulletins-deliberation | fusionné | 2026-09-18 | #44 | Vues de consolidation et de délibération (2 commits postérieurs non fusionnés, voir note) |
| 6 | Backend | fix/titulaire-scope-and-submission | fusionné | 2026-09-18 | #46 | Périmètre du titulaire, état « soumis » |
| 7 | Frontend | feat/frontend-teacher-scope-docs | livré | 2026-09-18 | #49 | Contrat frontend du titulariat par classe |
| 8 | Backend | feat/backend-grilles-et-perimetres | fusionné | 2026-09-22 | #50 | Grilles de cours par niveau, permissions contextuelles |
| 9 | Frontend | feat/frontend-rendu-et-navigation | livré | 2026-09-23 | #51 | Rendu des bulletins décrit par le serveur |
| 10 | Backend | feat/backend-conformite-socle | livré | 2026-10-03 | #55 | Mise en conformité du socle avec les invariants (jalon « Conformité du socle ») |
| 11 | Frontend | feat/frontend-conformite-interface | livré | 2026-10-04 | #56 | Traductions, accessibilité et corrections motivées |

## Notes

- **Sprint 5** : la branche `feat/frontend-bulletins-deliberation` portait
  deux commits postérieurs à la fusion de #44 (`b4014d1`, `73ac6fb`), jamais
  fusionnés. La branche a été supprimée de GitHub après la phase 0 ; ces
  commits ne sont plus dans aucune branche distante. Ils sont conservés dans
  les clones locaux et dans un bundle git
  (`urafiki-sauvegarde-feat-frontend-bulletins-deliberation.bundle`). Leur
  abandon est documente dans issue #52 (adaptateurs obsoletes).
- **Sprint 10** : bloqué partiellement par l'approvisionnement du stockage
  objet hors site (voir RESTAURATION.md). Fusion conditionnée à la revue de
  l'agent Frontend ; la protection de `main` exige désormais une approbation
  par un compte autre que l'auteur.

- **Sprint 11** : livraison Frontend sur #56, empilée sur #55 ; revue Backend requise, routes partagées à relire. Pas de fusion avant Backend et résolution des constats de #55/#54. Les chaînes dynamiques Python non marquées et les snapshots de bulletin restent attendus du Backend. Les chantiers #49/#51 ne sont pas repris par ce sprint.
