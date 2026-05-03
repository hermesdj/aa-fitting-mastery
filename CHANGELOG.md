# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

## [0.2.2] - 2026-05-03

### Added

- Add database migration `0014_sdeclonegradeskill` to store canonical Alpha max skill levels by skill type.
- Add `mastery/services/summary_cache.py` with `get_cached_progress`, `set_cached_progress`, `invalidate_progress_cache_for_skillset`, and `get_skillset_cache_version` utilities.
- Add `MASTERY_SUMMARY_PROGRESS_CACHE_TTL` setting (default: 600 seconds; set to 0 to disable P3 cache).
- Add P3 instrumentation bucket `p3_metrics.shared_progress_cache` (cache hits, misses, writes, stale fallbacks, hit ratio) visible in the Summary Debug Metrics admin page.
- Add translated clone-grade tooltip copy (`Alpha clone compatible` / `Requires Omega clone`) to the unified badge partial and locale catalogs.

### Changed

- Rework doctrine/fitting summary KPI cards to focus on character-level readiness in a single responsive row: remove the duplicated `Flyable now (players)` card from detail KPI cards and keep `Flyable now (characters)` ratio alongside status buckets.
- Keep player-level flyable information in contextual headers (`X/Y members have a flyable alt`) for doctrine and fitting detail views.
- Update Lot B analysis/checklists in `docs/_0_2_2_analysis.md` to match the implemented UI behavior.
- Persist SDE `cloneGrades.yaml` data in database during SDE imports (same flow as `masteries.yaml` and `certificates.yaml`) through new model `SdeCloneGradeSkill`.
- Add automatic fallback/backfill: if an instance is already on the latest SDE version but clone-grade rows are missing, command/task now run import instead of skipping.
- Complete Lot C Alpha/Omega integration across the fitting skill editor and member-facing pilot views: compute clone-grade eligibility per skill row (`required_requires_omega`, `recommended_requires_omega`, `requires_omega`), expose plan-level Alpha compatibility KPIs, and reuse a unified clone-grade badge across editor, preview, pilot detail, and pilot index pages.
- Show recommended-plan clone compatibility directly on pilot-facing fitting titles and only mark Omega-required target levels in missing-skill lists and gap modals.
- Replace the pilot-index text badge (`At least one pilot can fly` / `Training required`) with the clone-grade badge to reduce visual noise in doctrine rows.
- Redesign the Summary Debug Metrics page into a KPI-oriented layout with grouped source tabs, nested snapshot tabs, human-readable timestamps, visual `Nouveau` / `Ancien` snapshot cues, and bounded snapshot retention per source instead of a shared global cap.
- Use compact Greek symbols (`α` / `ω`) in clone-grade badges while keeping accessible labels and translated tooltips for screen readers and hover UX.
- Implement P3 shared inter-request progress cache: doctrine summary views now cache pilot×skillset progress results in Django's cache backend (default TTL 10 min, configurable via `MASTERY_SUMMARY_PROGRESS_CACHE_TTL`), invalidated automatically on skillset regeneration.

### Fixed

- Fix `VariableDoesNotExist` on the Summary Debug Metrics page when partial snapshots omit `progress_cache_misses`.
- Fix repeated dark-mode contrast issues on Summary Debug Metrics cards, headers, and vertical navigation pills.
- Fix clone-grade badge styling drift outside the fitting editor by making the unified badge partial carry its final Alpha/Omega colors directly.
- Fix migration drift on `SdeCloneGradeSkill` by explicitly naming the `max_alpha_level` index to match the generated migration state.
- Fix full-plugin regression coverage for `PilotProgressService.build_for_character(...)` request cache reuse by mocking Alpha cap loading in the service test.

### i18n

- Add `Flyable now (characters)` to `en` and `fr_FR` locale catalogs.
- Add translated clone-grade tooltip strings to `en` and `fr_FR` catalogs and compile updated `django.mo` files.

### Tests

