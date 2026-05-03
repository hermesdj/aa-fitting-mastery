# Analyse 0.2.2 - doctrine coverage, KPI can_fly(characters), alpha compatibility

## 1) Objectif

Ce document réanalyse complètement les 3 évolutions demandées pour `aa-fitting-mastery` et les transforme en lots
d’implémentation **autonomes** pour de futurs agents.

Demandes couvertes :

1. **Coverage doctrine strict par personnage** : ne compter que les personnages qui matchent le `SummaryAudienceGroup`,
   tout en conservant le `main_character` comme label visuel si nécessaire.
2. **KPI `can_fly (characters)`** : exposer partout le pendant personnages de `can_fly (players)`.
3. **Compatibilité Alpha/Omega** : afficher l’état clone par skill dans l’éditeur et calculer un KPI de compatibilité du
   plan.

Ce document ne contient **pas** l’implémentation. Il sert de base de travail opérationnelle pour des agents distincts
qui prendraient chacun un lot A/B/C.

---

## 2) Synthèse exécutable

### 2.1 Ce qui est confirmé après relecture

- **Lot A** : il y a bien un bug de scope. Le plugin calcule l’éligibilité audience au niveau user, puis recharge trop
  largement les personnages. Le problème affecte **les pages summary**, mais aussi **les vues pilot detail/export**
  lorsqu’un `group_id` est passé.
- **Lot B** : la donnée backend existe déjà presque partout. Le travail est surtout un travail de **payload clair + UI
  **.
- **Lot C** : la source de vérité est désormais clarifiée (`cloneGrades.yaml`) et **persistée en BDD**. Le lot restant
  est l’exploitation applicative (preview/UI/KPI) de cette donnée persistée.

### 2.2 Recommandation d’ordre

1. **Lot A** d’abord, car il corrige la vérité métier des statistiques et des exports.
2. **Lot B** ensuite, car il s’appuie sur ces chiffres et reste faible risque.
3. **Lot C** en dernier, car il dépend maintenant d’une intégration fonctionnelle transversale
   (services + contexte + templates + tests) à partir des clone grades déjà importés.

---

## 3) État actuel relu en détail

## 3.1 Coverage / SummaryAudienceGroup

### 3.1.1 Ce que fait le code aujourd’hui

- `_summary_group_users()` dans `mastery/views/summary_helpers.py` calcule correctement les **users éligibles** à partir
  d’un match corp/alliance sur **au moins un** character.
- `_build_member_groups_for_summary()` recharge ensuite les `Character` de ces users via
  `eve_character__character_ownership__user__in=eligible_users`, **sans réappliquer le scope character-level**.
- `_get_pilot_detail_characters()` reproduit le même pattern quand un utilisateur ayant la permission
  `mastery.doctrine_summary` ouvre une vue pilot detail avec un `summary_group` : tous les personnages des users
  éligibles sont récupérés, puis seul le filtre d’activité est appliqué.

### 3.1.2 Effets observés

- Un user peut entrer dans le scope via un alt, puis faire remonter **tous ses autres alts hors audience** dans :
    - les KPI doctrine/fitting,
    - les buckets de statut,
    - les écrans detail,
    - l’export CSV de coverage (`mastery/views/summary.py`, `_summary_fitting_member_coverage_csv_response`).
- L’activité est aujourd’hui évaluée **alt par alt**, alors que le besoin métier décrit un pilotage **au niveau joueur
  via
  le main**.

### 3.1.3 Preuves déjà présentes dans la suite de tests

- Le comportement actuel est verrouillé par
  `test_build_member_groups_for_summary_keeps_all_owned_characters_for_user_matched_by_alt`
  dans `mastery/tests/test_views.py`.
- Ce test valide explicitement l’ancien comportement et devra être **remplacé**, pas simplement complété.

### 3.1.4 Impact réel à intégrer dans la spec

Le lot A ne doit pas se limiter à `summary_list_view` : il affecte aussi les chemins suivants.

- `mastery/views/summary_helpers.py`
    - `_summary_group_users`
    - `_build_member_groups_for_summary`
    - `_get_pilot_detail_characters`
- `mastery/views/pilot.py`
    - `pilot_fitting_detail_view`
    - `pilot_fitting_skillplan_export_view`
