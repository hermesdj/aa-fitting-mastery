# AGENTS.md

## Scope and mental model
- This file is for work in `working/aa-fitting-mastery/` only. Treat other plugins as external dependencies unless a task explicitly crosses repo boundaries.
- `aa-fitting-mastery` is a Django app for Alliance Auth that bridges `fittings` and `memberaudit`: it turns doctrines/fittings into `SkillSetGroup` + `SkillSet` data, then augments them with EVE SDE masteries/certificates.
- The core flow is: doctrine -> doctrine map -> fitting map -> extracted required skills -> recommended mastery skills -> optional blacklist/suggestions.

## Read these files first
- Start with `README.md`, `pyproject.toml`, and `mastery/apps.py` for package identity and hard dependencies.
- Read `mastery/urls.py`, `mastery/views.py`, and `mastery/api.py` to see the actual UI/API surface.
- For the main business logic, read `mastery/services/doctrine/doctrine_map_service.py` and `mastery/services/doctrine/doctrine_skill_service.py`.
- Then read `mastery/services/fittings/skill_extractor.py`, `mastery/services/sde/mastery_service.py`, and `mastery/services/skills/{skill_control_service.py,suggestion_service.py}`.
- Use `mastery/models/` and `mastery/migrations/` as the source of truth for persistence shape.

## Architecture and data flow you should preserve
- `DoctrineMapService.create_doctrine_map()` creates one `memberaudit.SkillSetGroup` per `fittings.Doctrine`, stores it in `DoctrineSkillSetGroupMap`, then immediately calls `sync()`.
- `FittingMapService.create_fitting_map()` creates one `memberaudit.SkillSet` per `fittings.Fitting`, attaches it to the doctrine’s skillset group, and stores the mapping in `FittingSkillsetMap`.
- `DoctrineSkillService.generate_for_doctrine()` is the core orchestrator: it reads doctrine fittings, extracts hard requirements from `eve_sde.TypeDogma`, merges them with mastery recommendations from imported SDE data, wipes existing `skillset.skills`, bulk-creates new `SkillSetSkill` rows, then records suggestions in `FittingSkillControl`.
- Blacklist state is stored in `FittingSkillControl.is_blacklisted`; suggestion metadata also lives in `FittingSkillControl`, not in transient view state.
- `DoctrineSkillSnapshot` exists as persisted snapshot data for doctrine/fitting/skill combinations; inspect current usage before changing or deleting it.

## Project-specific conventions
- Views in `mastery/views.py` are thin and instantiate service objects at module scope. Preserve that pattern unless you have a strong reason to change initialization behavior.
- This plugin uses service classes, not fat models, for most business logic. New behavior usually belongs under `mastery/services/`, not directly in views/API handlers.
- Data creation is intentionally idempotent-ish: `filter().first()`, `create()`, and `update_or_create()` are used heavily to avoid duplicate maps/control rows.
- `mastery/api.py` is minimal right now: `toggle_blacklist` is the real mutating endpoint; `update_skill_level` currently parses JSON and returns `{"status": "ok"}` without persistence.
- `auth_hooks.py` is the navigation/URL integration point: menu entry uses `mastery.basic_access`, while management screens require `mastery.manage_fittings`.

## External dependencies and integration points
- Hard package dependencies are declared in `pyproject.toml`: `allianceauth`, `aa-memberaudit`, `fittings`, `allianceauth-app-utils`, `django-esi`, and `django-eveonline-sde`.
- `skill_extractor.py` depends on `eve_sde` dogma attributes for skill requirements; changes there can alter every generated skillset.
- SDE mastery recommendations are imported from CCP static data by `mastery/services/sde/importer.py` and exposed through `MasteryService.get_ship_skills()`.
- If a task touches installation/runtime integration, check `working/myauth/myauth/settings/local.py`: this workspace already enables `'mastery'` and schedules `mastery.tasks.import_sde_masteries` under `CELERYBEAT_SCHEDULE['update_sde_masteries']`.

## Testing and developer workflow
- `Makefile` assumes an active virtualenv; `make dev` installs editable mode and `make test` runs `tox`.
- Be careful with `tox.ini`: it expects `testauth.settings_aa4.local` and `runtests.py`, but those files are not present in this repo snapshot. Do not assume `tox` is currently runnable without adding the missing harness.
- For real validation, prefer focused checks in the integrated AA instance or targeted Django shell/management-command smoke tests over guessing from `tox.ini`.
- If you change SDE import logic, validate both the management command `python manage.py import_sde_masteries --dry-run` and the Celery task path in `mastery/tasks.py`.