- Verify migration state:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python -m django makemigrations --check --dry-run mastery` (**No changes detected in app 'mastery'**).
- Run focused clone-grade/service regression coverage:
  - `python -u runtests.py mastery.tests.test_pilot_progress_service_lot3 -v 2` (**77 passed**).
- Run focused pilot/summary/view regression suite:
  - `python -u runtests.py mastery.tests.test_views -v 1` (**129 passed**).
- Run full plugin suite:
  - `python -u runtests.py mastery -v 1` (**350 passed**).
- Run lint quality gate:
  - `pylint --load-plugins pylint_django mastery` (**10.00/10**).
- Build release artifacts:
  - `flit build` (validated in the project virtualenv / WSL release environment).

### Upgrade Notes

- Update package:
  - `pip install -U aa-fitting-mastery==0.2.2`
- Apply database changes:
  - `python manage.py migrate`
- If your instance was already marked as up to date on SDE before this change, run one import cycle to ensure clone-grade backfill is present:
  - `python manage.py import_sde_masteries`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services:
  - web service
  - Celery worker(s)
  - Celery beat

## [0.2.1] - 2026-04-28

### Added

- Add optional corporation/alliance scoping fields to all Secure Groups mastery skill-plan filters:
  - `MasteryFittingStatusFilter`
  - `MasteryFittingProgressFilter`
  - `MasteryDoctrineReadinessFilter`
  - `MasteryFittingEliteFilter`
- Add database migration `0013_masterydoctrinereadinessfilter_alliances_and_more` to persist the new M2M scope fields.
- Add regression tests for entity-scope behavior and same-character matching semantics in `mastery/tests/test_secure_groups.py`.

### Changed

- Enforce "same character" matching in Secure Groups filters: entity scope (corporation/alliance) and skill-plan condition are now evaluated on the same character.
- Update Secure Groups admin configuration to expose `corporations` and `alliances` with `filter_horizontal` on all mastery skill-plan filters.

### Tests

- Verify migration state:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python -m django makemigrations --check --dry-run mastery` (**No changes detected**).
- Run focused Secure Groups suite:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python -u runtests.py mastery.tests.test_secure_groups -v 2` (**34 passed**).
- Run full plugin suite:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python -u runtests.py mastery -v 2` (**307 passed**).
- Run lint quality gate:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local pylint --load-plugins pylint_django mastery` (**10.00/10**).

### Upgrade Notes

- Update package:
  - `pip install -U aa-fitting-mastery==0.2.1`
- Apply database changes:
  - `python manage.py migrate`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services:
  - web service
  - Celery worker(s)
  - Celery beat

## [0.2.0] - 2026-04-22

### Added

- Add optional Secure Groups hook registration in `mastery/auth_hooks.py` via `@hooks.register("secure_group_filters")` when `securegroups` is installed, so mastery smart filters are discoverable by allianceauth-secure-groups.
- Add readable labels for secure-groups FK selectors by implementing `__str__` on `FittingSkillsetMap` and `DoctrineSkillSetGroupMap`.
- Add focused regression tests for Secure Groups integration and model labels (`test_secure_groups.py`, `test_model_labels.py`).

### Changed

- Refactor optional app detection to the Alliance Auth pattern using `apps.is_installed("securegroups")` through `securegroups_installed()` in `mastery/app_settings.py`.
- Replace broad import-time `try/except ImportError` guards in `mastery/apps.py`, `mastery/admin.py`, and `mastery/models/__init__.py` with explicit feature gates.
- Harden secure-group character resolution to use Member Audit ownership lookups based on `Character.objects.owned_by_user(...)` and `eve_character__character_ownership` joins.
- Keep `minimum_status="can_fly"` evaluation strict while adding a defensive fallback to mastery progress (`can_fly` + `required_pct == 100`) to mitigate observed Member Audit false negatives on required-skill checks.

### Fixed

- Fix Smart Group filters returning empty results because Member Audit character lookups were using invalid relationship paths.
- Fix Smart Group admin UX showing opaque FK labels like `FittingSkillsetMap object (1)` by exposing fitting/doctrine names.
- Fix inconsistent secure-group audit behavior for `can_fly` and doctrine readiness when Member Audit required-skill checks are stale or misclassified.
- Fix doctrine coverage audience-group membership so a user is included when any owned character matches the configured corporation/alliance scope, instead of implicitly depending on the main character.
- Fix summary/detail readiness aggregation to keep evaluating all owned characters for an eligible user, preserving alt-based coverage and best-character selection in doctrine/fitting reports.

### Tests

- Run full plugin suite:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python runtests.py mastery -v 2` (**302 passed**).
- Run focused summary/view regression suite:
  - `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python runtests.py mastery.tests.test_views -v 2` (**97 passed**).
