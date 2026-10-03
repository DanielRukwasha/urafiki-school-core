# Vérification reproductible de conformité de l’interface

Branche : `feat/frontend-conformite-interface`. Issue #53, jalon Conformite du socle. Les tests ci-dessous tournent dans les jobs CI obligatoires existants, sans nouveau framework ni build JavaScript.

## Environnement et reproduction de la référence

Référence avant modifications : `66af5d1faf95afa43c5b9cb41d28477ab905ee62`. Les traces complètes et conclusions sont publiées dans #40. Deux environnements Python 3.11.16 séparés :

```sh
python3.11 -m venv .venv-core
.venv-core/bin/pip install -r requirements-dev.txt
# Base PostgreSQL 16 de TEST exclusivement : les fixtures drop_all/create_all détruisent son contenu.
export FLASK_ENV=testing SECRET_KEY=ci-only-secret
export DATABASE_URL=postgresql+psycopg://urafiki:urafiki@localhost:55432/urafiki_test
export TEST_DATABASE_URL="$DATABASE_URL"
.venv-core/bin/flask --app wsgi.py db upgrade
.venv-core/bin/pytest tests/unit tests/integration --cov=app --cov-report=term-missing

python3.11 -m venv .venv-browser
.venv-browser/bin/pip install -r requirements-browser.txt -r requirements-pdf.txt
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 poppler-utils
.venv-browser/bin/python -m playwright install --with-deps chromium
unset DATABASE_URL TEST_DATABASE_URL
REQUIRE_PDF=1 .venv-browser/bin/pytest tests/browser tests/integration/test_portal_pdf.py tests/integration/test_report_presentation_pdf.py -q
```

Référence reproduite sous WSL Ubuntu 26.04 : core 146 réussis / 4 PDF ignorés, navigateur/PDF 12 réussis / aucun ignoré. PostgreSQL 16.15, image CI identique ; Chromium 153.0.8010.12. Pango 1.57.0, WeasyPrint 70.0. Runner GitHub Ubuntu 24.04 : les versions natives ne sont pas supposées identiques. Les erreurs navigateur Windows sont distinctes des PDF ignorés par manque de GLib/Pango. Ne pas conclure une cause unique sans test contrôlé.

## Noms, calculs et périmètre

`tests/unit/test_interface_invariants.py` recherche automatiquement les identités d’établissement, cours et niveaux extraites des fixtures dans tous les gabarits et fichiers texte statiques, accents et casse normalisés. Ce contrôle rejette des occurrences connues ; il ne prétend pas reconnaître tout nom inconnu. Le contrôle Jinja AST rejette les opérations arithmétiques sur les champs de cote/total/pourcentage/rang. La colonne pondérée consomme `CourseBreakdown.weighted_points` calculé par le moteur serveur.

Le JavaScript de grille manipule uniquement les brouillons, identifiants, événements et états de synchronisation. Les compteurs de changements en attente sont des états de saisie, pas des résultats scolaires ; aucun total, taux ou rang n’y est calculé. Le contrôle de permission porte sur la réponse serveur brute : une cote et un cours non attribués ne doivent apparaître nulle part dans le HTML, y compris les attributs et champs cachés.

Audit de masquage : `.sr-only` sert aux lecteurs d’écran ; `.brand-sub`/`.nav-label` sont adaptés au petit écran ; toolbar est retirée de l’impression ; messages et boutons de reprise sont masqués selon l’état des brouillons. Aucun de ces masquages ne décide d’une permission. Les routes doivent filtrer les données avant rendu. Toute fuite constatée se signale au Backend, sans rustine CSS/JS.

## Contraste et statuts

```sh
.venv-core/bin/pytest tests/unit/test_theming.py tests/unit/test_interface_invariants.py -q
.venv-browser/bin/pytest tests/browser/test_tenant_visuals.py -q
```

