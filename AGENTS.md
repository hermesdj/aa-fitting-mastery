# AGENTS.md (FR)

But : guide concis et actionnable pour un agent IA qui prend en charge le plugin aa-fitting-mastery.

1) Big picture (architecture rapide)
- Composants principaux
  - views/ : logique HTTP scindée par responsabilités — doctrine.py, fitting.py, pilot.py, summary.py, summary_helpers.py, common.py
  - services/ : logique métier (doctrine, fittings, pilots, sde, suggestions, skill_control, pilot_progress)
  - templates/mastery/ et templates/mastery/partials : rendu UI (fitting_skills.html, fitting_skill_preview.html, pilot_fitting_detail.html, summary_list_view.html, etc.)
  - models/ : FittingSkillsetMap, DoctrineSkillSetGroupMap, SummaryAudienceGroup, SdeVersion, etc.
  - management/commands/import_sde_masteries.py et services/sde/importer.py : téléchargement + import SDE masteries & certificates
  - tests/ : test_views.py (plein de scenarios), test_services, tests pour importer SDE
- Intégrations externes
  - dépend fortement des plugins Alliance Auth, memberaudit et fittings (ex. ItemType de SDE, Character et SkillSet dans memberaudit, Doctrine/Fitting dans fittings)
  - permissions utilisées : mastery.manage_fittings, mastery.basic_access, mastery.doctrine_summary, mastery.manage_summary_groups

2) Flux de données & décisions clés
- Génération d’un skillset pour un fitting :
  doctrine_skill_service.generate_for_fitting(doctrine_map, fitting, modified_by, status)
  → met à jour FittingSkillsetMap, synchronise skillset dans memberaudit (création / update)
- Suggestions :
  suggestion_service calcule « add/remove » par skill en fonction des modules du fit et des skill requirements.
- Calcul progression pilote :
  pilot_progress_service.build_for_character(character, skillset, include_export_lines, cache_context)
  → retourne can_fly, required_pct, recommended_pct, mode_stats (missing SP/time), missing rows, export lines.
- Status buckets : mastery/services/pilots/status_buckets.py (BUCKET_CAN_FLY, BUCKET_ELITE, ...). Utilisé partout pour filtrer/afficher.

3) Patterns et conventions du projet (spécifiques)
- Views orchestrent des services : ne mettre que la validation / orchestration dans les views ; logique métier dans services/.
- Ajax incremental UI pattern :
  - Views retournent JSON via _build_fitting_skills_ajax_response (html fragment + messages_html) pour mise à jour dynamique.
  - Les endpoints AJAX renvoient JSON quand _is_ajax_request(request) est vrai.
- Tooltips / modals :
  - Contrainte : alliance-auth n'initialise PAS globalement les tooltips pour ce plugin. Tous les tooltips du plugin utilisent data-bs-tooltip="aa-mastery".
  - Initialiser côté JS : $('[data-bs-tooltip="aa-mastery"]').tooltip(); (s'assurer d'exécuter après rendu partiel ou mutation DOM).
  - Modal bootstrap : certains plugins s'appuient sur déclarations HTML; vérifie les usages existants (partial fitting_skill_preview.html).
- Langue d’export SDE :
  - ItemType table contient colonnes name_en, name_fr_fr, name_zh_hans, etc.
  - pilot_progress_service.normalize_export_language(lang) → choisir champ name_<lang> pour l’export.
- Recommandation/mastery:
  - effective mastery: resolved via doctrine_map.default_mastery_level, override per-fitting; voir doctrine_skill_service.resolve_effective_mastery_level.
  - recommended_level ne doit jamais être < required_level (contrainte appliquée côté view/service).
- Blacklist & manual skills :
  - control_service.set_blacklist(fitting_id, skill_type_id, value)
  - control_service.add_manual_skill(...) / remove_manual_skill(...)
  - Group ops: set_blacklist_batch, set_recommended_level_batch.

4) Endpoints & payloads utiles (exemples)
- Toggle blacklist (AJAX or form POST)
  POST /fitting/<fitting_id>/blacklist/
  body: { skill_type_id: "55", value: "true" }
  server calls control_service.set_blacklist(...), regen plan, renvoie JSON fragment.
- Update recommended level single skill
  POST /fitting/<fitting_id>/skills/recommended/
  body: { skill_type_id: "55", recommended_level: "4" }
- Update group (batch)
  POST /fitting/<fitting_id>/skills/group-controls/
  body e.g. { action: "set_group_recommended", recommended_level: "4", skill_type_ids: ["55","66"] }
  actions supportées: blacklist_group, unblacklist_group, set_group_recommended, clear_group_recommended
- Add manual skill
  POST /fitting/<fitting_id>/skills/manual/add/
  body: { skill_name: "Thermodynamics", recommended_level: "1" }
- Apply suggestions
  POST /fitting/<fitting_id>/skills/apply-suggestions/
- Preview (fragment)
  GET /fitting/<fitting_id>/preview/?mastery_level=4 → rend partial/mastery/partials/fitting_skill_preview.html

5) Developer workflows / commandes (exactes)
- Tests unitaires (local) :
  - Exemples : DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local
  - Lancer tests du plugin : DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python runtests.py mastery
  - Lancer un seul test : python runtests.py mastery.tests.test_views.TestPilotViews.test_pilot_fitting_detail_view -v 2