- Run lint quality gate:
  - `pylint --load-plugins pylint_django mastery` (**10.00/10**).
- Add focused regression coverage in `mastery/tests/test_views.py` for summary audience matching via alts, owned-character grouping, and best-character selection in doctrine coverage.

### Upgrade Notes

- Update package:
  - `pip install -U aa-fitting-mastery==0.2.0`
- Apply database changes (adds secure group filters via migration `0012_masterydoctrinereadinessfilter_and_more`):
  - `python manage.py migrate`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services:
  - web service
  - Celery worker(s)
  - Celery beat

## [0.1.9] - 2026-04-21

### Added

- Keep compiled locale catalogs in version control by explicitly allowing `mastery/locale/**/LC_MESSAGES/*.mo` in `.gitignore`.

### Changed

- Include compiled translation files (`django.mo`) in release artifacts so production instances can immediately serve `fr_FR` strings without requiring a post-deploy `compilemessages` run.

### Upgrade Notes

- Update package:
  - `pip install -U aa-fitting-mastery==0.1.9`
- No database migration, settings change, or Celery schedule update is required for this release.
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services:
  - web service
  - Celery worker(s)
  - Celery beat

## [0.1.8] - 2026-04-21

### Added

- Show doctrine priority directly in `Manage Skill Plans` doctrine list with the same visual badge scale used across mastery pages.

### Changed

- Harden i18n usage in JavaScript-driven templates by replacing fragile inline `{% translate %}` string injections with pre-translated template variables escaped for JS (`escapejs`), preventing locale-specific runtime syntax errors.
- Improve fitting/summary pilot popovers to consistently render translated status labels (Elite / Almost elite / Can fly / Almost fit / Needs training) from status buckets.
- Extend doctrine list context building so every doctrine row exposes its configured priority (`0` fallback when not initialized).
- Complete `fr_FR` translations for priority labels/tooltips and priority update feedback messages.

### Fixed

- Hide the `Approve` button in the fitting skill plan editor when the current plan is already approved.
- Fix Django template pluralization syntax in `fitting_skills_editor.html` (`blocktranslate count ... {% plural %}`), resolving `TemplateSyntaxError` at runtime.
- Fix copy behavior for long recommended plans in the fitting skill editor by moving copy payload from large `data-*` attributes to a dedicated hidden source element and adding a robust clipboard fallback.
- Fix copy feedback UX in both fitting and pilot views: buttons now reliably display a temporary `Copied!` state and restore their default labels.
- Fix pilot copy button initial empty-label edge case by enforcing explicit default label sources (`aria-label` / `data-copy-default-label`) and defensive JS fallback initialization.

### Tests

- Run full plugin test suite: `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python runtests.py mastery -v 2` (**257 passed**).
- Run focused pilot view regression suite: `python runtests.py mastery.tests.test_views.TestPilotViews -v 2` (**14 passed**).
- Run lint quality gate: `pylint --load-plugins pylint_django mastery` (**10.00/10**).
- Run duplicate-code audit: `pylint --load-plugins pylint_django --disable=all --enable=duplicate-code mastery/views mastery/services mastery/tests` (expected wrappers reported between `mastery/views/common.py` and `mastery/views/fitting.py`).

### Upgrade Notes

> ⚠️ **A database migration must be run for this update.**

- Update package:
  - `pip install -U aa-fitting-mastery`
