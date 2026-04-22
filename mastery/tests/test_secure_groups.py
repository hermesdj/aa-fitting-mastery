"""Tests for the optional Secure Groups filter integration.

Strategy
--------
* Unbound method calls: ``FilterClass.method(ns, *args)`` where ``ns`` is a
  ``SimpleNamespace`` mimicking ``self`` — avoids Django FK descriptor
  validation completely.
* Internal methods (``_passes``, ``_get_fitting_maps``, ``_count_flyable``) are
  bound to the namespace with ``types.MethodType`` so ``self.method(...)`` calls
  inside the production code resolve correctly.
* Patch paths for ``bucket_for_progress``, ``BUCKET_RANK``, ``BUCKET_LABELS``
  and ``BUCKET_ELITE`` use ``mastery.secure_groups.*`` because those names are
  imported at module level there (not re-looked-up via the origin module on
  each call).
"""
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase


# ──────────────────────────────────────────────────────────────────────────────
# Fake builders
# ──────────────────────────────────────────────────────────────────────────────

def _make_user(uid: int = 1) -> Mock:
    user = Mock()
    user.id = uid
    return user


def _make_character(name: str = "Pilot One", char_id: int = 10):
    char = Mock()
    char.id = char_id
    char.character_ownership.character.character_name = name
    char.character_ownership.user_id = 1
    return char


def _make_skillset(sid: int = 100):
    ss = Mock()
    ss.id = sid
    return ss


def _make_fitting_map(status="approved", name="Test Fitting"):
    fm = Mock()
    fm.skillset = _make_skillset()
    fm.skillset_id = fm.skillset.id
    fm.status = status
    fm.fitting.name = name
    fm.fitting_id = 99
    return fm


def _make_progress(can_fly=True, required_pct=100.0, recommended_pct=100.0):
    return {
        "can_fly": can_fly,
        "required_pct": required_pct,
        "recommended_pct": recommended_pct,
    }


# ──────────────────────────────────────────────────────────────────────────────
# SimpleNamespace "self" factories (no Django FK descriptors)
# ──────────────────────────────────────────────────────────────────────────────

def _status_self(minimum_status="can_fly", check_all=False):
    """Fake MasteryFittingStatusFilter instance with _passes bound."""
    from mastery.secure_groups import MasteryFittingStatusFilter
    ns = SimpleNamespace(
        minimum_status=minimum_status,
        check_all_characters=check_all,
        fitting_map=SimpleNamespace(skillset=_make_skillset()),
    )
    ns._passes = types.MethodType(MasteryFittingStatusFilter._passes, ns)
    return ns


def _progress_self(minimum_pct=80, use_required=False):
    return SimpleNamespace(
        minimum_progress_pct=minimum_pct,
        use_required_plan=use_required,
        fitting_map=SimpleNamespace(skillset=_make_skillset()),
    )


def _doctrine_self(minimum=1, approved_only=False):
    """Fake MasteryDoctrineReadinessFilter with _count_flyable bound."""
    from mastery.secure_groups import MasteryDoctrineReadinessFilter
    ns = SimpleNamespace(
        minimum_fittings=minimum,
        approved_only=approved_only,
        doctrine_map=Mock(),
    )
    # Note: _get_fitting_maps is NOT bound here — tests set ns._get_fitting_maps
    # directly so they fully control the returned fitting list.
    ns._count_flyable = types.MethodType(MasteryDoctrineReadinessFilter._count_flyable, ns)
    return ns


