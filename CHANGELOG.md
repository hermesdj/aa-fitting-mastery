# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

### Added

- Nothing yet.

## [0.1.4] - 2026-04-16

### Added

- Add reusable pilot status bucket helpers and shared template partials for status headers, KPI cards, fit header actions and pilot popovers.
- Add common skill requirement constants/helper module used by progression and extraction flows.

### Changed

- Rework Skill Mastery and Doctrine Summary templates with richer KPI/readiness presentation and unified table-header styling across pages (including dark mode consistency).
- Improve pilot and summary view composition by centralizing status bucket usage in both backend view code and frontend components.
- Refresh README and plugin settings documentation to cover the expanded UI and behavior.
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