- Apply database changes (adds priority fields on doctrine/fitting map models via migration `0011_priority_fields`):
  - `python manage.py migrate`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services so Django code and Celery tasks reload:
  - web service
  - Celery worker(s)
  - Celery beat

## [0.1.7] - 2026-04-17

### Fixed

- Fix intermittent `IntegrityError` (MySQL FK constraint) when regenerating a fitting skill plan that has already been evaluated by `memberaudit`. Before deleting the old `SkillSetSkill` rows the service now removes the corresponding M2M rows in both `CharacterSkillSetCheck.failed_required_skills` and `CharacterSkillSetCheck.failed_recommended_skills` within the same atomic transaction.

### Tests

- Refactor `test_generate_for_fitting_creates_only_non_blacklisted_entries_and_syncs` to mock `CharacterSkillSetCheck` and use the new shared `_make_generate_service` / `_make_preview` helpers.
- Add `test_generate_for_fitting_clears_m2m_fk_refs_before_deleting_skills`: verifies that both M2M through-table deletions are issued (in order) before the skillset `delete()` call.
- Add `test_generate_for_fitting_skips_m2m_cleanup_when_no_existing_skills`: verifies no M2M query is issued when the skillset is already empty.

### Upgrade Notes

- Update package:
  - `pip install -U aa-fitting-mastery==0.1.7`
- No database migration, no new settings, no Celery schedule changes required.
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services:
  - web service
  - Celery worker(s)
  - Celery beat

## [0.1.6] - 2026-04-17

### Added

- Add active-group tab persistence in the fitting skills editor: the currently open skill group is stored in the URL as `?active_group=<key>` and restored on page load, surviving POST-redirect cycles.
- Add `active_group` hidden input injection into every editor form so that POST actions (blacklist, recommend, manual add/remove, apply suggestion, …) carry the active tab back through the redirect via `_finalize_fitting_skills_action()` in `mastery/views/common.py`.

### Changed

- Remove `FittingSkillOverride` model (`mastery/models/fitting_skill_override.py`): blacklisted override rows are preserved by migration `0010` (see **Upgrade Notes**), which copies them into the existing `FittingSkillControl` table before dropping the old model. All references to `FittingSkillOverride` have been removed from `models/__init__.py`.
- Filter out doctrines with no configured fittings from the Doctrine Summary list view (`summary_list_view`) so that only actionable entries are shown to the user.

### Fixed

- Fix active group tab being lost after every form action in the fitting skills editor.
- Fix summary list showing unconfigured / skeleton doctrine entries that have zero fitted doctrines.

### Tests

- Extend `test_common_helpers_extra.py` with coverage for `active_group` injection and URL rewrite in `_finalize_fitting_skills_action`.
- Extend `test_views.py` with summary list filtering and active-group redirect preservation.

### Upgrade Notes

> ⚠️ **A database migration must be run for this release.**

- Update package:
  - `pip install -U aa-fitting-mastery==0.1.6`
- Apply database changes (removes legacy `FittingSkillOverride` table after migrating blacklisted rows to `FittingSkillControl`):
  - `python manage.py migrate`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services so Django code and Celery tasks reload:
  - web service
  - Celery worker(s)
  - Celery beat
- No new permissions, settings, or Celery schedule entries are required for this release.

## [0.1.5] - 2026-04-17

### Added

