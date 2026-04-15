# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

### Added

- Nothing yet.

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

