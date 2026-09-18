# Portail de saisie Urafiki

## Organisation

Le blueprint `portal` expose le tableau de bord, les attributions, la grille,
les résultats de période et les impressions. Les contrôles de rôle et
d'attribution sont appliqués côté serveur, y compris pour chaque cellule envoyée.

- `templates/base.html` : structure responsive et navigation selon le rôle.
- `templates/components/macros.html` : titres, champs accessibles et alertes.
- `templates/portal/` : pages et fragment de confirmation `_sync.html`.
- `static/css/portal.css` : couleurs ardoise, accents verts, focus visibles,
  tableaux défilants, en-têtes fixes et styles mobiles.
- `static/js/grade-grid.js` : brouillons, navigation clavier et coordination HTMX.
- `static/vendor/` : HTMX 2.0.10 et sa licence, servis localement sans CDN.

Les données sont échappées par Jinja. Aucun nom d'école, barème ou coefficient
n'est imposé par le frontend. Les pages métier portent `Cache-Control: no-store`.
Le cache d'historique HTMX est désactivé pour les données scolaires.

## Synchronisation

Chaque saisie crée immédiatement un brouillon local. Après 500 ms d'inactivité,
un événement `sync-grades` déclenche le formulaire `hx-post`. Un seul lot,
de 30 cellules maximum, est en cours à la fois. Le formulaire transmet le jeton
CSRF et un champ `changes` contenant :

```json
[{"enrollment":1,"course":2,"value":"12,5","base":"10.00"}]
```

`base` est la cote serveur connue avant modification. Une transaction avec
verrouillage de ligne compare cette valeur avant toute mutation. Une répétition
du même enregistrement est idempotente. Les mutations passent par le service
d'audit. Les cellules validées ou archivées ne sont jamais modifiables.

Le serveur renvoie un fragment HTML accompagné de `X-Grade-Sync: 1`.
Le client traite explicitement les réponses 200 et 422 sans remplacer la grille,
ce qui préserve focus et saisies intervenues pendant la requête. Un lot peut
contenir des cellules acceptées et des cellules invalides. Seule une confirmation
explicite efface le brouillon correspondant.

- 422 : erreur par cellule, conservée jusqu'à correction ou nouvel essai.
- 400 / 401 / 403 : arrêt des envois, message par cellule et reconnexion/rechargement.
- Coupure / délai / 5xx : conservation locale, nouvelle tentative après 5 secondes.
- Conflit : aucune écriture ; recharger pour obtenir la cote actuelle, puis
  comparer le brouillon ou utiliser « Reprendre la cote serveur ».
- Valeur vide : invalide à l'enregistrement ; une absence de cote reste distincte
  de zéro. La suppression d'une cote n'est pas une opération de cette grille.

## Brouillons et appareils partagés

Les clés sont limitées à l'origine du site, à l'utilisateur, à la classe et à la
période. Aucun nom d'élève n'est stocké dans le cache ; les identifiants et cotes
restent des données scolaires. Les brouillons confirmés sont supprimés. Les brouillons en attente sont retrouvés même après fermeture et réouverture du navigateur. Un verrou Web Locks limite la saisie à un onglet par grille et utilisateur ; les autres onglets restent en lecture seule jusqu’au rechargement. HTTPS (ou localhost) et un navigateur prenant en charge Web Locks sont requis.
La fermeture avec des brouillons déclenche un avertissement. L'export CSV permet
de récupérer les saisies avant de changer d'appareil ou de session.

Le stockage local dépend du navigateur : suppression des données du site,
navigation privée et quota peuvent empêcher la conservation. Une alerte indique
les échecs de stockage, sans annoncer faussement une sauvegarde locale.
La résilience couvre une grille déjà chargée ; une première ouverture hors
connexion nécessite encore le serveur.

## Accessibilité et styles

Labels explicites par élève et cours, en-têtes de table sémantiques, région
défilante nommée, lien d'évitement, focus visibles, résumé `aria-live`,
`aria-invalid` et message relié par `aria-describedby`.
Les états sont écrits en toutes lettres et ne reposent pas seulement sur la couleur.
Tab suit l'ordre naturel ; Haut/Bas et Entrée changent de ligne ; Gauche/Droite
changent de colonne à la limite du texte. Les champs verrouillés sont désactivés.
Les contrôles masqués utilisent la règle `[hidden]` pour rester hors du focus.

## Résultats et PDF

Les pourcentages et rangs proviennent du moteur Decimal existant. Les notes
manquantes sont exclues, les ex aequo partagent le rang et les résultats partiels
sont signalés. Cette vue prépare la délibération de période ; elle ne prétend pas
prononcer une décision annuelle.

Installer `requirements-pdf.txt` et les bibliothèques natives Pango selon
[la documentation WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).
Sur Ubuntu : `sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0`.
Sur Windows, configurer `WEASYPRINT_DLL_DIRECTORIES` vers les DLL natives.
Le déploiement peut garder l'aperçu imprimable sans PDF : l'absence du moteur
retourne une page 503 explicite avec accès à l'aperçu.

Le template autonome `print.html` contient tout son CSS : A4 portrait, marges
fixes, pagination, répétition des en-têtes de tableau et saut avant chaque bulletin.
Aucune ressource distante n'est requise par le rendu PDF.

## Vérification

```sh
pip install -r requirements-browser.txt -r requirements-pdf.txt
python -m playwright install chromium
ruff check .
pytest tests/unit tests/integration -q
pytest tests/browser -q
```

Les tests navigateur utilisent une base de test et un serveur sur une adresse
locale avec port aléatoire. Ils vérifient la saisie, les erreurs 400/422,
la coupure réseau, le rechargement, les modifications en cours de requête,
le clavier et la largeur mobile. Les tests PDF vérifient A4, plusieurs pages
et la présence du dernier élève. `REQUIRE_PDF=1` rend le moteur obligatoire.
Les captures et documents de vérification sont produits dans `tmp/portal-review/`
(ignoré par Git). Les contrôles automatisés ne remplacent pas une évaluation
complète avec lecteurs d'écran.