- Add `MASTERY_DEFAULT_SKILLS` setting (`app_settings.py`) to inject a global list of baseline required skills (e.g. Thermodynamics I) into every generated fitting plan. Each entry is a `{"type_id": …, "required_level": …}` dict; invalid or out-of-range entries are silently skipped with a warning log.
- Add per-fitting approval workflow on `FittingSkillsetMap`: new `status` field (`in_progress` / `not_approved` / `approved`), `approved_by`, `approved_at`, `modified_by`, `modified_at` (migration `0009`).
- Add `FittingApprovalService` (`mastery/services/fittings/approval_service.py`) with `approve()`, `mark_modified()` and `mark_status()` helpers. The service is wired into `deps.py` and injected into `DoctrineSkillService`.
- Add `update_fitting_approval_status_view` view and URL (`fitting/<id>/skills/approval/`) to change the approval state of a fitting skill plan.
- Add approval workflow controls to the fitting skills editor template (approve / in-progress / not-approved buttons) with actor/timestamp audit display.
- Add `normalize_default_skill_map()` and `merge_skill_maps()` helpers to `mastery/services/skill_requirements.py` to validate and merge default skill injections.
- Add `_require_post_and_resolve()` helper in `mastery/views/fitting.py` to centralise POST validation and context resolution, eliminating repeated boilerplate across view handlers.
- Add `_get_user_display()` and `_build_actor_display()` helpers in `mastery/views/common.py` for consistent actor rendering across templates.
- Add approval metadata fields (`approval_status`, `approval_status_label`, `approval_status_badge_class`, `approved_by_actor`, `modified_by_actor`, …) to the fitting preview context built by `_build_fitting_preview_context()`.
- Add `_fitting_preview_modal.html` partial for the copy-plan modal dialog.
- Add `active_skills` and `grouped_has_active_skills` template filters in `mastery/templatetags/skill_render.py`.
- Add `test_refactor_helpers.py` covering fitting context resolution, POST validation, group-controls unsupported action, manual skill not-found/removal, and approval guard paths.
- Add `test_common_helpers_extra.py` covering `_get_user_display`, `_build_actor_display`, empty AJAX messages, bad-request helpers, finalize flow, duration formatting, and filtered suggestion application.
- Add `test_sde_importer_and_command.py` covering `SdeMasteryImporter` (YAML extraction, certificate import, mastery rebuild, dry-run) and the `import_sde_masteries` management command.
- Add lot 3 test file `test_pilot_progress_service_lot3.py` covering all major uncovered paths in `PilotProgressService` (see Tests section).

### Changed

- Every fitting plan regeneration or mutation (blacklist toggle, recommended-level change, group-controls, manual skill add/remove, suggestion apply, mastery update, doctrine sync) now calls `FittingApprovalService.mark_modified()` to record `modified_by` / `modified_at` and reset the status to `in_progress`.
- `DoctrineSkillService.generate_for_fitting()` and `generate_for_doctrine()` now accept optional `modified_by` and `status` parameters that are forwarded to the approval service after plan generation.
- `DoctrineMapService.sync()` now accepts `modified_by` and `status` parameters and forwards them to `generate_for_doctrine()`.
- `sync_doctrine` and `update_doctrine_mastery` views now pass `request.user` and `IN_PROGRESS` to the sync call.
- Improve grouped summary scope propagation across Summary → Fitting → Pilot → Export flows for `group_id`, `activity_days`, and `include_inactive`.
- Update grouped pilot detail layout to display `activity_days` next to the character filter.
- Make `activity_days` configurable directly from the Doctrine Summary detail view.
- Extend `_approved_fitting_maps()` / `_is_approved_fitting_map()` helpers to `mastery/views/summary_helpers.py` and re-export them via `mastery/views/common.py`.
- Improve pilot and export views to check fitting plan approval status before serving skill plans to non-manager users.
- Consolidate duplicated view patterns (POST guard, context resolution, doctrine-map creation) across fitting view handlers with no user-facing API change.
- Update `FittingSkillsetMap.objects` queries across views to `select_related("approved_by", "modified_by")` where approval display data is needed.

### Fixed

- Fix doctrine fitting table approval column: approved plans now render the approver actor and timestamp instead of always showing the "No activity recorded yet" fallback.
- Fix grouped-scope navigation edge cases (invalid `group_id`, scope persistence across pages).
- Fix `_build_fitting_preview_context()` to forward the resolved fitting map into the preview instead of silently ignoring it when passed as an argument.

### Tests