- `mastery/views/summary.py`
    - les pages detail basées sur `user_rows`
    - l’export CSV de coverage

---

## 3.2 KPI `can_fly (characters)`

### 3.2.1 Ce que fait le code aujourd’hui

- `_build_fitting_kpis()` calcule déjà `flyable_now_characters`.
- `_build_doctrine_kpis()` calcule déjà `flyable_now_characters`.
- L’UI affiche désormais `Flyable now (characters)` dans :
    - `mastery/templates/mastery/partials/_summary_status_kpi_cards.html`
    - `mastery/templates/mastery/partials/_summary_status_kpi_nav_cards.html`
    - `mastery/templates/mastery/summary_list_view.html`
- L’information `Flyable now (players)` est conservée dans les en-têtes/badges de contexte (
  `X/Y members have a flyable alt`),
  au lieu d’être dupliquée dans les cartes KPI detail.

### 3.2.2 Ce qu’il manque pour en faire une feature propre

- Un **dénominateur explicite** côté personnages (`characters_total`) pour éviter les lectures ambiguës.
- Une intégration cohérente dans les vues summary/detail sans casser la grille responsive ni les `colspan`.

---

## 3.3 Alpha/Omega + KPI de compatibilité Alpha

### 3.3.1 Ce que fait le code aujourd’hui

- La source SDE utilisée pour Alpha/Omega est `cloneGrades.yaml`, importée via `SdeMasteryImporter`.
- Les clone grades sont **persistés** en base dans `SdeCloneGradeSkill` via `import_clone_grades(...)`.
- Le flux d’import est unifié avec masteries/certificates :
    - commande `import_sde_masteries`,
    - tâche `update_sde_masteries`.
- Un fallback de backfill est en place : si la version SDE est déjà à jour mais que `SdeCloneGradeSkill` est vide,
  l’import est relancé au lieu d’être ignoré.
- La couche métier/UI du lot C n’est pas encore branchée :
    - `DoctrineSkillService.preview_fitting()` n’expose pas encore `requires_omega`,
    - `_build_plan_kpis()` ne calcule pas encore de compatibilité Alpha,
    - `fitting_skills_editor.html` n’affiche pas encore de badges Alpha/Omega harmonisés.

### 3.3.2 Ce qui est plausible côté données

- `cloneGrades.yaml` est la source de vérité pour les caps Alpha par skill.
- Règle retenue :
    - skill absent de `cloneGrades` => Omega-only,
    - skill présent avec cap `N < 5` => partiellement Alpha,
    - skill présent avec cap `5` => full Alpha.
- `TypeDogma` / attribut `1047` reste un signal legacy/hint et n’est pas utilisé pour la logique de restriction.

### 3.3.3 Conclusion technique

Le lot C est désormais un lot d’**intégration fonctionnelle** (et non de découverte de source) :

1. brancher la donnée persistée `SdeCloneGradeSkill` dans le preview,
2. calculer et exposer les KPI Alpha/Omega requis/recommandés,
3. rendre ces informations lisibles dans l’éditeur avec badges + cards,
4. couvrir le tout par des tests service/vue/template.

---

## 4) Décisions de spec proposées

## 4.1 Lot A - règle cible

Pour un `SummaryAudienceGroup` donné :

- **Stats coverage** : seuls les `Character` qui matchent corp/alliance du groupe sont comptés.
- **Activité** : l’activité est évaluée au niveau joueur à partir du `main_character`.
- **Si `include_inactive=1`** : tous les characters in-scope sont conservés.
- **Sinon** : les characters in-scope du joueur sont conservés seulement si le joueur est actif selon la règle
  ci-dessus.
- **Affichage du nom joueur** : conserver `main_character` comme étiquette visuelle même s’il est hors scope.
- **Le main hors scope reste décoratif** : il ne doit jamais entrer dans les KPI/buckets/exports.

### Décision de fallback à verrouiller pour les agents

Pour éviter une zone grise lorsque le user n’a pas de main configuré :

- **activité** : fallback sur le character in-scope le plus récemment vu,
- **label** : fallback sur `best_character`, puis `user.username`.

Cette décision évite d’exclure arbitrairement les users sans main configuré tout en restant déterministe.

## 4.2 Lot B - décision d’affichage

Décision UI finale :

