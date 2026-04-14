# Fitting Mastery Plugin for Alliance Auth

`aa-fitting-mastery` is an [Alliance Auth](https://allianceauth.readthedocs.io/) plugin that turns doctrine fittings into actionable skill plans.

It connects your configured doctrines and fittings from the `fittings` plugin with character and skill data from `aa-memberaudit`, then provides:

- pilot readiness views for accessible doctrine fittings,
- missing required and recommended skills,
- exportable in-game skill plans,
- configurable required and recommended skill plans per fitting,
- leadership summary views for doctrine coverage.

[![release](https://img.shields.io/pypi/v/aa-fitting-mastery?label=release)](https://pypi.org/project/aa-fitting-mastery/)
[![python](https://img.shields.io/pypi/pyversions/aa-fitting-mastery)](https://pypi.org/project/aa-fitting-mastery/)
[![django](https://img.shields.io/pypi/djversions/aa-fitting-mastery?label=django)](https://pypi.org/project/aa-fitting-mastery/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Main features](#main-features)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Updating](#updating)
- [Configuration](#configuration)
- [Permissions](#permissions)
- [How it works](#how-it-works)
- [Settings](#settings)

## Overview

Fitting Mastery is designed for organizations that already manage doctrine ships in `fittings` and track character skills in `aa-memberaudit`.

The plugin adds two complementary workflows:

1. **Pilot workflow**
   - members can see which of their characters can fly a doctrine fitting,
   - inspect missing required / recommended skills,
   - export missing skills in a format suitable for EVE skill plan import.

2. **Leadership workflow**
   - doctrine managers can configure fitting skill plans,
   - review suggestions to blacklist or restore skills,
   - define summary groups across corporations and alliances,
   - view doctrine coverage for a selected audience.

Access to doctrines and fittings follows the visibility rules from the `fittings` plugin so that category restrictions are respected consistently.

## Requirements

This plugin depends on the following components:

- `fittings` — required
- `aa-memberaudit` — required
- `django-eveonline-sde` / `eve_sde` — required for ship mastery and dogma data
- Alliance Auth 4.x

> **Important**
> This plugin does **not** replace `fittings` or `aa-memberaudit`.
> It builds on top of both. You need both plugins installed and working before enabling `mastery`.

## Main features

- Generate fitting skill plans from doctrine ships and their modules
- Merge **required** fitting skills with **recommended** ship mastery skills
- Add manual skills, blacklist skills, or override recommended levels per fitting
- Detect and suggest skills that can be removed from a plan
- Export missing skills in dependency-safe order for in-game EVE import
- Support multiple export languages for skill names
- Show member-facing doctrine readiness based on accessible fittings only
- Show leadership doctrine coverage across configurable corp/alliance audience groups
- Keep fitting access aligned with the access rules configured in the `fittings` plugin

## Screenshots

### Character progress

![Character progress](https://raw.githubusercontent.com/hermesdj/aa-fitting-mastery/main/docs/view-character-progress.png)

### Fitting skill plan management

![Fitting skill plans](https://raw.githubusercontent.com/hermesdj/aa-fitting-mastery/main/docs/edit-fitting-skill-plans.png)

## Installation

### 1 - Install prerequisites

Make sure your Alliance Auth installation already has these apps installed and configured:

- `fittings`
- `memberaudit`
- `eve_sde`

### 2 - Install the package

Install the plugin into your Alliance Auth virtual environment:

```bash
pip install aa-fitting-mastery
```

### 3 - Add the app to Alliance Auth

Add `mastery` to `INSTALLED_APPS` in your `local.py`:

```python
INSTALLED_APPS += [
    "mastery",
]
```

### 4 - Configure the scheduled SDE mastery update task

Add the periodic task to your `CELERYBEAT_SCHEDULE`:

```python
CELERYBEAT_SCHEDULE["update_sde_masteries"] = {
    "task": "mastery.tasks.update_sde_masteries",
    "schedule": crontab(0, 0, day_of_month="1"),
}
```

### 5 - Run migrations and collect static files

```bash
python manage.py migrate
python manage.py collectstatic
```

### 6 - Import mastery data

Import ship mastery and certificate data from the EVE SDE:

```bash
python manage.py import_sde_masteries
```

For a test run without writing to the database:

```bash
python manage.py import_sde_masteries --dry-run
```

### 7 - Restart your services

Restart your web and Celery services so the plugin and beat task are loaded.

## Updating

To update an existing installation:

```bash
pip install -U aa-fitting-mastery
python manage.py migrate
python manage.py collectstatic
```

Then restart your web and Celery services.

## Configuration

After installation, the usual setup flow is:

1. **Ensure your doctrines and fittings already exist in the `fittings` plugin**
2. Open **Manage Skill Plans** in Fitting Mastery
3. Generate or sync doctrine skill plans
4. Review each fitting and adjust:
   - mastery level,
   - manual skills,
   - blacklisted skills,
   - recommended level overrides,
   - skill suggestions
5. If you want doctrine leadership views, create audience groups in **Summary Group Settings**
6. Assign the appropriate permissions to members, doctrine managers and leadership roles

### Access model

For pilot-facing views, Fitting Mastery uses the same fittings visibility rules as the `fittings` plugin.

That means:

- users must have access to `fittings` itself,
- category restrictions remain effective,
- doctrines and fittings that are hidden in `fittings` will not be exposed by Fitting Mastery.

## Permissions

The plugin defines the following permissions:

| Code | Description |
| --- | --- |
| `basic_access` | Can access the pilot-facing Fitting Mastery pages |
| `manage_fittings` | Can manage doctrine/fitting skill plans |
| `doctrine_summary` | Can view leadership doctrine summary pages |
| `manage_summary_groups` | Can create and manage summary audience groups |

### Recommended usage

- **Members**: `basic_access`
- **Doctrine / fitting managers**: `basic_access`, `manage_fittings`
- **Leadership / FC / HR reviewers**: `basic_access`, `doctrine_summary`
- **Admins managing summary scopes**: `manage_summary_groups`

In practice, pilot-facing access is usually granted together with fitting visibility from the `fittings` plugin.

You will typically also want matching access in the `fittings` plugin, especially `fittings.access_fittings` or `fittings.manage`.

## How it works

At a high level the plugin works like this:

1. It reads the ship and module requirements from fitting dogma data
2. It reads ship mastery recommendations from imported SDE mastery data
3. It combines both into a per-fitting skill plan
4. It lets managers refine that plan with blacklists, manual additions and level overrides
5. It compares those plans against character skills from `aa-memberaudit`
6. It presents the result in pilot and leadership views

### Required vs Recommended

- **Required** skills come from fitting / module requirements and their recursive prerequisites
- **Recommended** skills come from ship mastery data, plus any manual adjustments you configure

### Summary groups

Doctrine summary views can be scoped to configurable audience groups.

Each summary group can combine:

- corporations,
- alliances,
- mixed corporation/alliance audiences.

This makes it possible to review doctrine coverage for a coalition, SIG, alliance wing or any other relevant operational scope.

### Exported skill plans

When exporting missing skills for a pilot, the plugin:

- includes all missing intermediate levels,
- adds missing prerequisites recursively,
- orders skills so prerequisites appear first,
- supports multiple languages for skill labels.

## Settings

The following setting can be added to your Alliance Auth `local.py`:

| Name | Description | Default |
| --- | --- | --- |
| `MASTERY_PLAN_ESTIMATE_SP_PER_HOUR` | Training speed used to estimate plan duration in fitting previews | `1800` |

Example:

```python
MASTERY_PLAN_ESTIMATE_SP_PER_HOUR = 1800
```

## Notes

- If you change doctrine skill plan configuration, regenerate or sync the affected doctrine/fitting so changes are reflected in the active skill set.
- If leadership summaries are enabled, remember to configure at least one summary audience group.
- If no mastery data has been imported yet, recommended ship skills will be incomplete until `import_sde_masteries` has been run.
- Fitting Mastery respects fitting visibility from the `fittings` plugin and will not intentionally expose restricted doctrines or fittings outside that access model.