- New test files: `test_refactor_helpers.py`, `test_common_helpers_extra.py`, `test_sde_importer_and_command.py`, `test_pilot_progress_service_lot3.py`.
- Extend `test_services.py` with `TestSkillRequirementsHelpers` for `normalize_default_skill_map`/`merge_skill_maps` and `TestFittingApprovalService` for `approve`/`mark_modified` workflow transitions.
- Extend `test_views.py` with grouped scope propagation, export behavior, approval state transitions, doctrine/fitting mutations, and `_approved_fitting_maps`/`_is_approved_fitting_map`/`_missing_skillset_error` helpers.
- `pilot_progress_service.py` coverage raised from **48 % → 90 %** (lot 3).
- Total measured coverage: **80 %**.
- `pylint --load-plugins pylint_django mastery`: **10.00/10**.
- Run full suite: `DJANGO_SETTINGS_MODULE=testauth.settings_aa4.local python runtests.py mastery` (251 tests, all passing).

### Upgrade Notes

- Update package:
  - `pip install -U aa-fitting-mastery==0.1.5`
- Add the new optional setting to `local.py` (leave empty if not used):
  - `MASTERY_DEFAULT_SKILLS = []`
- Apply database changes (adds approval workflow fields to `FittingSkillsetMap`):
  - `python manage.py migrate`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services so Django code and Celery tasks reload:
  - web service
  - Celery worker(s)
  - Celery beat
- No new permissions or Celery schedule entries are required for this release.

## [0.1.4] - 2026-04-16

### Added

- Add reusable pilot status bucket helpers and shared template partials for status headers, KPI cards, fit header actions and pilot popovers.
- Add common skill requirement constants/helper module used by progression and extraction flows.

### Changed

- Rework Skill Mastery and Doctrine Summary templates with richer KPI/readiness presentation and unified table-header styling across pages (including dark mode consistency).
- Improve pilot and summary view composition by centralizing status bucket usage in both backend view code and frontend components.
- Update pilot detail filter labels to include matching character counts and only expose non-empty filter options.

### Fixed

- Fix `pilot_fitting_detail` character filtering by automatically falling back from `can_fly_now` to `all` when no pilot matches the default filter.
- Stop forcing focused pilots into filtered results when they are not eligible for the active filter.
- Fix sticky `Character readiness` table header transparency on scroll and align its appearance with the shared table-header styling.

### Tests

- Extend pilot and summary view test coverage for filter fallback behavior, selected-pilot visibility, and updated KPI/status rendering paths.
- Add/adjust regression tests for pilot progress service updates and new status-bucket based logic.

## [0.1.3] - 2026-04-15

### Changed

- Improve Doctrine Summary performance for large groups by reusing request-scoped caches for skillset skills, character skills and dogma lookups across repeated progress calculations.
- Reduce repeated pilot/summary view work by sharing cached progress-loading context across doctrine, fitting and pilot readiness pages.

### Tests

- Add regression coverage to verify that repeated progress builds reuse the new request cache instead of reloading the same skill data multiple times.

## [0.1.2] - 2026-04-15

### Fixed

- Fix progress bars rendering as `0%` in non-English locales by forcing unlocalized numeric values in CSS width styles.
- Improve Skill Mastery filtering by excluding doctrines/fittings that are not yet configured with a generated skill plan.

### Changed

- Improve pilot/summary page load times by avoiding export-line generation in progress computations when not needed.
- Add quick access buttons in fitting skill plan management to open the related fitting and doctrine pages.

## [0.1.1] - 2026-04-15

### Fixed

- Avoid `IntegrityError` when generating doctrine maps if a `memberaudit` `SkillSetGroup` with the same name already exists.
- Restore tooltip behavior on first load in fitting skills pages by hardening tooltip initialization timing.

## [0.1.0] - 2026-04-15

### Added

- Initial public release of the Fitting Mastery plugin for Alliance Auth.
- Doctrine skill plan generation based on `fittings` doctrines and fittings.
- Mastery recommendation merge using imported EVE SDE certificates/masteries.
- Pilot-facing readiness views and skill plan export helpers.
- Summary/audience views to review readiness across selected member scopes.
- Skill control tooling: blacklist, manual skill overrides, and recommendation overrides.
- SDE import tooling with management command (`import_sde_masteries`) and Celery update task (`update_sde_masteries`).