Fixtures : Rivage (primaire jaune #ffff00 volontairement impropre, accent magenta) et Horizon (bleu/vert). Les garde-fous corrigent le jaune ; chaque paire affichée respecte 4.5:1 pour le texte et 3:1 pour contours/focus. Ratios non arrondis pour décider du succès. Preuve JSON : `tmp/portal-review/contrast-ratios.json` ; captures des deux tenants dans le même répertoire.

Chaque cellule porte un libellé (`Non saisie`, `Brouillon local`, `Enregistrement…`, `Enregistré sur le serveur`, erreur explicitée ou `Lecture seule`). Les décisions et états de cours ont un libellé textuel ; une pastille seule n’est pas utilisée. Vérifier les captures et PDF en niveaux de gris.

Bootstrap CSS 5.3.8 est local, avec licence et contrôle SHA-384 officiel ; `portal.css` chargé ensuite applique les tokens du tenant. Aucun accès CDN à l’exécution, aucun bundle JS Bootstrap ajouté. Source : https://getbootstrap.com/docs/5.3/getting-started/introduction/.

## PDF WeasyPrint réels

`REQUIRE_PDF=1` transforme une dépendance native absente en échec, jamais en test ignoré. Les tests vérifient la réponse `application/pdf`, les dimensions A4, pagination, matricules, langue, branding, logo, absence de l’identité de l’autre tenant et de liens d’édition.

```sh
REQUIRE_PDF=1 .venv-browser/bin/pytest tests/integration/test_portal_pdf.py tests/integration/test_report_presentation_pdf.py -q
pdftoppm -f 1 -singlefile -scale-to 1600 -png tmp/portal-review/rivage-configured.pdf tmp/portal-review/rivage-pdf-page1
pdftoppm -f 1 -singlefile -scale-to 1600 -png tmp/portal-review/horizon-configured.pdf tmp/portal-review/horizon-pdf-page1
```

Ouvrir ces PNG et les dernières pages : pas de texte tronqué, de chevauchement, de cellule coupée ou de logo déformé ; identité et marque d’aperçu visibles. Un aperçu Chromium ne valide pas cette étape. PDF et captures sont archivés par le job browser-pdf.

## Coupure réseau

```sh
.venv-browser/bin/pytest tests/browser/test_grade_grid.py::test_offline_draft_survives_reload_and_reconnect -q
```

Le scénario réel Playwright : ouvrir la grille, couper le réseau, saisir 16, vérifier le libellé et localStorage, rétablir le réseau en bloquant /sync, recharger, retrouver 16, lever le blocage, provoquer le retour online, vérifier la confirmation serveur sans cliquer Réessayer, recharger et lire 16.00 depuis le serveur. Captures `network-offline.png` et `network-recovered.png`. Tester aussi erreur CSRF, concurrence de deux onglets, modification pendant une requête et stockage local indisponible (suite test_grade_grid.py).

La fixture ferme systématiquement son serveur même si le setup échoue : aucun serveur laissé actif ne doit polluer le test suivant. Aucune dépendance PDF ne résout à elle seule une concurrence SQLite.

## Publication, dépendances Backend et critères de fusion

Une période soumise/publiée ne rend aucun champ de cote ni action de synchronisation ; test d’intégration sur le HTML brut. La publication demeure annoncée irréversible. Le motif de correction et l’historique auteur/date/version nécessitent le contrat et la validation serveur du Backend : ne pas inventer une route ou stocker une version côté client.

La traduction de l’ensemble des gabarits et messages JS, catalogue français, pluriels et formats localisés attend le socle Backend. Aucun fallback silencieux de traduction ajouté. La PR Frontend reste en brouillon jusqu’au raccordement des contrats et à la revue Backend. Aucune PR Backend ouverte à la date de démarrage ; #53 demande explicitement sa publication. L’absence de cette PR ne permet pas de produire une revue formelle.

## Résultat de ce lot (2026-10-03, avant contrats Backend)

- Lint Ruff : réussi.
- Unitaires/intégration avec PDF natif : 157 réussis, aucun ignoré, 38.02 s (SQLite Linux ; la CI revalide PostgreSQL).
- Navigateur et PDF : 12 réussis, aucun ignoré, 31.87 s.
- Contrastes réellement mesurés dans Chromium : bouton Rivage 5.0224082334:1, bouton Horizon 5.2468854695:1 ; titres 7.3063:1 et 14.2096:1. Valeurs et paires complètes dans browser-contrast.json et contrast-ratios.json, archivées avec les artefacts CI.
- Inspection visuelle des PDF natifs : Rivage page 1 couleur et Horizon page 2 en gris, A4 portrait/paysage, logos, colonnes et signatures lisibles, aucune troncature ni superposition observée. Vérification bornée aux pages inspectées, en complément des contrôles automatiques de toutes les pages.
- Reprise réseau automatique réussie, puis rechargement confirmant la valeur persistée au serveur. Les captures offline/recovered sont produites par le test.
- Statut du sprint : en cours. Traductions, catalogue français, formats localisés, UI de correction motivée et historique non livrés faute des contrats Backend suivis dans #54. Revue formelle Backend également en attente de la PR cible. Aucune fusion autorisée par ces seuls résultats.

### Contrat de correction proposé pour revue Backend (non implémenté)

Le serveur doit fournir une action de correction uniquement à un compte autorisé, avec URL POST, jeton CSRF, version source et contraintes du motif ; et une liste de versions comprenant numéro, motif, auteur et date/heure localisée. L’interface affichera un formulaire séparé du bulletin publié : motif obligatoire, conséquences explicites et validation serveur des erreurs, puis historique accessible et lisible à l’impression. Le bulletin officiel reste sans champs de saisie. Une version ne sera jamais créée par JavaScript ni par un simple changement de compteur local. Les noms de routes/champs seront ceux publiés par le Backend ; aucune signature fictive ne sera branchée.