- Conserver `Flyable now (players)` dans l’entête contextuel (`X / users_total members have a flyable alt`).
- Afficher les cartes KPI detail sur une seule ligne avec `Flyable now (characters)` + buckets de statut.
- Conserver la vue liste doctrine avec les deux colonnes `Flyable now (players)` et `Flyable now (characters)`.

Le lot B reste sans changement métier lourd grâce à `characters_total` ajouté aux payloads KPI.

## 4.3 Lot C - décision de payload minimale

### Niveau skill

Ajouter au minimum sur chaque row preview :

- `requires_omega: bool`
    - `True` : Omega requis
    - `False` : compatible Alpha

`is_alpha_trainable` reste dérivable (`requires_omega is False`) et n’est pas nécessaire si on veut garder le payload
minimal.

### Niveau plan

Ajouter dans `_build_plan_kpis(active_rows)` :

- `required_alpha_compatible: bool | None`
- `recommended_alpha_compatible: bool | None`
- `required_omega_skill_count: int`
- `recommended_omega_skill_count: int`

### Règle de fallback recommandée

Avec `cloneGrades.yaml` comme source de vérité, l’absence d’une compétence dans la table clone grades signifie
**Omega-only**. Il n’y a donc pas d’état `Unknown` dans ce flux.

---

## 5) Informations transverses à donner à tout futur agent

## 5.1 Fichiers à lire avant de coder

Minimum recommandé :

- `working/aa-fitting-mastery/AGENTS.md`
- `mastery/views/summary_helpers.py`
- `mastery/views/summary.py`
- `mastery/views/pilot.py`
- `mastery/views/common.py`
- `mastery/services/doctrine/doctrine_skill_service.py`
- `mastery/services/sde/importer.py`
- `mastery/models/sde_clone_grade_skill.py`
- `mastery/management/commands/import_sde_masteries.py`
- `mastery/tasks.py`
- `mastery/templates/mastery/partials/_summary_status_kpi_cards.html`
- `mastery/templates/mastery/partials/_summary_status_kpi_nav_cards.html`
- `mastery/templates/mastery/summary_list_view.html`
- `mastery/templates/mastery/partials/fitting_skills_editor.html`
- `mastery/tests/test_views.py`
- `mastery/tests/test_services.py`

## 5.2 Commandes de travail / validation

Depuis `working/aa-fitting-mastery` en PowerShell :

```powershell
$env:DJANGO_SETTINGS_MODULE='testauth.settings_aa4.local'
python -u runtests.py mastery.tests.test_views -v 2
python -u runtests.py mastery.tests.test_services -v 2
python -u runtests.py mastery -v 2
pylint --load-plugins pylint_django mastery
python -m django makemigrations --check --dry-run mastery
```

## 5.3 i18n / docs / release

- Si de nouvelles chaînes sont ajoutées, mettre à jour :
    - `mastery/locale/en/LC_MESSAGES/django.po`
    - `mastery/locale/fr_FR/LC_MESSAGES/django.po`
- Sous Windows avec environnement WSL/venv Linux, suivre le pattern documenté dans le `AGENTS.md` racine pour
  `makemessages` / `compilemessages`.
- Mettre à jour au minimum `CHANGELOG.md` sous `## [Unreleased]`.
- **Ne pas** bumper `mastery/__init__.py::__version__` sauf si la tâche est explicitement traitée comme une release.

## 5.4 Contraintes à préserver

- Préserver le style conservateur du projet : pas de refactor hors sujet.
- Garder les views minces ; déplacer la logique métier dans les services si un nouveau calcul métier apparaît.
- Ne pas ajouter de migration si elle n’est pas strictement nécessaire.
- Ne pas injecter de JS Bootstrap supplémentaire juste pour les badges / modals / cards.

---

## 6) Checklist d’implémentation - Lot A

## 6.1 But du lot

Corriger le scope coverage pour que **seuls les characters in-scope** entrent dans les calculs, les écrans detail et les
exports, tout en évaluant l’activité au niveau joueur via le `main_character`.

## 6.2 Hors périmètre du lot

- Aucun changement visuel majeur hors nécessité de cohérence.
- Aucun changement du modèle de données.
- Aucun ajout de KPI Alpha/Omega.

## 6.3 Fichiers / symboles impactés

### Cœur métier

