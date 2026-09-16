# Thématisation et bulletins multi-écoles

## État de cette livraison

Branche : `feat/frontend-multitenant-theming`, construite sur le portail de la PR #33.
Les chantiers indépendants 1, 2 et 4 sont préparés. La résolution réelle du tenant,
les états d’authentification et la console super-admin ne sont pas simulés en production.

La règle de séquencement impose d’attendre la fusion de la PR backend #39.
Le contrat de référence est publié dans le [journal #40](https://github.com/DanielRukwasha/urafiki-school-core/issues/40).
Aucun modèle ni migration n’a été modifié. Le contexte neutre actuel est volontairement
sans accès à la base : il doit être remplacé par l’adaptateur après fusion.

## Composants

- `app/ui/theming.py` : données d’identité, normalisation et palette calculée.
- `app/ui/reports.py` : schéma de présentation validé, colonnes et libellés FR/EN.
- `app/ui/access.py` : messages pour les états d’accès décidés par le backend.
- `app/ui/report_assets.py` : inclusion sûre des logos dans les PDF.
- `components/theme.html` : identité visuelle et variables CSS sur `:root`.
- `portal/print.html` : même gabarit pour toutes les structures de périodes.
- `portal/report_editor.html` : éditeur et iframe d’aperçu non officiel.

Chaque appel crée une nouvelle présentation. Il n’existe aucun cache global de
nom, logo, palette ou configuration pouvant être réutilisé entre requêtes.
Aucun sélecteur d’établissement n’est envoyé au navigateur.

## Contrat de présentation interne

Ce format est un objet de présentation Python, **pas une nouvelle table ni une API de persistance** :

```python
theme = build_theme({
    "display_name": configuration_name,
    "primary_color": "#2563eb",
    "accent_color": "#0f766e",
    "neutral_color": "#64748b",
    "logo_url": "/static/tenant-assets/tenant-id/logo.png",
    "favicon_url": "/static/tenant-assets/tenant-id/favicon.png",
    "locale": "fr",
})
```

Les couleurs acceptées sont uniquement des hexadécimaux à six chiffres.
Les données textuelles restent échappées par Jinja. Aucun champ ne peut injecter
du HTML, du CSS ou un fragment de gabarit exécutable.

Les valeurs d’identité absentes produisent un repli ardoise, un nom générique et
des initiales calculées, sans emprunter l’identité d’une autre école.
Un logo absent n’empêche jamais la lecture du nom.

### Variables CSS

| Variables | Usage |
|---|---|
| `--primary`, `--on-primary` | boutons et marque principale |
| `--accent`, `--on-accent` | liens et accents |
| `--neutral` | teinte de départ des neutres |
| `--background`, `--surface` | page et panneaux |
| `--surface-subtle`, `--surface-hover` | tableaux et navigation |
| `--text`, `--muted` | texte principal et secondaire |
| `--line`, `--control-border`, `--focus` | séparateurs, champs et focus |
| `--error`, `--success`, `--warning`, `--info` | états sémantiques |
| `--*-surface` | fond associé à chaque état |

Les feuilles de style et les gabarits ne contiennent aucune couleur hexadécimale
d’identité. Le logo, le favicon et le nom sont des attributs HTML échappés, pas des
chaînes interpolées dans une règle CSS.

## Garde-fous de contraste

La luminance utilise la conversion sRGB avec le seuil 0,04045 et la formule de
contraste `(Lclair + 0,05) / (Lfoncé + 0,05)`. Les rapports ne sont jamais arrondis
avant comparaison.

La palette conserve la teinte primaire autant que possible, éclaircit les fonds,
réduit la saturation des neutres et assombrit les couleurs de texte/actions lorsque
nécessaire. Les valeurs RGB finales sont revérifiées après quantification.

- Texte courant : minimum 4,5:1 ; cible de calcul 4,8:1.
- Texte principal : cible 7:1.
- Bordures nécessaires et focus : minimum 3:1 ; cible 3,1:1.
- Les états sont aussi écrits en texte, jamais indiqués uniquement par couleur.
- La couleur choisie peut être corrigée ; `Theme.adjustments` décrit les champs concernés.

Références : [WCAG 2.2, contraste du texte](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
et [contraste non textuel](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).

## Bulletins configurables

`build_report_layout` accepte :

- langue FR/EN ; les libellés de rapport et le `lang` du document sont cohérents ;
- `header_lines`, `legal_text`, `signatures` (jusqu’à quatre blocs) ;
- `labels` : titres et libellés en texte brut ;
- `columns` : ordre des colonnes parmi cours, code, coefficient, maximum, cote,
  points pondérés ; cours et cote restent obligatoires ;
- `ranking_columns` : ordre des colonnes du palmarès ;
- format A4 portrait/paysage, alignement d’en-tête, affichage du logo ;
- taille de texte limitée entre 9 et 12 points.

Les noms et dates des périodes proviennent du contexte académique, pas de
conditions « trimestre »/« semestre » dans le template. Les tableaux répètent
leurs en-têtes et les bulletins commencent sur une nouvelle page. Le paysage
utilise un espacement adapté à sa hauteur disponible.

L’interface générale de cette livraison reste en français ; la langue des
bulletins est indépendante. Le nom de l’établissement porte son attribut de
langue propre pour les technologies d’assistance.

L’éditeur est réservé à DIRECTION. Son POST valide la configuration puis affiche
un aperçu éphémère dans une iframe nommée. Il ne sauvegarde pas les paramètres
et ne publie pas de bulletin. Le marquage « APERÇU - NON OFFICIEL » est imposé
et répété dans le pied de chaque page PDF ; il ne peut être supprimé par un libellé.

## Logos et favicon

Les URL acceptées sont locales à l’origine : aucun schéma, domaine externe,
chemin de traversée, query string, fragment ou contenu inline fourni par un tenant.
Cela évite aussi les dépendances à un CDN à l’ouverture d’un portail.

Pour WeasyPrint, seules les images PNG/JPEG/WebP de moins de 2 Mo présentes dans
le répertoire statique de l’application sont incorporées en data URI après contrôle
du chemin résolu et de la signature de fichier. Le moteur ne télécharge jamais un
logo arbitraire. Un futur stockage privé devra fournir un chargeur serveur autorisé,
sans accepter une URL de réseau comme source de lecture PDF.

## Ajouter une identité

1. Provisionner l’établissement avec le service Backend prévu à cet effet.
2. Fournir nom et langue via `Institution`, logo et couleur primaire via `TenantConfig`.
3. Déposer les ressources dans l’espace d’assets autorisé de cet établissement.
4. Construire la présentation avec `build_theme` ; contrôler les corrections de palette.
5. Configurer le bulletin et vérifier l’aperçu avant publication.
6. Exécuter les tests d’identité, de contraste et de PDF avant de rendre la configuration active.

**Limite actuelle :** l’étape de sauvegarde complète et le raccordement runtime
attendent le backend. Ne pas ranger les champs manquants dans `feature_flags`,
ni créer une configuration globale qui deviendrait un tenant implicite.

## Adaptation backend attendue

Le journal #40 documente `g.current_ecole_id`, `Institution` par clé primaire et
`TenantConfig` filtré automatiquement. Après fusion, le processor doit lire uniquement
ce tenant résolu, puis produire `ui_theme` et `report_layout`.

| Source validée | Présentation |
|---|---|
| `Institution.name`, `locale` | nom et langue |
| `TenantConfig.primary_color`, `logo_url` | identité principale |
| `report_header`, `report_legal_mentions`, `report_signatures` | blocs du bulletin |
| `feature_flags` | disponibilité des modules uniquement |

Champs/API encore absents du contrat livré : accent, neutre, favicon, libellés et
ordre des colonnes, options de disposition, sauvegarde du gabarit, authentification
et endpoints de console opérateur, limitation de connexion et états détaillés.

La console devra conserver une présentation Urafiki indépendante des écoles et
une session opérateur distincte. Tout accès à des données d’école devra exiger
un motif côté serveur, être journalisé et afficher un bandeau permanent. Ces écrans
ne sont pas livrés avant la fusion et la disponibilité de ce contrat.

La grille HTMX et ses brouillons sont conservés. La séparation par origine du
navigateur existe déjà ; l’intégration devra ajouter la clé du tenant résolu aux
clés de brouillon/verrou et vérifier l’isolation avec le vrai middleware, sans
faire confiance à un identifiant envoyé par le navigateur pour autoriser une requête.

## Vérification

```sh
pip install -r requirements-browser.txt -r requirements-pdf.txt
python -m playwright install chromium
ruff check .
pytest -q
```

Les tests couvrent 157 palettes, deux identités fictives, les URL d’assets,
l’absence de noms d’écoles/couleurs littérales dans les sources de présentation,
les états d’accès, les permissions de l’éditeur, l’échappement des textes,
les aperçus non officiels et les PDF A4 portrait/paysage.

Les fixtures de présentation sur deux hôtes sont explicitement des simulations
de contrat, **pas une preuve d’isolation du runtime multi-tenant**. Cette preuve
sera ajoutée après fusion et raccordement au middleware réel.

Les captures et PDF de contrôle sont sous `tmp/portal-review/` et publiés en
artefact CI. Les tests de contraste ne constituent pas à eux seuls un audit WCAG complet.

