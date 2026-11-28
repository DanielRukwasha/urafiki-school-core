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
| 10 | Backend | feat/backend-conformite-socle | fusionné | 2026-11-23 | #55 | Mise en conformité du socle avec les invariants (jalon « Conformité du socle ») |
| 12 | Backend | feat/backend-conformite-socle | fusionné | 2026-11-23 | #55 | Bloquants de la revue Frontend de #55 : contenu figé des versions, langue sans catalogue, instantané de sauvegarde partagé ; puis revue de suivi : lecture figée sans grille vivante, lien PDF versionné, garde du journal, CI épinglée (n° 11 : sprint Frontend sur #56) |
| 13 | Backend | fix/404-hors-perimetre | fusionné | 2026-11-28 | #125 | #76 : 404 pour les refus hors périmètre (`roles_required`, session d'une autre école), 403 du compte désactivé rendu atteignable et documenté |
| 14 | Frontend | fix/frontend-badges-etat | livré | 2026-11-27 | #127 | Contrat d’état des badges de consolidation et accessibilité |
| 15 | Backend | fix/titulaire-a-date | livré | 2026-11-28 | #128 | #84 : titulaire à une date passée lu dans `TitulaireHistorique`, délégation en vigueur à cette date |
| 17 | Backend | test/fixtures-divergentes | livré | 2026-11-28 | #131 | #88 : deux niveaux aux grilles divergentes par école fictive (cours, groupes, maxima par période, cours exclu, appréciation) et garde-fou réfuté |
| 19 | Backend | test/reference-moteur | livré | 2026-11-28 | #132 | #89 : fichier de valeurs attendues du moteur sur les fixtures divergentes, comparé au centime en CI |

## Notes

- **Sprint 5** : la branche `feat/frontend-bulletins-deliberation` portait
  deux commits postérieurs à la fusion de #44 (`b4014d1`, `73ac6fb`), jamais
  fusionnés. La branche a été supprimée de GitHub après la phase 0 ; ces
  commits ne sont plus dans aucune branche distante. Ils sont conservés dans
  les clones locaux et dans un bundle git
  (`urafiki-sauvegarde-feat-frontend-bulletins-deliberation.bundle`), et
  depuis le 2026-11-23 dans la branche distante
  `archive/frontend-bulletins-deliberation`. Leur sort est à arbitrer.
- **Sprint 10** : bloqué partiellement par l'approvisionnement du stockage
  objet hors site (voir RESTAURATION.md). Fusion conditionnée à la revue de
  l'agent Frontend ; la protection de `main` exige désormais une approbation
  par un compte autre que l'auteur.
- **Interruption du 2026-10-17 au 2026-11-23** : aucun commit ni aucune
  fusion. Cause : #55 ne pouvait pas être approuvée, car les deux agents
  utilisaient le seul compte du propriétaire (#66). Le 2026-10-16, le
  propriétaire a interdit aux agents de pousser sous son compte tant que le
  jeton du compte machine n'était pas disponible : travail local seulement.
  Un premier jeton, exposé par l'affichage de la variable `GH_TOKEN`, a été
  révoqué ; le jeton en vigueur date du 2026-11-22 (`AGENT_BRIEFING.md`
  §6 bis). La reprise a eu lieu le 2026-11-22, heure locale.
- **Fusion de #55** : le 2026-11-23 à 01:57 UTC, commit de fusion
  `89e5895`, après la revue de suivi du Frontend sur les correctifs
  `6d9d914`, `a6ddc7c`, `ef16c14` et `d03ce8a`, et CI verte au SHA
  `d03ce8a`.
- **Manquement au processus, exception unique à l'invariant 13** : la
  fusion `89e5895` (et l'approbation de 01:51 UTC qui la précède) a été
  faite par le compte machine `DanielRukwashabot`, et non par le
  propriétaire. Sur le fond, rien n'est fautif : la revue et l'accord du
  propriétaire étaient légitimes. Le manquement montre que le compte
  machine peut à la fois approuver et fusionner les PR dont le propriétaire
  est l'auteur enregistré, si bien qu'aucune barrière humaine ne subsiste
  sur ces PR. Réponse : invariant 13 et protocole de revue
  (`AGENT_BRIEFING.md` §3 et §6 ter). `89e5895` reste la seule fusion sur
  `main` faite par un autre auteur que `Daniel Rukwasha`.
- **Fusions de synchronisation hors `main`** : `8bb8ec6` et `c284488`
  (2026-09-17) et `b3a3ffb` (2026-09-18), de `rukwashai`, sont des fusions
  faites sur des branches de travail puis entrées dans `main` par leur PR.
  Elles apparaissent dans `git log main --merges`, d'où l'option
  `--first-parent` du test de l'invariant 13.
- **PR #73** (documentation seule, Backend) : procédure du compte machine,
  règle 404/403, invariant 13, protocole de revue, règles du jeton,
  repère `BA` en fin de commit. Ouverte le 2026-11-23, en attente de revue.