- `mastery/views/summary_helpers.py`
    - `_summary_group_entry_ids`
    - `_summary_group_users`
    - `_build_member_groups_for_summary`
    - `_get_pilot_detail_characters`
    - `_character_last_seen`
    - `_is_character_active`

### Vues consommatrices

- `mastery/views/summary.py`
- `mastery/views/pilot.py`

### Tests

- `mastery/tests/test_views.py`

## 6.4 Règles métier à préserver

- `_summary_group_users()` doit continuer à renvoyer un **queryset de users** : ne pas le transformer en queryset de
  `Character`, car d’autres callsites s’en servent comme garde d’accès.
- Le `main_character` peut être **hors audience** mais rester le **label** du joueur.
- Le `best_character` doit être choisi **uniquement parmi les characters in-scope**.
- Les KPI et buckets doivent être calculés **sur les seuls characters in-scope actifs**.
- `include_inactive=1` ne doit jamais faire revenir des characters hors scope.

## 6.5 Checklist d’implémentation détaillée

- [x] Ajouter un helper réutilisable, idéalement dans `summary_helpers.py`, du style
  `_summary_group_character_filters(summary_group) -> Q | None`.
- [x] Réutiliser ce helper dans `_summary_group_users()` pour éviter la duplication de logique corp/alliance.
- [x] Ajouter un helper de queryset si utile, du style
  `_summary_group_characters_queryset(summary_group, users=None)` afin d’éviter deux implémentations divergentes du
  scope character-level.
- [x] Modifier `_build_member_groups_for_summary()` pour charger **uniquement** les characters in-scope.
- [x] Revoir la construction de `group` pour distinguer clairement :
    - [x] `main_character` (label),
    - [x] `characters` (uniquement in-scope),
    - [x] `active_count`,
    - [x] `total_count`.
- [x] Introduire un helper dédié d’activité joueur, par ex.
  `_is_summary_member_active(group, cutoff, include_inactive)`.
- [x] Faire porter le filtre d’activité sur le `main_character` si présent.
- [x] Appliquer la décision de fallback d’activité si le main est absent : character in-scope le plus récemment vu.
- [x] Vérifier que `group["total_count"]` devient bien le total **in-scope**, pas le total du compte.
- [x] Vérifier que `group["characters"]` ne contient plus jamais de character hors scope.
- [x] Modifier `_get_pilot_detail_characters()` pour appliquer le même scope character-level quand `summary_group` est
  utilisé.
- [x] Vérifier l’impact sur `pilot_fitting_detail_view` et `pilot_fitting_skillplan_export_view` : les listes proposées
  et
  les exports texte ne doivent plus montrer d’alts hors scope.
- [x] Vérifier l’impact sur l’export CSV summary : le CSV doit refléter exactement les `user_rows` in-scope. *(test
  dédié ajouté ; validation manuelle UI/export à faire)*
- [x] Ne pas casser le tri actuel par label (`main_character.character_name` sinon fallback).

## 6.6 Checklist de tests à écrire / adapter

- [x] Supprimer/remplacer le test qui valide l’ancien comportement :
  `test_build_member_groups_for_summary_keeps_all_owned_characters_for_user_matched_by_alt`.
- [x] Ajouter un test : main hors scope + alt in-scope + main actif => seul l’alt in-scope est conservé.
- [x] Ajouter un test : main actif + alt in-scope inactif => l’alt reste présent si `include_inactive=False`.
- [x] Ajouter un test : main inactif + alt in-scope => joueur exclu si `include_inactive=False`.
- [x] Ajouter un test : `include_inactive=1` conserve tous les characters in-scope, jamais hors scope.
- [x] Ajouter un test : user sans character in-scope => absent des KPI / groups.
- [x] Ajouter un test sur `_get_pilot_detail_characters()` avec `summary_group` pour prouver que seuls les characters
  in-scope sont proposés dans le detail/export.
- [x] Ajouter un test de régression CSV si la suite en contient déjà le point d’entrée ; sinon tester le contenu des
  `user_rows` source qui alimentent le CSV.

## 6.7 Checklist de validation manuelle

- [ ] Ouvrir `summary_list_view` sur un groupe avec un user ayant main hors scope + alt in-scope.
- [ ] Vérifier que le user est bien présent, mais avec seulement ses alts in-scope comptés.
- [ ] Vérifier qu’un fitting detail n’affiche plus d’alts hors scope.
- [ ] Vérifier que l’export skillplan pilot n’accepte plus un `character_id` hors scope quand `group_id` est actif.
- [ ] Vérifier qu’un export CSV coverage ne contient plus de character hors audience.

