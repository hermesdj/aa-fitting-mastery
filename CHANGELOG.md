# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

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