- Coverage :
  - python -m coverage run runtests.py mastery
  - python -m coverage report
- Lint / qualité :
  - pylint --load-plugins pylint_django mastery
  - Respecter pyproject.toml / règles existantes (ne pas changer sans consentement).
- SDE import / task :
  - Management: python manage.py import_sde_masteries [--dry-run|--force]
  - Celery task: mastery.tasks.update_sde_masteries (schedule daily via cron/beat) — config: daily at 00:00 (crontab).
- CI notes :
  - CI peut échouer si DJANGO_SETTINGS_MODULE ne trouve pas testauth : fournir un test settings modulé comme les autres plugins.
- Git / release:
  - Bump __init__.py version, mettre à jour CHANGELOG.md, lancer tests + pylint, tag & push.

6) Points sensibles & bugs récurrents (repérés)
- Internationalisation numerics: progress bar widths peuvent être affectées par localisation (format numérique). Utiliser float() / str() non localisé pour CSS widths.
- Tooltip init : tooltips non initialisés au premier rendu — must run $('[data-bs-tooltip="aa-mastery"]').tooltip() après DOM inserts.
- ItemType name fields: pour exports, lire le champ name_<lang> correspondant (name_en, name_fr_fr, name_zh_hans...). Voir pilot_progress_service.resolve_itemtype_name_field.
- pilot_progress_service est volumineux & cacheable : utiliser cache_context partagé pour éviter recalculs lourds dans summary loops.
- Duplicate constants (REQUIRED_SKILL_ATTRIBUTES) : centraliser dans services/general.py ou services/skill_requirements.py.
- AJAX UI pattern: prefer fetch POST to the endpoints above and update the returned html + messages_html. Use response JSON shape:
  { "status": "ok"|"error", "html": "<fragment>", "messages_html": "<alerts>" }
- Character portraits: templatetag character_portrait_url does not accept size 24 — check usage to avoid silent failures.

7) Where to look (key files)
- Views & helpers: mastery/views/*.py and mastery/views/summary_helpers.py
- Business rules: mastery/services/* (pilot_progress_service, doctrine_skill_service, skill_control_service, suggestion_service)
- Templates: templates/mastery/fitting_skills.html, templates/mastery/partials/fitting_skill_preview.html, templates/mastery/pilot_fitting_detail.html, templates/mastery/summary_*.html
- SDE importer: mastery/services/sde/importer.py and management/commands/import_sde_masteries.py
- Tests: mastery/tests/test_views.py, mastery/tests/* (good reference for expected behaviors and edge cases)
- Models and migrations: mastery/models/*.py and relations to memberaudit SkillSet/SkillSetGroup

8) Short tasks checklist for agents (actionable)
- When editing UI behavior:
  - Ensure tooltips initialised with data-bs-tooltip="aa-mastery" after any partial render.
  - Use fetch to POST to known endpoints and update DOM using payload.html + payload.messages_html.
- When modifying exports:
  - Use pilot_progress_service.normalize_export_language(lang) → resolve ItemType name_<lang> field.
  - For export lists, expand skill levels per-level (1..N) and include prerequisites in correct order (use dogma TypeDogma lookups).
- When improving performance:
  - Reuse progress cache_context across loops in summary_helpers/_build_doctrine_summary and pilot index.
- When adding tests:
  - Mock external ORM access accordingly (see existing tests). Use runtests.py and test settings env var.

9) Minimal reproducible dev setup
- Ensure testauth (test settings) is available in PYTHONPATH or set DJANGO_SETTINGS_MODULE to an existing test settings used by other plugins.
- Run tests & linter before opening PR: runtests.py mastery ; pylint --load-plugins pylint_django mastery ; coverage run runtests.py mastery

10) Communication notes (for humans)
- If you touch pilot_progress_service: add unit tests (service-level) — it’s the most critical & heaviest file.
- Keep view methods thin; add logic in services and add tests.
- Respect existing settings keys:
  - MASTERY_DEFAULT_SKILLS (list)
  - Summary group thresholds (configurable in settings — check app_settings.py)

11) Quality gates & duplication audit notes (maintenir à jour)
- Quick quality gate before PR (PowerShell):
  - `$env:DJANGO_SETTINGS_MODULE='testauth.settings_aa4.local'; python runtests.py mastery`
  - `$env:DJANGO_SETTINGS_MODULE='testauth.settings_aa4.local'; python -m coverage run runtests.py mastery; python -m coverage report -m`
  - `pylint --load-plugins pylint_django mastery`
- Duplication audit shortcut:
  - `pylint --load-plugins pylint_django --disable=all --enable=duplicate-code mastery\views mastery\services mastery\tests`
- Current hotspots to prioritize for future coverage increase:
  - `mastery/services/pilots/pilot_progress_service.py`
  - `mastery/views/fitting.py`
  - `mastery/views/common.py`
- Last validated quality snapshot in this workspace:
  - tests: `176 passed`
  - coverage: `71%` total
  - pylint: `10.00/10`
- Intentional duplication note:
  - Some duplicated snippets reported between `mastery/views/fitting.py` and `mastery/views/common.py` are expected wrappers around shared helper flows; avoid aggressive dedup that hurts readability in endpoint handlers.