## 6.8 Critères d’acceptation du lot Aw

- [x] Tous les KPI summary/doctrine/fitting sont calculés sur des characters in-scope uniquement.
- [x] Le label joueur reste lisible via le `main_character` même si ce main est hors scope.
- [x] L’activité n’exclut plus un alt spécialisé simplement parce que cet alt ne s’est pas connecté récemment, tant que
  le main reste actif.
- [ ] Aucun alt hors scope n’apparaît dans les pages detail ni dans les exports quand un `summary_group` est actif. *(
  test CSV manuel à confirmer)*

## 6.9 Progression d’implémentation (fait)

- `mastery/views/summary_helpers.py`
    - Ajout de `_summary_group_character_filters()` et `_summary_group_characters_queryset()`.
    - `_summary_group_users()` refactoré pour réutiliser la même source de vérité character-level.
    - `_build_member_groups_for_summary()` refactoré :
        - charge uniquement les characters in-scope,
        - résout l’activité au niveau joueur via `main_character`,
        - applique fallback sur le character in-scope le plus récemment vu.
    - `_get_pilot_detail_characters()` aligné sur la même logique via `_build_member_groups_for_summary()`.
- `mastery/tests/test_views.py`
    - Tests Lot A remplacés/ajoutés pour le nouveau scope et la nouvelle règle d’activité.
    - Ancien test validant le mauvais comportement supprimé/remplacé.
- Exécution tests (OK)
    - `python -u runtests.py mastery.tests.test_views.TestSummaryHelpers -v 2` → **37 passed**
    - `python -u runtests.py mastery.tests.test_views.TestPilotViews -v 2` → **14 passed**

## 6.10 Reste à faire pour clôture complète Lot A

- Faire la validation manuelle section 6.7 (UI + export) avant fermeture définitive.

---

## 7) Checklist d’implémentation - Lot B

## 7.1 But du lot

Afficher explicitement le KPI `Flyable now (characters)` dans toutes les vues summary, avec `Flyable now (players)`
exposé dans l’entête contextuel des vues detail.

## 7.2 Hors périmètre du lot

- Pas de changement métier profond.
- Pas de refonte complète des cartes KPI.

## 7.3 Fichiers / symboles impactés

### Backend léger

- `mastery/views/summary_helpers.py`
    - `_build_fitting_kpis`
    - `_build_doctrine_kpis`

### Templates

- `mastery/templates/mastery/partials/_summary_status_kpi_cards.html`
- `mastery/templates/mastery/partials/_summary_status_kpi_nav_cards.html`
- `mastery/templates/mastery/summary_list_view.html`

### Tests

- `mastery/tests/test_views.py`

## 7.4 Décisions d’implémentation recommandées

- Ajouter `characters_total` au payload KPI plutôt que de recalculer ad hoc en template.
- Afficher le KPI sous forme ratio : `flyable_now_characters / characters_total`.
- Conserver `Flyable now (players)` en entête/badge contextuel, pas dans les cartes KPI detail.

## 7.5 Checklist d’implémentation détaillée

- [x] Ajouter `characters_total` dans `_build_fitting_kpis()`.
- [ ] Calcul recommandé : somme des buckets characters, pour rester cohérent avec l’état réellement affiché.
- [x] Ajouter `characters_total` dans `_build_doctrine_kpis()`.
- [x] Vérifier que `flyable_now_characters <= characters_total` dans tous les cas.
- [x] Mettre à jour `_summary_status_kpi_cards.html` pour afficher la carte supplémentaire.
- [x] Mettre à jour `_summary_status_kpi_nav_cards.html` pour afficher le KPI supplémentaire dans les cartes de
  navigation doctrine → fitting.
- [x] Mettre à jour `summary_list_view.html` pour ajouter une colonne `Flyable now (characters)`.
- [x] Ajuster le `colspan` de la ligne vide dans `summary_list_view.html`.
- [x] Vérifier la lisibilité responsive des cartes KPI (grille 6 colonnes en desktop, wrap contrôlé en mobile/tablette).
- [ ] Ne pas modifier `_summary_status_headers.html` sauf si la décision finale change la structure des colonnes
  buckets.

