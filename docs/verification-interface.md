# Vérification reproductible de conformité de l’interface

Branche : `feat/frontend-conformite-interface`. Issue #53, jalon Conformite du socle. Les tests ci-dessous tournent dans les jobs CI obligatoires existants, sans nouveau framework ni build JavaScript.

## Environnement et reproduction de la référence

Référence avant modifications : `66af5d1faf95afa43c5b9cb41d28477ab905ee62`. Les traces complètes et conclusions sont publiées dans #40. Ce premier bloc concerne un checkout du hash de référence ci-dessus. Pour le sprint courant, utiliser les commandes et groupes de tests de la section Publication. Deux environnements Python 3.11.16 séparés :

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
.venv-browser/bin/pytest -m browser tests/browser/test_tenant_visuals.py -q
```

Fixtures : Rivage (primaire jaune #ffff00 volontairement impropre, accent magenta) et Horizon (bleu/vert). Les garde-fous corrigent le jaune ; chaque paire affichée respecte 4.5:1 pour le texte et 3:1 pour contours/focus. Ratios non arrondis pour décider du succès. Preuve JSON : `tmp/portal-review/contrast-ratios.json` ; captures des deux tenants dans le même répertoire.

Chaque cellule porte un libellé (`Non saisie`, `Brouillon local`, `Enregistrement…`, `Enregistré sur le serveur`, erreur explicitée ou `Lecture seule`). Les décisions et états de cours ont un libellé textuel ; une pastille seule n’est pas utilisée. Vérifier les captures et PDF en niveaux de gris.

Bootstrap CSS 5.3.8 est local, avec licence et contrôle SHA-384 officiel ; `portal.css` chargé ensuite applique les tokens du tenant. Aucun accès CDN à l’exécution, aucun bundle JS Bootstrap ajouté. Source : https://getbootstrap.com/docs/5.3/getting-started/introduction/.

## PDF WeasyPrint réels

Sur le sprint courant, sélectionner explicitement le groupe `pdf` : le contrôle des dépendances natives échoue si une dépendance manque, sans test ignoré. Les tests vérifient la réponse `application/pdf`, les dimensions A4, pagination, matricules, langue, branding, logo, absence de l’identité de l’autre tenant et de liens d’édition.

```sh
.venv-browser/bin/pytest -m pdf tests/integration/test_portal_pdf.py tests/integration/test_report_presentation_pdf.py -q
pdftoppm -f 1 -singlefile -scale-to 1600 -png tmp/portal-review/rivage-configured.pdf tmp/portal-review/rivage-pdf-page1
pdftoppm -f 1 -singlefile -scale-to 1600 -png tmp/portal-review/horizon-configured.pdf tmp/portal-review/horizon-pdf-page1
```

Ouvrir ces PNG et les dernières pages : pas de texte tronqué, de chevauchement, de cellule coupée ou de logo déformé ; identité et marque d’aperçu visibles. Un aperçu Chromium ne valide pas cette étape. PDF et captures sont archivés par le job browser-pdf.

## Coupure réseau

```sh
.venv-browser/bin/pytest -m browser tests/browser/test_grade_grid.py::test_offline_draft_survives_reload_and_reconnect -q
```

Le scénario réel Playwright : ouvrir la grille, couper le réseau, saisir 16, vérifier le libellé et localStorage, rétablir le réseau en bloquant /sync, recharger, retrouver 16, lever le blocage, provoquer le retour online, vérifier la confirmation serveur sans cliquer Réessayer, recharger et lire 16.00 depuis le serveur. Captures `network-offline.png` et `network-recovered.png`. Tester aussi erreur CSRF, concurrence de deux onglets, modification pendant une requête et stockage local indisponible (suite test_grade_grid.py).

La fixture ferme systématiquement son serveur même si le setup échoue : aucun serveur laissé actif ne doit polluer le test suivant. Aucune dépendance PDF ne résout à elle seule une concurrence SQLite.

## Publication, traduction et critères de fusion

La PR Frontend #56 est empilée sur la PR Backend #55 : fusion Backend d’abord, puis Frontend après revue croisée. Les modèles et services restent propriété Backend. La revue formelle de #55 relève notamment l’absence de snapshot de bulletin ; l’historique affiché ne prouve donc pas encore l’immuabilité du document.

Le formulaire séparé de correction POSTe le motif obligatoire vers `portal.publish_correction`. Le serveur fournit l’action seulement à la Direction après publication, ainsi que la longueur minimale issue du contrat Backend. Le bulletin publié reste sans champ de cote. L’historique expose numéro, motif, auteur et date localisée ; l’échappement des motifs est testé, et les confirmations irréversibles sont des attributs traduits échappés, sans interpolation dans du JavaScript inline.

Les 23 gabarits ont été inspectés : trois composants ne contiennent aucun texte affiché constant ; les autres passent par gettext/ngettext. Les messages JS sont fournis par JSON traduit serveur, avec variables nommées. Les dates utilisent Babel, les nombres un filtre serveur `interface_decimal` sans quantification supplémentaire. Le langage HTML vient de la sélection Babel du tenant, pas d’une couleur ou d’une langue de branding. Les valeurs de saisie conservent le format canonique attendu par le serveur.

```sh
pybabel extract -F babel.cfg -k _l -k lazy_gettext --no-location --sort-output --project=urafiki-school-core --copyright-holder=Urafiki -o app/translations/messages.pot .
pybabel update -i app/translations/messages.pot -d app/translations
pybabel compile -d app/translations
pytest -ra
pytest -m "browser or pdf" -ra
```

Le test CI `test_no_unmarked_visible_template_literals` inspecte le texte HTML et les attributs accessibles. Le test des identités dérive les noms de fixtures ; les codes artificiels d’un ou deux caractères sont exclus pour éviter de confondre des variables de bibliothèques avec des établissements. Cette recherche ne peut identifier un nom inconnu qui n’est dans aucun référentiel de fixtures : la revue humaine reste nécessaire.

Les textes métier configurés (cours, mentions, libellés de bulletin) viennent de la base et ne doivent pas être remplacés par des libellés imposés dans un catalogue. Les messages Python dynamiques non marqués dans les fichiers Backend restent une demande de revue #55/#54 ; appeler gettext au rendu ne remplace pas l’extraction de leurs chaînes à la source. La présence de liens vers des routes non autorisées (par exemple délibération depuis consolidation pour un titulaire) est signalée au Backend : pas de masquage CSS/JS ajouté.

## Preuves déjà vérifiées avant raccordement

Le lot précédent a passé 157 tests unitaires/intégration avec PDF et 12 tests navigateur/PDF. Les nouvelles traductions et le raccordement Backend exigent une nouvelle exécution complète, dont le résultat sera inscrit dans la PR et le journal de session.

Contrastes Chromium : bouton Rivage 5.0224082334:1, bouton Horizon 5.2468854695:1 ; titres 7.3063:1 et 14.2096:1. Les palettes éloignées comprennent un jaune primaire volontairement inadéquat, corrigé par le garde-fou serveur. Les cellules disposent systématiquement d’un libellé, pas seulement d’une couleur. Aucun total, rang ou pourcentage scolaire n’est calculé en JavaScript.

Inspection des PDF natifs : Rivage page 1 couleur, Horizon page 2 en gris, portrait/paysage A4. Logos, colonnes et signatures lisibles ; absence de troncature ou superposition sur les pages inspectées. Les fichiers PDF sont générés par WeasyPrint, puis rasterisés avec Poppler ; les captures navigateur ne servent pas de preuve du rendu PDF.

## Résultat du raccordement (2026-10-04)

Sur le socle Backend `9b631615302b2bc79e81cc1bb874b95962184f93` et le diff Frontend soumis à #56 : `pytest -ra` donne 250 réussis / 16 désélectionnés (groupes séparés), puis `pytest -m "browser or pdf" -ra` donne 12 réussis / 254 désélectionnés. Aucun test sélectionné ignoré. L’environnement Linux utilise Python 3.11.16, PostgreSQL 16.15, Flask-Babel 4.0.0, Babel 2.18.0, WeasyPrint 70, Playwright 1.63 et Chromium 153. Le job PostgreSQL est reproduit avec `pytest -ra --cov=app --cov-report=term-missing` : 250 réussis, couverture 92 %, migrations montée/descente/remontée réussies. Les dépendances natives et la réconciliation du commit main sont détaillées dans #40.

Les suites natives signalent un avertissement WeasyPrint concernant une dépendance HarfBuzz-Subset requise par une future version ; cela n’a pas empêché la génération actuelle. PDF et ratios sont dans les artefacts `portal-visual-review` de la CI. Inspection complémentaire : `rivage-final-pdf.png` page 1 et `horizon-final-pdf-gray.png` page 2, issues des PDF réels après traduction ; résultat lisible, sans troncature observée sur ces deux pages. Les fichiers temporaires ne sont pas versionnés.