def _elite_self():
    return SimpleNamespace(
        fitting_map=SimpleNamespace(skillset=_make_skillset()),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Patch paths
# NOTE: bucket_for_progress / BUCKET_* are imported at module level into
# mastery.secure_groups, so patch THERE not in the origin module.
# ──────────────────────────────────────────────────────────────────────────────

_SG = "mastery.secure_groups"


# ──────────────────────────────────────────────────────────────────────────────
# MasteryFittingStatusFilter
# ──────────────────────────────────────────────────────────────────────────────

class TestMasteryFittingStatusFilter(SimpleTestCase):
    """Unit tests for MasteryFittingStatusFilter.process_filter / audit_filter."""

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db", return_value=True)
    def test_process_filter_can_fly_returns_true_when_character_qualifies(self, _cf, mock_chars):
        from mastery.secure_groups import MasteryFittingStatusFilter
        mock_chars.return_value = [_make_character()]
        ns = _status_self(minimum_status="can_fly")
        self.assertTrue(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db", return_value=False)
    def test_process_filter_can_fly_returns_false_when_character_cannot_fly(self, _cf, mock_chars):
        from mastery.secure_groups import MasteryFittingStatusFilter
        mock_chars.return_value = [_make_character()]
        ns = _status_self(minimum_status="can_fly")
        self.assertFalse(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}._can_fly_db", return_value=False)
    def test_process_filter_can_fly_uses_progress_fallback_when_db_false_negative(
        self, _cf, mock_progress, mock_chars
    ):
        from mastery.secure_groups import MasteryFittingStatusFilter

        mock_chars.return_value = [_make_character()]
        mock_progress.return_value = _make_progress(can_fly=True, required_pct=100.0)
        ns = _status_self(minimum_status="can_fly")

        self.assertTrue(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters", return_value=[])
    def test_process_filter_returns_false_when_no_characters(self, _mock):
        from mastery.secure_groups import MasteryFittingStatusFilter
        ns = _status_self()
        self.assertFalse(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}.bucket_for_progress", return_value="elite")
    @patch(f"{_SG}.BUCKET_RANK", {"elite": 5, "can_fly": 3, "needs_training": 1})
    def test_process_filter_elite_returns_true_for_elite_bucket(self, _bfp, mock_progress, mock_chars):
        from mastery.secure_groups import MasteryFittingStatusFilter
        mock_chars.return_value = [_make_character()]
        mock_progress.return_value = _make_progress(recommended_pct=100.0)
        ns = _status_self(minimum_status="elite")
        self.assertTrue(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db")
    def test_process_filter_check_all_requires_all_characters(self, mock_can_fly, mock_chars):
        from mastery.secure_groups import MasteryFittingStatusFilter
        mock_chars.return_value = [_make_character("A", 10), _make_character("B", 11)]
        mock_can_fly.side_effect = [True, False]
        ns = _status_self(minimum_status="can_fly", check_all=True)
        self.assertFalse(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db", return_value=True)
    def test_process_filter_check_all_passes_when_all_qualify(self, _cf, mock_chars):
        from mastery.secure_groups import MasteryFittingStatusFilter
        mock_chars.return_value = [_make_character("A", 10), _make_character("B", 11)]
        ns = _status_self(minimum_status="can_fly", check_all=True)
        self.assertTrue(MasteryFittingStatusFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._user_to_characters_map")
    @patch(f"{_SG}._bulk_can_fly_map")
    @patch(f"{_SG}.BUCKET_RANK", {"can_fly": 3, "elite": 5, "needs_training": 1})
    @patch(f"{_SG}.BUCKET_LABELS", {"can_fly": "Can fly"})
    def test_audit_filter_returns_correct_structure(self, mock_bulk_can_fly_map, mock_user_chars):
        from mastery.secure_groups import MasteryFittingStatusFilter
        user = _make_user(1)
        character = _make_character()
        mock_user_chars.return_value = {1: [character]}
        mock_bulk_can_fly_map.return_value = {character.id: True}
        ns = _status_self(minimum_status="can_fly")
        result = MasteryFittingStatusFilter.audit_filter(ns, [user])
        self.assertIn(1, result)
        self.assertTrue(result[1]["check"])
        self.assertIn("Pilot One", result[1]["message"])

    @patch(f"{_SG}._user_to_characters_map", return_value={})
    def test_audit_filter_returns_false_for_users_without_characters(self, _mock):
        from mastery.secure_groups import MasteryFittingStatusFilter
        user = _make_user(1)
        ns = _status_self()
        result = MasteryFittingStatusFilter.audit_filter(ns, [user])
        self.assertFalse(result[1]["check"])


# ──────────────────────────────────────────────────────────────────────────────
# MasteryFittingProgressFilter
# ──────────────────────────────────────────────────────────────────────────────

class TestMasteryFittingProgressFilter(SimpleTestCase):
    """Unit tests for MasteryFittingProgressFilter."""

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._best_pct_for_characters", return_value=(90.0, "Pilot One"))
    def test_process_filter_returns_true_when_above_threshold(self, _pct, mock_chars):
        from mastery.secure_groups import MasteryFittingProgressFilter
        mock_chars.return_value = [_make_character()]
        ns = _progress_self(minimum_pct=80)
        self.assertTrue(MasteryFittingProgressFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._best_pct_for_characters", return_value=(70.0, "Pilot One"))
    def test_process_filter_returns_false_when_below_threshold(self, _pct, mock_chars):
        from mastery.secure_groups import MasteryFittingProgressFilter
        mock_chars.return_value = [_make_character()]
        ns = _progress_self(minimum_pct=80)
        self.assertFalse(MasteryFittingProgressFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters", return_value=[])
    def test_process_filter_returns_false_when_no_characters(self, _mock):
        from mastery.secure_groups import MasteryFittingProgressFilter
        ns = _progress_self()
        self.assertFalse(MasteryFittingProgressFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._best_pct_for_characters")
    def test_process_filter_passes_use_required_flag(self, mock_pct, mock_chars):
        from mastery.secure_groups import MasteryFittingProgressFilter
        mock_chars.return_value = [_make_character()]
        mock_pct.return_value = (85.0, "Pilot One")
        ns = _progress_self(use_required=True)
        MasteryFittingProgressFilter.process_filter(ns, _make_user())
        self.assertTrue(mock_pct.call_args.args[2])

    @patch(f"{_SG}._user_to_characters_map")
    @patch(f"{_SG}._build_progress")
    def test_audit_filter_returns_best_pct_message(self, mock_progress, mock_user_chars):
        from mastery.secure_groups import MasteryFittingProgressFilter
        user = _make_user(1)
        mock_user_chars.return_value = {1: [_make_character()]}
        mock_progress.return_value = _make_progress(recommended_pct=85.0)
        ns = _progress_self(minimum_pct=80)
        result = MasteryFittingProgressFilter.audit_filter(ns, [user])
        self.assertTrue(result[1]["check"])
        self.assertIn("85.0%", result[1]["message"])


# ──────────────────────────────────────────────────────────────────────────────
# MasteryDoctrineReadinessFilter
# ──────────────────────────────────────────────────────────────────────────────

class TestMasteryDoctrineReadinessFilter(SimpleTestCase):
    """Unit tests for MasteryDoctrineReadinessFilter."""

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db", return_value=True)
    def test_process_filter_returns_true_when_enough_flyable(self, _cf, mock_chars):
        from mastery.secure_groups import MasteryDoctrineReadinessFilter
        mock_chars.return_value = [_make_character()]
        ns = _doctrine_self(minimum=1)
        ns._get_fitting_maps = lambda: [_make_fitting_map()]
        self.assertTrue(MasteryDoctrineReadinessFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db", return_value=False)
    def test_process_filter_returns_false_when_cannot_fly_any(self, _cf, mock_chars):
        from mastery.secure_groups import MasteryDoctrineReadinessFilter
        mock_chars.return_value = [_make_character()]
        ns = _doctrine_self(minimum=1)
        ns._get_fitting_maps = lambda: [_make_fitting_map()]
        self.assertFalse(MasteryDoctrineReadinessFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}._can_fly_db", return_value=False)
    def test_process_filter_uses_progress_fallback_when_db_false_negative(
        self, _cf, mock_progress, mock_chars
    ):
        from mastery.secure_groups import MasteryDoctrineReadinessFilter

        mock_chars.return_value = [_make_character()]
        mock_progress.return_value = _make_progress(can_fly=True, required_pct=100.0)
        ns = _doctrine_self(minimum=1)
        ns._get_fitting_maps = lambda: [_make_fitting_map()]

        self.assertTrue(MasteryDoctrineReadinessFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters", return_value=[])
    def test_process_filter_returns_false_when_no_characters(self, _mock):
        from mastery.secure_groups import MasteryDoctrineReadinessFilter
        ns = _doctrine_self()
        ns._get_fitting_maps = lambda: [_make_fitting_map()]
        self.assertFalse(MasteryDoctrineReadinessFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._can_fly_db")
    def test_process_filter_counts_correctly_with_multiple_fittings(self, mock_can_fly, mock_chars):
        from mastery.secure_groups import MasteryDoctrineReadinessFilter
        mock_chars.return_value = [_make_character()]
        mock_can_fly.side_effect = [True, False]
        ns = _doctrine_self(minimum=2)
        ns._get_fitting_maps = lambda: [_make_fitting_map(), _make_fitting_map()]
        self.assertFalse(MasteryDoctrineReadinessFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._user_to_characters_map")
    @patch(f"{_SG}._can_fly_db", return_value=True)
    def test_audit_filter_reports_fitting_names(self, _cf, mock_user_chars):
        from mastery.secure_groups import MasteryDoctrineReadinessFilter
        user = _make_user(1)
        mock_user_chars.return_value = {1: [_make_character()]}
        ns = _doctrine_self(minimum=1)
        ns._get_fitting_maps = lambda: [_make_fitting_map(name="Test Fitting")]
        result = MasteryDoctrineReadinessFilter.audit_filter(ns, [user])
        self.assertTrue(result[1]["check"])
        self.assertIn("Test Fitting", result[1]["message"])


# ──────────────────────────────────────────────────────────────────────────────
# MasteryFittingEliteFilter
# ──────────────────────────────────────────────────────────────────────────────

class TestMasteryFittingEliteFilter(SimpleTestCase):
    """Unit tests for MasteryFittingEliteFilter."""

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}.bucket_for_progress", return_value="elite")
    @patch(f"{_SG}.BUCKET_ELITE", "elite")
    def test_process_filter_returns_true_for_elite_bucket(self, _bfp, mock_progress, mock_chars):
        from mastery.secure_groups import MasteryFittingEliteFilter
        mock_chars.return_value = [_make_character()]
        mock_progress.return_value = _make_progress(recommended_pct=100.0)
        ns = _elite_self()
        self.assertTrue(MasteryFittingEliteFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}.bucket_for_progress", return_value="can_fly")
    @patch(f"{_SG}.BUCKET_ELITE", "elite")
    def test_process_filter_returns_false_for_non_elite_bucket(self, _bfp, mock_progress, mock_chars):
        from mastery.secure_groups import MasteryFittingEliteFilter
        mock_chars.return_value = [_make_character()]
        mock_progress.return_value = _make_progress(recommended_pct=75.0)
        ns = _elite_self()
        self.assertFalse(MasteryFittingEliteFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._get_memberaudit_characters", return_value=[])
    def test_process_filter_returns_false_when_no_characters(self, _mock):
        from mastery.secure_groups import MasteryFittingEliteFilter
        ns = _elite_self()
        self.assertFalse(MasteryFittingEliteFilter.process_filter(ns, _make_user()))

    @patch(f"{_SG}._user_to_characters_map")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}.bucket_for_progress", return_value="elite")
    @patch(f"{_SG}.BUCKET_ELITE", "elite")
    def test_audit_filter_marks_elite_pass(self, _bfp, mock_progress, mock_user_chars):
        from mastery.secure_groups import MasteryFittingEliteFilter
        user = _make_user(1)
        mock_user_chars.return_value = {1: [_make_character()]}
        mock_progress.return_value = _make_progress(recommended_pct=100.0)
        ns = _elite_self()
        result = MasteryFittingEliteFilter.audit_filter(ns, [user])
        self.assertTrue(result[1]["check"])
        self.assertIn("Elite", result[1]["message"])

    @patch(f"{_SG}._user_to_characters_map")
    @patch(f"{_SG}._build_progress")
    @patch(f"{_SG}.bucket_for_progress", return_value="can_fly")
    @patch(f"{_SG}.BUCKET_ELITE", "elite")
    def test_audit_filter_marks_non_elite_fail_with_pct(self, _bfp, mock_progress, mock_user_chars):
        from mastery.secure_groups import MasteryFittingEliteFilter
        user = _make_user(1)
        mock_user_chars.return_value = {1: [_make_character()]}
        mock_progress.return_value = _make_progress(recommended_pct=80.0)
        ns = _elite_self()
        result = MasteryFittingEliteFilter.audit_filter(ns, [user])
        self.assertFalse(result[1]["check"])
        self.assertIn("80.0%", result[1]["message"])


# ──────────────────────────────────────────────────────────────────────────────
# Internal helper unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSecureGroupHelpers(SimpleTestCase):
    """Unit tests for internal helper functions in mastery.secure_groups."""

    @patch(f"{_SG}._build_progress")
    def test_best_pct_for_characters_returns_max_recommended(self, mock_build):
        from mastery.secure_groups import _best_pct_for_characters
        chars = [_make_character("A", 1), _make_character("B", 2)]
        mock_build.side_effect = [
            _make_progress(recommended_pct=60.0),
            _make_progress(recommended_pct=85.0),
        ]
        pct, name = _best_pct_for_characters(chars, _make_skillset(), use_required=False)
        self.assertAlmostEqual(pct, 85.0)
        self.assertEqual(name, "B")

    @patch(f"{_SG}._build_progress")
    def test_best_pct_for_characters_uses_required_flag(self, mock_build):
        from mastery.secure_groups import _best_pct_for_characters
        chars = [_make_character()]
        mock_build.return_value = _make_progress(required_pct=70.0, recommended_pct=90.0)
        pct, _ = _best_pct_for_characters(chars, _make_skillset(), use_required=True)
        self.assertAlmostEqual(pct, 70.0)

    def test_character_name_extracts_name(self):
        from mastery.secure_groups import _character_name
        char = _make_character("Tester One")
        self.assertEqual(_character_name(char), "Tester One")

    def test_character_name_returns_str_on_error(self):
        from mastery.secure_groups import _character_name

        class _BadChar:
            @property
            def character_ownership(self):
                raise AttributeError("simulated failure")

            def __str__(self):
                return "bad_char_fallback"

        result = _character_name(_BadChar())
        self.assertIsInstance(result, str)
        self.assertEqual(result, "bad_char_fallback")