## 7.6 Checklist de tests à écrire / adapter

- [x] Ajouter/adapter un test unitaire de KPI pour vérifier `characters_total`.
- [ ] Ajouter un test de rendu ou de contexte sur `summary_list_view` pour vérifier la présence de la nouvelle colonne.
- [ ] Ajouter un test de rendu sur `_summary_status_kpi_cards.html` / vue qui l’utilise, si une assertion textuelle est
  déjà pratiquée dans la suite.
- [ ] Ajouter un test de rendu sur `_summary_status_kpi_nav_cards.html` ou la vue doctrine detail correspondante.

## 7.7 Checklist i18n / docs

- [x] Ajouter les nouvelles chaînes (`Flyable now (characters)`) aux catalogues `en` et `fr_FR`.
- [x] Ajouter une entrée `Changed` ou `Added` dans `CHANGELOG.md` sous `Unreleased`.

## 7.8 Critères d’acceptation du lot B

- [x] Le KPI characters est visible dans les cartes summary/detail et dans la liste doctrine.
- [x] Le KPI players reste visible via l’entête contextuel/badge (`members have a flyable alt`).
- [ ] Les ratios affichés sont compréhensibles sans calcul mental.
- [ ] Aucun template summary n’a de structure cassée (headers, colspan, wrapping).

---

## 8) Checklist d’implémentation - Lot C

## 8.1 But du lot

Exploiter la donnée clone-grade déjà persistée en base (`SdeCloneGradeSkill`) pour :

- afficher l’état Alpha/Omega de chaque skill dans l’éditeur,
- calculer les KPI de compatibilité Alpha (required/recommended),
- garantir une logique déterministe basée sur `cloneGrades.yaml` (et non sur `TypeDogma`).

## 8.2 Hors périmètre du lot

- Pas de nouvelle source de vérité SDE.
- Pas de refonte des écrans hors preview/editor KPI.
- Pas d’usage de `TypeDogma`/`1047` pour la décision métier.

## 8.3 État de départ déjà implémenté (prérequis acquis)

- Import SDE clone grades en base :
    - modèle `mastery/models/sde_clone_grade_skill.py` (`SdeCloneGradeSkill`),
    - migration `0014_sdeclonegradeskill`.
- Pipeline d’import unifié :
    - `SdeMasteryImporter.import_clone_grades(...)`,
    - `SdeMasteryImporter.clone_grade_skill_caps(...)`,
    - `import_sde_masteries` + `update_sde_masteries` chargent `cloneGrades.yaml`.
- Fallback déploiement :
    - backfill automatique quand la version SDE est à jour mais que `SdeCloneGradeSkill` est vide.

## 8.4 Fichiers / symboles impactés pour le lot C fonctionnel

### Services / logique métier

- `mastery/services/doctrine/doctrine_skill_service.py`
    - `DoctrineSkillService.preview_fitting`

### Helpers de vue / KPI

- `mastery/views/common.py`
    - `_group_preview_skills`
    - `_build_fitting_preview_context`
    - `_build_plan_kpis`

### Lecture SDE persistée

- `mastery/models/sde_clone_grade_skill.py`
- (option recommandé) nouveau helper de lecture sous `mastery/services/sde/` pour éviter de dupliquer le mapping.

### Templates

- `mastery/templates/mastery/partials/fitting_skills_editor.html`

### Tests

- `mastery/tests/test_services.py`
- `mastery/tests/test_views.py`

## 8.5 Règle métier de référence à appliquer

Pour chaque skill (`typeID`) et niveau cible (`required_level` / `recommended_level`) :

- si le skill n’existe pas dans `SdeCloneGradeSkill` -> `requires_omega = True`,
- si `max_alpha_level >= niveau_cible` -> `requires_omega = False`,
- si `max_alpha_level < niveau_cible` -> `requires_omega = True`.

Notes :

- `max_alpha_level == 5` => full Alpha,
- le statut dépend du niveau demandé, donc un même skill peut être Alpha en required et Omega en recommended,
- pas de statut `Unknown` dans la logique standard cloneGrades (absence => Omega-only).

## 8.6 Checklist d’implémentation détaillée

