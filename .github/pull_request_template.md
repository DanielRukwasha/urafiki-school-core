## Objet

<!-- Ce que fait la PR, l'issue ou le sprint qu'elle traite. -->

Agent auteur : <!-- backend | frontend -->

## Protocole de revue (AGENT_BRIEFING.md §6 ter) : aucune étape sautée

- [ ] **Auteur** : poussé sous le compte machine ; chaque commit se termine par le repère de l'agent (`BA` pour le Backend), sans autre ligne d'attribution.
- [ ] **Auteur** : CI verte ; réponse dans la PR avec les commits, le SHA et le lien du run.
- [ ] **Autre agent** : revue ciblée en commentaire, chaque constat avec chemin du fichier et numéro de ligne (lien au SHA relu), verdict explicite.
- [ ] **Auteur** : corrections poussées et réponse constat par constat ; correctifs relus par l'autre agent.
- [ ] **Propriétaire** : verdict lu, approbation autorisée.
- [ ] **Propriétaire** : approbation et fusion faites lui-même, depuis son compte personnel.

> Aucun agent n'exécute `gh pr merge`, `gh pr review --approve` ni l'appel API équivalent (invariant 13). Un agent qui juge la PR prête le dit en commentaire et s'arrête.

## Vérifications

- [ ] `SPRINTS.md` mis à jour dans cette PR.
- [ ] Invariants touchés : test de réfutation ajouté ou cité.
- [ ] Aucune valeur de `GH_TOKEN` ni de secret dans le code, les commits, les journaux ou les commentaires.
