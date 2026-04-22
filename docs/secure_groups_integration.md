# Secure Groups Integration — Design & Implementation Plan

> **Status : IN PROGRESS**
> Dernière mise à jour : 2026-04-22
> Version cible : 0.2.0

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Dépendances & optionnalité](#2-dépendances--optionnalité)
3. [Filtres à implémenter](#3-filtres-à-implémenter)
4. [Architecture des fichiers](#4-architecture-des-fichiers)
5. [Détail d'implémentation par fichier](#5-détail-dimplémentation-par-fichier)
   - 5.1 [mastery/secure_groups.py](#51-masterysecure_groupspy)
   - 5.2 [mastery/models/__init__.py](#52-masterymodels__init__py)
   - 5.3 [mastery/apps.py](#53-masteryappspy)
   - 5.4 [mastery/admin.py](#54-masteryadminpy)
   - 5.5 [mastery/migrations/0012_secure_group_filters.py](#55-masterymigrations0012_secure_group_filterspy)
   - 5.6 [mastery/tests/test_secure_groups.py](#56-masteryteststest_secure_groupspy)
   - 5.7 [README.md — section optionnelle](#57-readmemd--section-optionnelle)
   - 5.8 [CHANGELOG.md](#58-changelogmd)
6. [Logique de check par filtre](#6-logique-de-check-par-filtre)
7. [Notes de performance](#7-notes-de-performance)
8. [Checklist d'implémentation](#8-checklist-dimplémentation)

---

## 1. Vue d'ensemble

Ce module ajoute une intégration **optionnelle** entre `aa-fitting-mastery` et
`allianceauth-secure-groups`. Quand `securegroups` est présent dans
`INSTALLED_APPS`, mastery expose des **Smart Filters** configurables depuis
l'admin Django, qui permettent de conditionner l'appartenance à un Smart Group
sur la progression des pilotes par rapport aux skill plans générés.

Le plugin secure-groups découvre les filtres via `ContentType`. Il suffit que
les modèles de filtres soient enregistrés dans l'admin (et présents en DB)
pour qu'ils apparaissent dans le catalogue.

---

## 2. Dépendances & optionnalité

- `allianceauth-secure-groups` **n'est PAS** une dépendance obligatoire.
- Tous les imports de `securegroups` sont **conditionnels** (wrap `try/except ImportError`).
- Les modèles de filtres sont définis dans `mastery/secure_groups.py` et
  importés dans `mastery/models/__init__.py` uniquement si `securegroups`
  est installé (géré depuis `apps.py:ready()`).
- La migration `0012` crée les tables **uniquement si le module est importé**
  (Django ne crée des tables que pour les modèles enregistrés).

**Pattern d'import conditionnel (à répéter partout) :**
```python
try:
    from securegroups.models import FilterBase
    SECURE_GROUPS_AVAILABLE = True
except ImportError:
    FilterBase = object  # fallback no-op base
    SECURE_GROUPS_AVAILABLE = False
```

---

## 3. Filtres à implémenter

### 3.1 `MasteryFittingStatusFilter`
**Nom admin :** `Smart Filter: Mastery — Fitting Status`

Vérifie que l'utilisateur (via au moins un de ses personnages memberaudit)
atteint un **statut bucket minimal** sur un fitting donné.

| Champ | Type | Description |
|---|---|---|
| `name` | CharField(500) | Nom affiché dans l'admin |
| `description` | CharField(500) | Description affichée dans le catalogue |
| `fitting_map` | FK → `FittingSkillsetMap` | Fitting cible |
| `minimum_status` | CharField choices | `needs_training` / `almost_fit` / `can_fly` / `almost_elite` / `elite` |
| `check_all_characters` | BooleanField(default=False) | Si True : tous les persos doivent passer ; si False (défaut) : au moins un |

**Logique `process_filter(user)` :**
1. Récupérer les `Character` memberaudit de l'user via `character_ownerships`.
2. Pour chaque character, vérifier `CharacterSkillSetCheck` sur le skillset du fitting.
3. Calculer le bucket via `bucket_for_progress(progress)`.
4. Retourner `True` si `BUCKET_RANK[bucket] >= BUCKET_RANK[minimum_status]`.

**Optimisation :** pour `can_fly` et inférieur, utiliser directement
`CharacterSkillSetCheck.can_fly` (DB, pas de calcul SP). Pour `almost_elite`
et `elite`, appeler `PilotProgressService.build_for_character`.

**Logique `audit_filter(users)` :**
- Batch : charger tous les `CharacterSkillSetCheck` pour le skillset en une requête.
- Message : `"[NomPerso] → [status_label]"` pour le meilleur perso trouvé.

---

### 3.2 `MasteryFittingProgressFilter`
**Nom admin :** `Smart Filter: Mastery — Fitting Recommended Progress`

Vérifie que l'utilisateur atteint un **pourcentage minimal du plan recommandé**
sur un fitting donné.

| Champ | Type | Description |
|---|---|---|
| `name` | CharField(500) | Nom affiché |
| `description` | CharField(500) | Description |
| `fitting_map` | FK → `FittingSkillsetMap` | Fitting cible |
| `minimum_progress_pct` | PositiveSmallIntegerField (0-100) | Seuil en % (ex: 80) |
| `use_required_plan` | BooleanField(default=False) | Si True : compare `required_pct` au lieu de `recommended_pct` |

**Logique `process_filter(user)` :**
1. Récupérer les `Character` memberaudit de l'user.
2. Appeler `PilotProgressService.build_for_character(character, skillset)`.
3. Prendre le max de `recommended_pct` (ou `required_pct`) sur tous les persos.
4. Retourner `True` si `max_pct >= minimum_progress_pct`.

**Logique `audit_filter(users)` :**
- Message : `"[NomPerso] → [pct]%"` pour le meilleur perso.

---

### 3.3 `MasteryDoctrineReadinessFilter`
**Nom admin :** `Smart Filter: Mastery — Doctrine Readiness`

Vérifie que l'utilisateur peut fly au moins **N fittings** d'une doctrine donnée
(parmi les fittings avec plan approuvé optionnellement).

| Champ | Type | Description |
|---|---|---|
| `name` | CharField(500) | Nom affiché |
| `description` | CharField(500) | Description |
| `doctrine_map` | FK → `DoctrineSkillSetGroupMap` | Doctrine cible |
| `minimum_fittings` | PositiveSmallIntegerField(default=1) | Nombre minimal de fittings à pouvoir fly |
| `approved_only` | BooleanField(default=False) | Si True : ne compte que les fittings approuvés (`status=approved`) |

**Logique `process_filter(user)` :**
1. Récupérer les `FittingSkillsetMap` de la doctrine (filtré `approved` si `approved_only`).
2. Pour chaque fitting map, vérifier `CharacterSkillSetCheck.can_fly` (requête DB directe).
3. Retourner `True` si le count de fittings flyables ≥ `minimum_fittings`.

**Logique `audit_filter(users)` :**
- Message : `"[N]/[total] fittings : [nom1], [nom2]"`.

---

### 3.4 `MasteryFittingEliteFilter`
**Nom admin :** `Smart Filter: Mastery — Fitting Elite`

Version simplifiée du filtre statut : vérifie uniquement si le perso est
en bucket `elite` (required 100% + recommended ≥ seuil elite configuré en settings).

| Champ | Type | Description |
|---|---|---|
| `name` | CharField(500) | Nom affiché |
| `description` | CharField(500) | Description |
| `fitting_map` | FK → `FittingSkillsetMap` | Fitting cible |

**Logique :** identique à `MasteryFittingStatusFilter` avec `minimum_status=elite` hardcodé.
Moins de configuration pour l'admin. Appelle `PilotProgressService.build_for_character`.

---

## 4. Architecture des fichiers

```
mastery/
├── secure_groups.py              # [NEW] Modèles FilterBase pour tous les filtres
├── apps.py                       # [MODIFY] ready() importe secure_groups si dispo
├── admin.py                      # [MODIFY] enregistrement des 4 filtres dans admin
├── models/
│   └── __init__.py               # [MODIFY] import conditionnel de secure_groups
├── migrations/
│   └── 0012_secure_group_filters.py  # [NEW] tables pour les 4 modèles de filtres
├── tests/
│   └── test_secure_groups.py     # [NEW] tests unitaires avec mock de securegroups
docs/
└── secure_groups_integration.md  # [THIS FILE]
README.md                         # [MODIFY] section "Optional: Secure Groups"
CHANGELOG.md                      # [MODIFY] entrée 0.2.0
```

---

## 5. Détail d'implémentation par fichier

### 5.1 `mastery/secure_groups.py`

Fichier central contenant les 4 modèles. Structure cible :

```python
"""Optional Secure Groups filter models for Fitting Mastery.

This module is only imported when allianceauth-secure-groups is installed.
All imports from securegroups are guarded with try/except.
"""
from collections import defaultdict

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

try:
    from securegroups.models import FilterBase
    SECURE_GROUPS_AVAILABLE = True
except ImportError:
    FilterBase = models.Model  # fallback: crée des modèles Django normaux non enregistrés
    SECURE_GROUPS_AVAILABLE = False


def _get_memberaudit_characters(user: User):
    """Return list of memberaudit Character objects for a user (all ownerships)."""
    # Import local pour éviter la dépendance circulaire
    from memberaudit.models import Character
    character_ids = user.character_ownerships.values_list("character__character_id", flat=True)
    return list(Character.objects.filter(
        character_ownership__character__character_id__in=character_ids
    ).select_related("character_ownership__character"))


def _best_progress_for_skillset(characters, skillset_id: int) -> dict:
    """
    Return best (highest rank) progress dict across all characters for a skillset.
    Uses CharacterSkillSetCheck for can_fly + DB counts.
    Returns {"can_fly": bool, "required_pct": float, "recommended_pct": float,
             "character_name": str}
    """
    from memberaudit.models import CharacterSkillSetCheck
    from mastery.services.pilots.status_buckets import BUCKET_RANK, bucket_for_progress

    checks = {
        c.skill_set_id: c
        for c in CharacterSkillSetCheck.objects.filter(
            character__in=characters,
            skill_set_id=skillset_id,
        ).select_related("character__character_ownership__character")
    }

    best = None
    best_rank = -1
    for character in characters:
        check = checks.get(skillset_id)  # TODO: key by character
        # ... (implémentation détaillée dans le code final)
    return best or {"can_fly": False, "required_pct": 0.0, "recommended_pct": 0.0, "character_name": ""}


# ─── Filtre 1 : Statut bucket ────────────────────────────────────────────────

class MasteryFittingStatusFilter(FilterBase):
    class Meta:
        verbose_name = _("Smart Filter: Mastery — Fitting Status")
        verbose_name_plural = _("Smart Filter: Mastery — Fitting Status")
        abstract = not SECURE_GROUPS_AVAILABLE

    # Choices for minimum_status
    STATUS_CHOICES = [
        ("needs_training", _("Needs training")),
        ("almost_fit", _("Almost fit")),
        ("can_fly", _("Can fly")),
        ("almost_elite", _("Almost elite")),
        ("elite", _("Elite")),
    ]

    fitting_map = models.ForeignKey(
        "mastery.FittingSkillsetMap",
        on_delete=models.CASCADE,
        verbose_name=_("fitting skill plan"),
    )
    minimum_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="can_fly",
        verbose_name=_("minimum status"),
    )
    check_all_characters = models.BooleanField(
        default=False,
        verbose_name=_("require all characters to pass"),
        help_text=_("If checked, all registered characters must reach the minimum status. "
                    "By default, any single character passing is enough."),
    )

    def process_filter(self, user: User) -> bool: ...
    def audit_filter(self, users) -> dict: ...


# ─── Filtre 2 : Pourcentage de progression ───────────────────────────────────

class MasteryFittingProgressFilter(FilterBase):
    class Meta:
        verbose_name = _("Smart Filter: Mastery — Fitting Progress")
        verbose_name_plural = _("Smart Filter: Mastery — Fitting Progress")
        abstract = not SECURE_GROUPS_AVAILABLE

    fitting_map = models.ForeignKey(
        "mastery.FittingSkillsetMap",
        on_delete=models.CASCADE,
        verbose_name=_("fitting skill plan"),
    )
    minimum_progress_pct = models.PositiveSmallIntegerField(
        default=80,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("minimum progress (%)"),
    )
    use_required_plan = models.BooleanField(
        default=False,
        verbose_name=_("use required plan"),
        help_text=_("If checked, compares against the required skills plan. "
                    "By default, compares against the recommended skills plan."),
    )

    def process_filter(self, user: User) -> bool: ...
    def audit_filter(self, users) -> dict: ...


# ─── Filtre 3 : Readiness doctrine ──────────────────────────────────────────

class MasteryDoctrineReadinessFilter(FilterBase):
    class Meta:
        verbose_name = _("Smart Filter: Mastery — Doctrine Readiness")
        verbose_name_plural = _("Smart Filter: Mastery — Doctrine Readiness")
        abstract = not SECURE_GROUPS_AVAILABLE

    doctrine_map = models.ForeignKey(
        "mastery.DoctrineSkillSetGroupMap",
        on_delete=models.CASCADE,
        verbose_name=_("doctrine skill plan"),
    )
    minimum_fittings = models.PositiveSmallIntegerField(
        default=1,
        verbose_name=_("minimum flyable fittings"),
    )
    approved_only = models.BooleanField(
        default=False,
        verbose_name=_("approved fittings only"),
        help_text=_("If checked, only fittings with 'approved' status count toward the minimum."),
    )

    def process_filter(self, user: User) -> bool: ...
    def audit_filter(self, users) -> dict: ...


# ─── Filtre 4 : Elite simplifié ──────────────────────────────────────────────

class MasteryFittingEliteFilter(FilterBase):
    class Meta:
        verbose_name = _("Smart Filter: Mastery — Fitting Elite")
        verbose_name_plural = _("Smart Filter: Mastery — Fitting Elite")
        abstract = not SECURE_GROUPS_AVAILABLE

    fitting_map = models.ForeignKey(
        "mastery.FittingSkillsetMap",
        on_delete=models.CASCADE,
        verbose_name=_("fitting skill plan"),
    )

    def process_filter(self, user: User) -> bool: ...
    def audit_filter(self, users) -> dict: ...
```

**Note :** `abstract = not SECURE_GROUPS_AVAILABLE` — si securegroups n'est pas là,
les modèles deviennent abstraits et aucune migration / table n'est créée.

---

### 5.2 `mastery/models/__init__.py`

Ajouter en bas, **conditionnellement** :

```python
# Secure Groups integration (optional)
try:
    from securegroups.models import FilterBase as _FilterBase  # noqa: F401
    from .secure_groups import (  # noqa: F401
        MasteryFittingStatusFilter,
        MasteryFittingProgressFilter,
        MasteryDoctrineReadinessFilter,
        MasteryFittingEliteFilter,
    )
except ImportError:
    pass
```

---

### 5.3 `mastery/apps.py`

Ajouter `ready()` pour enregistrer les filtres si securegroups est disponible :

```python
from django.apps import AppConfig


class MasteryConfig(AppConfig):
    name = "mastery"
    label = "mastery"
    verbose_name = "Fitting Mastery"

    def ready(self):
        # Import secure_groups filters only if securegroups is installed.
        # This registers the models with Django's app registry so ContentType
        # picks them up and secure-groups can discover the filter catalog.
        try:
            import securegroups  # noqa: F401
            from mastery import secure_groups  # noqa: F401
        except ImportError:
            pass
```

---

### 5.4 `mastery/admin.py`

Enregistrement conditionnel des 4 filtres. Exemple de pattern :

```python
# Secure Groups integration
try:
    from securegroups.models import FilterBase  # noqa: F401
    from mastery.secure_groups import (
        MasteryDoctrineReadinessFilter,
        MasteryFittingEliteFilter,
        MasteryFittingProgressFilter,
        MasteryFittingStatusFilter,
    )

    @admin.register(MasteryFittingStatusFilter)
    class MasteryFittingStatusFilterAdmin(admin.ModelAdmin):
        list_display = ("name", "description", "fitting_map", "minimum_status", "check_all_characters")

    @admin.register(MasteryFittingProgressFilter)
    class MasteryFittingProgressFilterAdmin(admin.ModelAdmin):
        list_display = ("name", "description", "fitting_map", "minimum_progress_pct", "use_required_plan")

    @admin.register(MasteryDoctrineReadinessFilter)
    class MasteryDoctrineReadinessFilterAdmin(admin.ModelAdmin):
        list_display = ("name", "description", "doctrine_map", "minimum_fittings", "approved_only")

    @admin.register(MasteryFittingEliteFilter)
    class MasteryFittingEliteFilterAdmin(admin.ModelAdmin):
        list_display = ("name", "description", "fitting_map")

except ImportError:
    pass
```

---

### 5.5 `mastery/migrations/0012_secure_group_filters.py`

Migration à générer avec `makemigrations mastery` après l'implémentation des modèles.

> ⚠️ **Important :** ne pas écrire cette migration à la main. La générer via :
> ```
> python manage.py makemigrations mastery
> ```
> avec `securegroups` présent dans `INSTALLED_APPS` du projet de test.

La migration sera conditionnelle : Django ne crée pas les tables des modèles
abstraits, donc si `SECURE_GROUPS_AVAILABLE = False`, les classes sont
abstraites et aucune table n'est créée. La migration peut quand même exister
dans le code — elle est simplement vide d'opérations sur les modèles abstraits.

**Stratégie alternative :** écrire la migration manuellement avec un
`state_operations` conditionnel. À valider selon ce que `makemigrations` produit.

---

### 5.6 `mastery/tests/test_secure_groups.py`

Structure des tests :

```python
"""Tests for optional Secure Groups filter integration."""
from unittest.mock import MagicMock, patch
from django.test import TestCase


class TestMasteryFittingStatusFilter(TestCase):
    """Tests for MasteryFittingStatusFilter."""

    def test_process_filter_returns_true_when_character_reaches_minimum_status(self): ...
    def test_process_filter_returns_false_when_no_character_qualifies(self): ...
    def test_process_filter_returns_false_when_no_memberaudit_characters(self): ...
    def test_process_filter_check_all_characters_requires_all_to_pass(self): ...
    def test_audit_filter_returns_correct_message_and_check(self): ...
    def test_audit_filter_returns_false_for_users_without_characters(self): ...


class TestMasteryFittingProgressFilter(TestCase):
    """Tests for MasteryFittingProgressFilter."""

    def test_process_filter_returns_true_when_pct_above_threshold(self): ...
    def test_process_filter_returns_false_when_pct_below_threshold(self): ...
    def test_process_filter_uses_required_pct_when_flag_set(self): ...
    def test_audit_filter_returns_best_character_pct(self): ...


class TestMasteryDoctrineReadinessFilter(TestCase):
    """Tests for MasteryDoctrineReadinessFilter."""

    def test_process_filter_counts_flyable_fittings(self): ...
    def test_process_filter_approved_only_excludes_non_approved(self): ...
    def test_process_filter_returns_false_when_below_minimum(self): ...
    def test_audit_filter_reports_fitting_names(self): ...


class TestMasteryFittingEliteFilter(TestCase):
    """Tests for MasteryFittingEliteFilter."""

    def test_process_filter_returns_true_for_elite_bucket(self): ...
    def test_process_filter_returns_false_for_non_elite_bucket(self): ...
```

**Note :** les tests mockent `securegroups.models.FilterBase` via `@patch` ou
via un settings flag `SECURE_GROUPS_INSTALLED = True` dans `testauth/settings`.

---

### 5.7 `README.md` — section optionnelle

Ajouter une section :

```markdown
## Optional: Secure Groups Integration

If [`allianceauth-secure-groups`](https://github.com/pvyParts/allianceauth-secure-groups)
is installed, Fitting Mastery exposes four Smart Filter types in the Django admin:

| Filter | Description |
|---|---|
| **Mastery — Fitting Status** | Requires a pilot to reach a minimum status bucket (Can fly, Elite, …) on a specific fitting. |
| **Mastery — Fitting Progress** | Requires a pilot to reach a minimum % completion of the recommended (or required) skill plan. |
| **Mastery — Doctrine Readiness** | Requires a pilot to be able to fly at least N fittings of a doctrine. |
| **Mastery — Fitting Elite** | Requires a pilot to be in the Elite bucket on a specific fitting. |

### Setup

1. Install `allianceauth-secure-groups`.
2. Add `securegroups` to `INSTALLED_APPS`.
3. Run `python manage.py migrate`.
4. Configure Smart Filters via **Django Admin → Mastery → Smart Filter: Mastery — …**.
5. Attach the filters to Smart Groups via **Django Admin → Secure Groups → Smart Group**.
```

---

### 5.8 `CHANGELOG.md`

Entrée `## [0.2.0] - yyyy-mm-dd` avec :

```markdown
### Added

- Optional integration with `allianceauth-secure-groups`:
  - `MasteryFittingStatusFilter` — gate a Smart Group on pilot status bucket (Needs training / Almost fit / Can fly / Almost elite / Elite) for a specific fitting.
  - `MasteryFittingProgressFilter` — gate a Smart Group on the % completion of the recommended or required skill plan for a fitting.
  - `MasteryDoctrineReadinessFilter` — gate a Smart Group on being able to fly at least N fittings of a doctrine (with optional approved-only mode).
  - `MasteryFittingEliteFilter` — simplified filter gating on the Elite bucket for a specific fitting.
- All four filters are auto-discovered by secure-groups via Django ContentType and appear in the Smart Filter catalog without any extra configuration.

### Upgrade Notes

> ⚠️ **A database migration must be run if `securegroups` is in `INSTALLED_APPS`.**

- Update package:
  - `pip install -U aa-fitting-mastery==0.2.0`
- Apply database changes (creates filter tables if securegroups is installed):
  - `python manage.py migrate`
- Rebuild static assets:
  - `python manage.py collectstatic --noinput`
- Restart services.
```

---

## 6. Logique de check par filtre

### Résolution utilisateur → characters

```python
def _get_memberaudit_characters(user: User):
    from memberaudit.models import Character
    return list(
        Character.objects.filter(
            character_ownership__user=user
        ).select_related("character_ownership__character")
    )
```

### `can_fly` — check DB direct (sans PilotProgressService)

```python
from memberaudit.models import CharacterSkillSetCheck

def _character_can_fly(character, skillset_id: int) -> bool:
    try:
        check = CharacterSkillSetCheck.objects.get(
            character=character,
            skill_set_id=skillset_id,
        )
        return check.can_fly  # property: not failed_required_skills.exists()
    except CharacterSkillSetCheck.DoesNotExist:
        return False
```

### Progress complet (pour % et elite)

```python
from mastery.services.pilots.pilot_progress_service import PilotProgressService

def _character_progress(character, skillset):
    svc = PilotProgressService()
    return svc.build_for_character(
        character=character,
        skillset=skillset,
        include_export_lines=False,  # ne pas générer les lignes d'export
    )
```

### Sélection du "meilleur perso"

```python
from mastery.services.pilots.status_buckets import BUCKET_RANK, bucket_for_progress

def _best_character_progress(characters, skillset_id: int, skillset) -> dict | None:
    """Return progress dict with highest bucket rank across all characters."""
    best = None
    best_rank = -1

    for character in characters:
        progress = _character_progress(character, skillset)
        if progress is None:
            continue
        bucket = bucket_for_progress(progress)
        rank = BUCKET_RANK.get(bucket, 0)
        if rank > best_rank:
            best_rank = rank
            best = progress
            best["_character_name"] = getattr(
                getattr(character, "character_ownership", None),
                "character", None
            )

    return best
```

### Audit batch (optimisation)

Pour `audit_filter(users)`, charger les `CharacterSkillSetCheck` en une seule requête :

```python
all_character_ids = [...]  # IDs memberaudit Character de tous les users
checks = CharacterSkillSetCheck.objects.filter(
    character_id__in=all_character_ids,
    skill_set_id=skillset_id,
).select_related("character__character_ownership__character",
                 "character__character_ownership__user")
```

---

## 7. Notes de performance

| Filtre | Mode process_filter | Mode audit_filter |
|---|---|---|
| Status (can_fly et inférieur) | 1 requête DB par user (check exists) | 1 requête batch pour tous les users |
| Status (almost_elite / elite) | PilotProgressService par character | PilotProgressService par character — peut être lent sur gros groupes |
| Progress % | PilotProgressService par character | Même coût |
| Doctrine readiness | N requêtes (N = nb fittings), 1 check par fitting | Batch possible sur les skillset_ids |
| Elite | PilotProgressService par character | Même coût |

**Recommandations :**
- Pour les groupes ≥ 100 membres, les filtres qui appellent `PilotProgressService`
  peuvent être lents en mode audit. Documenter ce point dans le README.
- Le mode `process_filter` (appelé lors de la demande d'adhésion) est toujours
  individuel, donc acceptable.
- Pour `audit_filter` des filtres % / elite, on peut ajouter une option
  `use_can_fly_only` qui dégrade vers le check DB direct si les admins
  veulent la performance au détriment de la précision.

---

## 8. Checklist d'implémentation

> Cocher au fur et à mesure. Ce fichier est la source de vérité pour reprendre une implémentation partielle.

### Fichiers à créer
- [ ] `mastery/secure_groups.py` — modèles des 4 filtres avec logique complète
- [ ] `mastery/migrations/0012_secure_group_filters.py` — générée par `makemigrations`
- [ ] `mastery/tests/test_secure_groups.py` — tests unitaires des 4 filtres

### Fichiers à modifier
- [ ] `mastery/models/__init__.py` — import conditionnel de secure_groups.py
- [ ] `mastery/apps.py` — `ready()` avec import conditionnel
- [ ] `mastery/admin.py` — enregistrement admin des 4 filtres
- [ ] `README.md` — section "Optional: Secure Groups Integration"
- [ ] `CHANGELOG.md` — entrée 0.2.0
- [ ] `mastery/__init__.py` — bump version 0.1.9 → 0.2.0

### Validation
- [ ] `python manage.py migrate` (avec securegroups dans INSTALLED_APPS)
- [ ] `python runtests.py mastery.tests.test_secure_groups -v 2` — tous les tests passent
- [ ] `python runtests.py mastery -v 2` — suite complète inchangée
- [ ] `pylint --load-plugins pylint_django mastery` — 10.00/10
- [ ] Vérifier que les filtres apparaissent dans l'admin sous "Mastery"
- [ ] Vérifier que les filtres apparaissent dans le catalogue Smart Group de securegroups

### Post-implémentation
- [ ] `makemessages` + `compilemessages` pour fr_FR (nouveaux strings i18n)
- [ ] Bump version 0.2.0 dans `mastery/__init__.py` et `CHANGELOG.md`