- [x] Introduire un composant de lecture des caps Alpha depuis `SdeCloneGradeSkill` (cache in-memory recommandé).
- [x] Exposer une API explicite de résolution clone-state par `(skill_type_id, target_level)`.
- [x] Enrichir `DoctrineSkillService.preview_fitting()` :
    - [x] `required_requires_omega`,
    - [x] `recommended_requires_omega`,
    - [x] champ de synthèse `requires_omega` selon le mode affiché.
- [x] Propager ces champs dans `_group_preview_skills()` sans perte.
- [x] Étendre `_build_plan_kpis(active_rows)` :
    - [x] `required_alpha_compatible`,
    - [x] `recommended_alpha_compatible`,
    - [x] `required_omega_skill_count`,
    - [x] `recommended_omega_skill_count`.
- [x] Injecter ces KPI dans `_build_fitting_preview_context()`.
- [x] Mettre à jour `fitting_skills_editor.html` :
    - [x] badge skill `Alpha` / `Omega` (pas d’état `Unknown`),
    - [x] afficher les symboles grecs `α` / `ω` dans les badges (avec libellé accessible). Symbole Oméga en MAJUSCULE.
    - [x] placer les badges dans les colonnes `Req` et `Rec`,
    - [x] factoriser via un composant template réutilisable de badge clone-grade,
    - [x] cards plan requis/recommandé.
- [x] Vérifier que skills manuels, overrides et blacklists suivent la même logique de calcul.

## 8.7 Checklist de tests à écrire / adapter

### Service / mapping clone grades

- [x] Test de lecture `SdeCloneGradeSkill` -> cap alpha par skill.
- [x] Test résolution par niveau cible :
    - [x] absent en table => Omega,
    - [x] cap >= niveau => Alpha,
    - [x] cap < niveau => Omega.

### Preview / contexte

- [x] Test `DoctrineSkillService.preview_fitting()` avec skills partiellement Alpha (`cap < 5`).
- [x] Test `_group_preview_skills()` (propagation des champs clone-state).
- [x] Test `_build_plan_kpis()` pour required/recommended avec mix Alpha/Omega.
- [x] Test `_build_fitting_preview_context()` (KPI exposés).

### Template

- [x] Test de rendu badges `Alpha` / `Omega`.
- [ ] Test de rendu des cards `Alpha compatible` (required/recommended).

## 8.8 Checklist de validation manuelle

- [ ] Ouvrir un fitting avec skills de base + spécialisations T2.
- [ ] Vérifier qu’un même skill peut être Alpha en required et Omega en recommended selon le niveau.
- [ ] Vérifier badges et KPI lors d’un override de niveau.
- [ ] Vérifier badges et KPI avec skills manuels / blacklists.
- [ ] Vérifier qu’aucune décision n’utilise `TypeDogma` (consistance avec clone grades).

## 8.9 Checklist i18n / docs

- [x] Ajouter/valider chaînes `Alpha`, `Omega`, `Alpha compatible`, libellés KPI associés.
- [x] Mettre à jour `CHANGELOG.md` (`Changed`/`Added`) pour la partie fonctionnelle du lot C.
- [x] Mettre à jour ce document en marquant C-prérequis déjà en place + C-fonctionnel livré.

## 8.10 Critères d’acceptation du lot C

- [x] Chaque skill du preview expose un clone-state cohérent avec `SdeCloneGradeSkill` et le niveau cible.
- [x] Les KPI required/recommended reflètent correctement les restrictions Alpha/Omega.
- [x] Aucune heuristique `TypeDogma`/`1047` n’est utilisée dans la décision métier.
- [x] L’UI réutilise le même composant de badge clone-grade en colonnes `Req`/`Rec` et dans les cards KPI
  (Alpha bleuté, Omega doré).
- [ ] Le comportement est couvert par des tests service + vue/template.

---

## 9) Définition of done globale pour la version 0.2.2

Un agent qui clôture un lot doit pouvoir cocher **tous** les points suivants pour son lot :

- [ ] lecture des fichiers de contexte listés en section 5,
- [ ] implémentation limitée au périmètre du lot,
- [ ] tests ciblés ajoutés/adaptés,
- [ ] exécution d’au moins la suite ciblée du lot,
- [ ] `makemigrations --check --dry-run` propre,
- [ ] mise à jour i18n si nouvelles chaînes,
- [ ] `CHANGELOG.md` mis à jour sous `Unreleased`,
- [ ] validation manuelle du comportement visible.

---

## 10) Résumé décisionnel final

- **Lot A** : bug confirmé, périmètre plus large que la seule summary view ; il faut corriger le scope dans les helpers
  summary **et** dans le chemin pilot detail/export.
- **Lot B** : faible risque, mais à faire proprement avec un `characters_total` explicite et une mise à jour cohérente
  des
  templates.
- **Lot C** : les prérequis data sont désormais en place (clone grades persistés + backfill). Le lot restant est
  l’intégration applicative preview/UI/KPI basée sur `SdeCloneGradeSkill`.

Ce document peut désormais servir de base de ticket ou de lot de travail autonome pour plusieurs agents distincts.

---

## Alpha/Omega Skill Restriction System

### Encodage dans `cloneGrades.yaml`

La source de vérité des restrictions Alpha/Omega n’est pas un attribut dogma, mais le fichier SDE `cloneGrades.yaml`.

Structure observée :

```yaml
1:
  name: Alpha Caldari
  skills:
    - typeID: 3307
      level: 4
```

- la clé racine est un `gradeID`,
- chaque grade contient une liste `skills`,
- chaque entrée `skills` porte un `typeID` et un `level`,
- `level` représente le **niveau maximum entraînable par un clone Alpha**.

Les 4 grades Alpha sont redondants pour cette logique : les `typeID` et les caps `level` sont identiques. On peut donc
traiter le grade `1` comme source canonique et produire une map `typeID -> maxAlphaLevel`.

### Logique décisionnelle complète

Pour n’importe quel `typeID` de compétence :

1. si le `typeID` est absent de `cloneGrades.yaml` → **Omega-only**,
2. si le `typeID` est présent avec `level = N < 5` → niveaux `1..N` accessibles Alpha, niveaux `N+1..5` Omega,
3. si le `typeID` est présent avec `level = 5` → compétence **pleinement accessible Alpha**.

### Statut de l’attribut dogma `1047`

L’attribut dogma `canNotBeTrainedOnTrial` (`1047`) existe bien dans la SDE et dans la base dev locale, mais il doit être
traité comme **legacy / hint UI** uniquement.

- il ne couvre pas tous les skills,
- il ne permet pas à lui seul d’exprimer des caps Alpha par niveau,
- il peut entrer en contradiction avec `cloneGrades.yaml`, qui doit donc toujours primer.

Conséquence : **ne pas utiliser `1047` pour la logique de restriction Alpha/Omega**.

### Loader SDE existant dans ce codebase

Le loader YAML existant est `mastery/services/sde/importer.py`, classe `SdeMasteryImporter`.

Fonctionnement actuel :

- `download()` télécharge l’archive SDE YAML officielle,
- `extract_yaml(zip_file, filename)` parcourt `zip_file.namelist()` et parse le premier fichier finissant par le nom
  demandé via `yaml.safe_load`,
- la commande `mastery/management/commands/import_sde_masteries.py` charge `masteries.yaml`, `certificates.yaml` et
  `cloneGrades.yaml`,
- la tâche `mastery/tasks.py::update_sde_masteries` suit exactement le même flux.

Le point d’extension est désormais intégré **dans** ce loader : `cloneGrades.yaml` est traité dans
`SdeMasteryImporter` et persisté en `SdeCloneGradeSkill`.

### Fichiers SDE concernés dans l’archive

Chemins constatés dans l’archive YAML actuelle :

- `cloneGrades.yaml` — **source de vérité à charger pour la logique Alpha/Omega**,
- `typeDogma.yaml` — fichier legacy/référence possible autour de `1047`, **à ne pas utiliser pour la logique de
  restriction**.

Le codebase actuel charge déjà :

- `masteries.yaml`,
- `certificates.yaml`,
- `cloneGrades.yaml`.

### Intégration actuelle et prochaine étape

Intégration actuelle (faite) :

- `cloneGrades.yaml` est importé/persisté via l’importeur existant,
- la map canonique est construite dans `SdeMasteryImporter.clone_grade_skill_caps(...)`,
- fallback auto pour les instances déjà à jour SDE mais sans rows clone grades.

Prochaine étape (lot C fonctionnel) : brancher cette donnée persistée dans le preview/editor/KPI.

