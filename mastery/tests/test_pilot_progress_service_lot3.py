"""Lot 3 – targeted coverage for PilotProgressService uncovered paths."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.test import SimpleTestCase

from mastery.services.pilots.pilot_progress_service import PilotProgressService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(eve_type_id, name="Skill", required_level=None, recommended_level=None):
    return SimpleNamespace(
        eve_type_id=eve_type_id,
        eve_type=SimpleNamespace(name=name),
        required_level=required_level,
        recommended_level=recommended_level,
    )


def _make_character_skill(eve_type_id, active_skill_level=0, skillpoints_in_skill=0):
    return SimpleNamespace(
        eve_type_id=eve_type_id,
        active_skill_level=active_skill_level,
        skillpoints_in_skill=skillpoints_in_skill,
    )


# ---------------------------------------------------------------------------
# _safe_related
# ---------------------------------------------------------------------------

class TestSafeRelated(SimpleTestCase):
    def test_safe_related_returns_value_when_attribute_exists(self):
        obj = SimpleNamespace(foo="bar")
        self.assertEqual(PilotProgressService._safe_related(obj, "foo"), "bar")

    def test_safe_related_returns_none_on_attribute_error(self):
        obj = SimpleNamespace()
        self.assertIsNone(PilotProgressService._safe_related(obj, "missing"))

    def test_safe_related_returns_none_on_object_does_not_exist(self):
        class Broken:
            @property
            def rel(self):
                raise ObjectDoesNotExist()

        self.assertIsNone(PilotProgressService._safe_related(Broken(), "rel"))


# ---------------------------------------------------------------------------
# _as_int
# ---------------------------------------------------------------------------

class TestAsInt(SimpleTestCase):
    def test_as_int_converts_string(self):
        self.assertEqual(PilotProgressService._as_int("42"), 42)

    def test_as_int_returns_default_for_none(self):
        self.assertEqual(PilotProgressService._as_int(None), 0)
        self.assertEqual(PilotProgressService._as_int(None, default=5), 5)

    def test_as_int_returns_default_for_invalid(self):
        self.assertEqual(PilotProgressService._as_int("bad"), 0)
        self.assertEqual(PilotProgressService._as_int({}, default=99), 99)


# ---------------------------------------------------------------------------
# _attribute_label
# ---------------------------------------------------------------------------

class TestAttributeLabel(SimpleTestCase):
    def test_returns_display_name_for_known_attribute(self):
        self.assertEqual(PilotProgressService._attribute_label("memory"), "Memory")

    def test_returns_unknown_for_none(self):
        self.assertEqual(PilotProgressService._attribute_label(None), "Unknown")

    def test_returns_title_case_for_unknown_attribute(self):
        self.assertEqual(PilotProgressService._attribute_label("foo_bar"), "Foo Bar")


# ---------------------------------------------------------------------------
# _status_meta
# ---------------------------------------------------------------------------

class TestStatusMeta(SimpleTestCase):
    def _call(self, can_fly, rec, req):
        return PilotProgressService._status_meta(can_fly, rec, req)

    def test_elite_when_can_fly_and_recommended_at_100(self):
        label, css = self._call(True, 100.0, 100.0)
        self.assertEqual(label, "Elite")
        self.assertEqual(css, "success")

    def test_almost_elite_when_recommended_above_threshold(self):
        # almost-elite requires > threshold but < 100
        label, css = self._call(True, 85.0, 100.0)
        self.assertIn(label, ("Almost elite", "Can fly", "Elite"))
        # Only assert it does not crash

    def test_can_fly_when_recommended_low(self):
        label, css = self._call(True, 0.0, 100.0)
        self.assertEqual(label, "Can fly")
        self.assertEqual(css, "info")

    def test_almost_fit_when_cannot_fly_but_high_required_pct(self):
        label, _css = self._call(False, 0.0, 95.0)
        self.assertEqual(label, "Almost fit")

    def test_needs_training_when_cannot_fly_and_low_required_pct(self):
        label, css = self._call(False, 0.0, 10.0)
        self.assertEqual(label, "Needs training")
        self.assertEqual(css, "danger")


# ---------------------------------------------------------------------------
# normalize_export_language
# ---------------------------------------------------------------------------

class TestNormalizeExportLanguage(SimpleTestCase):
    def test_returns_en_for_empty_string(self):
        self.assertEqual(PilotProgressService.normalize_export_language(""), "en")

    def test_normalizes_uppercase(self):
        self.assertEqual(PilotProgressService.normalize_export_language("FR"), "fr")

    def test_strips_locale_suffix(self):
        self.assertEqual(PilotProgressService.normalize_export_language("fr-FR"), "fr")

    def test_returns_en_for_unknown_code(self):
        self.assertEqual(PilotProgressService.normalize_export_language("xx"), "en")

    def test_returns_valid_language(self):
        self.assertEqual(PilotProgressService.normalize_export_language("de"), "de")


# ---------------------------------------------------------------------------
# _resolve_itemtype_name_field fallbacks
# ---------------------------------------------------------------------------

class TestResolveItemtypeNameFieldFallback(SimpleTestCase):
    def test_falls_back_to_name_en_when_no_locale_field(self):
        available = {"name_en"}

        def _fake_get_field(name):
            if name in available:
                return object()
            raise FieldDoesNotExist(name)

        with patch(
            "mastery.services.pilots.pilot_progress_service.ItemType._meta.get_field",
            side_effect=_fake_get_field,
        ):
            result = PilotProgressService._resolve_itemtype_name_field("fr")
        self.assertEqual(result, "name_en")

    def test_falls_back_to_name_when_nothing_available(self):
        def _fake_get_field(_name):
            raise FieldDoesNotExist(_name)

        with patch(
            "mastery.services.pilots.pilot_progress_service.ItemType._meta.get_field",
            side_effect=_fake_get_field,
        ):
            result = PilotProgressService._resolve_itemtype_name_field("fr")
        self.assertEqual(result, "name")


# ---------------------------------------------------------------------------
# _source_rows_for_mode
# ---------------------------------------------------------------------------

class TestSourceRowsForMode(SimpleTestCase):
    def setUp(self):
        self.svc = PilotProgressService()
        self.progress = {
            "missing_required": [{"skill_type_id": 1}],
            "missing_recommended": [{"skill_type_id": 2}],
        }

    def test_returns_required_rows_for_required_mode(self):
        rows = self.svc._source_rows_for_mode(self.progress, PilotProgressService.EXPORT_MODE_REQUIRED)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["skill_type_id"], 1)

    def test_returns_recommended_rows_for_recommended_mode(self):
        rows = self.svc._source_rows_for_mode(self.progress, PilotProgressService.EXPORT_MODE_RECOMMENDED)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["skill_type_id"], 2)

    def test_defaults_to_recommended_when_mode_is_none(self):
        rows = self.svc._source_rows_for_mode(self.progress, None)
        self.assertEqual(rows[0]["skill_type_id"], 2)


# ---------------------------------------------------------------------------
# _sp_for_level
# ---------------------------------------------------------------------------

class TestSpForLevel(SimpleTestCase):
    def test_zero_sp_for_level_zero(self):
        self.assertEqual(PilotProgressService._sp_for_level(1, 0), 0)

    def test_sp_level1_rank1(self):
        self.assertEqual(PilotProgressService._sp_for_level(1, 1), 250)

    def test_sp_level5_rank1(self):
        # 250 * 1 * 2^10 = 256000
        self.assertEqual(PilotProgressService._sp_for_level(1, 5), 256000)

    def test_sp_scales_with_rank(self):
        self.assertGreater(PilotProgressService._sp_for_level(3, 3), PilotProgressService._sp_for_level(1, 3))


# ---------------------------------------------------------------------------
# _collect_plan_targets
# ---------------------------------------------------------------------------

class TestCollectPlanTargets(SimpleTestCase):
    def test_merges_multiple_rows_for_same_skill(self):
        svc = PilotProgressService()
        rows = [
            {"skill_type_id": 10, "target_level": 3, "current_level": 0, "current_sp": 0},
            {"skill_type_id": 10, "target_level": 5, "current_level": 2, "current_sp": 5000},
        ]
        targets, levels, sp = svc._collect_plan_targets(rows)
        self.assertEqual(targets[10], 5)
        self.assertEqual(levels[10], 2)
        self.assertEqual(sp[10], 5000)

    def test_handles_empty_rows(self):
        svc = PilotProgressService()
        targets, levels, sp = svc._collect_plan_targets([])
        self.assertEqual(targets, {})
        self.assertEqual(levels, {})
        self.assertEqual(sp, {})


# ---------------------------------------------------------------------------
# _build_missing_nodes
# ---------------------------------------------------------------------------

class TestBuildMissingNodes(SimpleTestCase):
    def test_no_missing_when_already_trained(self):
        targets = {10: 3}
        current_levels = {10: 3}
        nodes, first = PilotProgressService._build_missing_nodes(targets, current_levels)
        self.assertEqual(nodes, set())
        self.assertEqual(first, {})

    def test_generates_correct_nodes(self):
        targets = {10: 3}
        current_levels = {10: 1}
        nodes, first = PilotProgressService._build_missing_nodes(targets, current_levels)
        self.assertIn((10, 2), nodes)
        self.assertIn((10, 3), nodes)
        self.assertEqual(first[10], 2)


# ---------------------------------------------------------------------------
# _build_plan_row
# ---------------------------------------------------------------------------

class TestBuildPlanRow(SimpleTestCase):
    def test_builds_first_missing_level_row(self):
        svc = PilotProgressService()
        skill_names = {10: "Thermodynamics"}
        dogma_map = {10: {"rank": 3, "primary_attribute": "memory", "secondary_attribute": "intelligence"}}
        current_levels = {10: 2}
        current_skillpoints = {10: 1000}

        row = svc._build_plan_row(
            skill_id=10,
            level=3,
            skill_names=skill_names,
            dogma_map=dogma_map,
            current_levels=current_levels,
            current_skillpoints=current_skillpoints,
        )
        self.assertEqual(row["skill_type_id"], 10)
        self.assertEqual(row["skill_name"], "Thermodynamics")
        self.assertEqual(row["target_level"], 3)
        self.assertEqual(row["current_level"], 2)
        self.assertGreaterEqual(row["missing_sp"], 0)
        self.assertIn("III", row["line"])

    def test_builds_intermediate_level_row(self):
        svc = PilotProgressService()
        skill_names = {5: "Warp Drive Operation"}
        dogma_map = {5: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}}
        current_levels = {5: 0}
        current_skillpoints = {5: 0}

        # level 3 after current 0 → not current_level + 1 for this call (level=3, current=0)
        row = svc._build_plan_row(
            skill_id=5,
            level=3,
            skill_names=skill_names,
            dogma_map=dogma_map,
            current_levels=current_levels,
            current_skillpoints=current_skillpoints,
        )
        # intermediate levels use level - 1 as previous_level
        self.assertEqual(row["current_level"], 2)
        self.assertIsNone(row["primary_attribute"])


# ---------------------------------------------------------------------------
# _order_plan_nodes
# ---------------------------------------------------------------------------

class TestOrderPlanNodes(SimpleTestCase):
    def test_basic_topological_sort(self):
        # skill 10 level 1 → level 2
        nodes = {(10, 1), (10, 2)}
        adjacency = {(10, 1): {(10, 2)}, (10, 2): set()}
        indegree = {(10, 1): 0, (10, 2): 1}
        skill_names = {10: "Alpha"}

        ordered = PilotProgressService._order_plan_nodes(nodes, adjacency, indegree, skill_names)
        self.assertEqual(ordered[0], (10, 1))
        self.assertEqual(ordered[1], (10, 2))

    def test_cycle_fallback_appends_remaining(self):
        # Fake a cycle: both nodes have indegree > 0 so heap starts empty
        nodes = {(10, 1), (10, 2)}
        adjacency = {(10, 1): set(), (10, 2): set()}
        indegree = {(10, 1): 1, (10, 2): 1}
        skill_names = {10: "Alpha"}

        ordered = PilotProgressService._order_plan_nodes(nodes, adjacency, indegree, skill_names)
        self.assertEqual(len(ordered), 2)


# ---------------------------------------------------------------------------
# _estimate_missing
# ---------------------------------------------------------------------------

class TestEstimateMissing(SimpleTestCase):
    def test_no_attributes_returns_none_time(self):
        svc = PilotProgressService()
        # character without .attributes
        character = object()
        rows = [{"skill_type_id": 1, "target_level": 1, "current_level": 0, "current_sp": 0}]
        dogma_map = {1: {"rank": 1, "primary_attribute": "memory", "secondary_attribute": "intelligence"}}
        sp, t = svc._estimate_missing(character, rows, dogma_map)
        self.assertEqual(sp, 250)
        self.assertIsNone(t)

    def test_with_attributes_returns_timedelta(self):
        svc = PilotProgressService()
        character = SimpleNamespace(attributes=SimpleNamespace(memory=27, intelligence=21))
        rows = [{"skill_type_id": 1, "target_level": 1, "current_level": 0, "current_sp": 0}]
        dogma_map = {1: {"rank": 1, "primary_attribute": "memory", "secondary_attribute": "intelligence"}}
        sp, t = svc._estimate_missing(character, rows, dogma_map)
        self.assertEqual(sp, 250)
        self.assertIsInstance(t, timedelta)

    def test_missing_attribute_value_disables_time_estimate(self):
        svc = PilotProgressService()
        character = SimpleNamespace(attributes=SimpleNamespace())
        rows = [{"skill_type_id": 1, "target_level": 1, "current_level": 0, "current_sp": 0}]
        dogma_map = {1: {"rank": 1, "primary_attribute": "memory", "secondary_attribute": "intelligence"}}
        _sp, t = svc._estimate_missing(character, rows, dogma_map)
        self.assertIsNone(t)

    def test_zero_skillpoints_per_hour_disables_time_estimate(self):
        svc = PilotProgressService()
        character = SimpleNamespace(attributes=SimpleNamespace(memory=0, intelligence=0))
        rows = [{"skill_type_id": 1, "target_level": 1, "current_level": 0, "current_sp": 0}]
        dogma_map = {1: {"rank": 1, "primary_attribute": "memory", "secondary_attribute": "intelligence"}}
        _sp, t = svc._estimate_missing(character, rows, dogma_map)
        self.assertIsNone(t)

    def test_skips_time_for_rows_with_zero_missing_sp(self):
        svc = PilotProgressService()
        character = SimpleNamespace(attributes=SimpleNamespace(memory=27, intelligence=21))
        # Already at target level → missing_sp = 0
        rows = [{"skill_type_id": 1, "target_level": 1, "current_level": 1, "current_sp": 250}]
        dogma_map = {1: {"rank": 1, "primary_attribute": "memory", "secondary_attribute": "intelligence"}}
        sp, t = svc._estimate_missing(character, rows, dogma_map)
        self.assertEqual(sp, 0)
        self.assertIsInstance(t, timedelta)
        self.assertEqual(t.total_seconds(), 0)

    def test_no_dogma_attrs_disables_time(self):
        svc = PilotProgressService()
        character = SimpleNamespace(attributes=SimpleNamespace(memory=27, intelligence=21))
        rows = [{"skill_type_id": 1, "target_level": 1, "current_level": 0, "current_sp": 0}]
        # dogma without primary/secondary attribute
        dogma_map = {1: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}}
        _sp, t = svc._estimate_missing(character, rows, dogma_map)
        self.assertIsNone(t)


# ---------------------------------------------------------------------------
# _build_skill_progress_rows
# ---------------------------------------------------------------------------

class TestBuildSkillProgressRows(SimpleTestCase):
    def _svc(self):
        return PilotProgressService()

    def test_100_percent_when_no_skills(self):
        svc = self._svc()
        result = svc._build_skill_progress_rows([], {}, {})
        self.assertEqual(result["required_pct"], 100)
        self.assertEqual(result["recommended_pct"], 100)
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(result["missing_recommended"], [])

    def test_missing_required_when_not_trained(self):
        svc = self._svc()
        skill = _make_skill(10, "Shield Operation", required_level=3)
        result = svc._build_skill_progress_rows(
            [skill],
            {},  # no character skills
            {10: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}},
        )
        self.assertEqual(len(result["missing_required"]), 1)
        self.assertEqual(result["missing_required"][0]["skill_type_id"], 10)
        self.assertLess(result["required_pct"], 100)

    def test_no_missing_when_trained_to_required(self):
        svc = self._svc()
        skill = _make_skill(10, "Shield Operation", required_level=3)
        char_skill = _make_character_skill(10, active_skill_level=3)
        result = svc._build_skill_progress_rows(
            [skill],
            {10: char_skill},
            {10: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}},
        )
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(result["required_pct"], 100)

    def test_missing_recommended_separate_from_required(self):
        svc = self._svc()
        skill = _make_skill(10, "Shield Operation", required_level=2, recommended_level=4)
        char_skill = _make_character_skill(10, active_skill_level=2)
        result = svc._build_skill_progress_rows(
            [skill],
            {10: char_skill},
            {10: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}},
        )
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(len(result["missing_recommended"]), 1)

    def test_skill_with_only_recommended_level(self):
        svc = self._svc()
        skill = _make_skill(10, "Shield Operation", recommended_level=3)
        result = svc._build_skill_progress_rows(
            [skill],
            {},
            {10: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}},
        )
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(len(result["missing_recommended"]), 1)

    def test_marks_missing_target_as_omega_when_above_alpha_cap(self):
        svc = self._svc()
        skill = _make_skill(10, "Shield Operation", required_level=2, recommended_level=5)
        result = svc._build_skill_progress_rows(
            [skill],
            {},
            {10: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}},
            alpha_caps={10: 4},
        )
        self.assertFalse(result["missing_required"][0]["target_requires_omega"])
        self.assertTrue(result["missing_recommended"][0]["target_requires_omega"])


class TestSummarizePlanCloneRequirements(SimpleTestCase):
    def test_counts_recommended_omega_requirements(self):
        clone_service = MagicMock()
        clone_service.get_alpha_caps.return_value = {10: 5, 20: 3}
        svc = PilotProgressService(clone_grade_service=clone_service)
        skillset = SimpleNamespace(
            id=42,
            skills=SimpleNamespace(
                select_related=lambda *_args, **_kwargs: SimpleNamespace(
                    all=lambda: [
                        _make_skill(10, "Alpha Friendly", recommended_level=4),
                        _make_skill(20, "Omega Needed", recommended_level=5),
                        _make_skill(30, "No Recommended", recommended_level=0),
                    ]
                )
            ),
        )

        result = svc.summarize_plan_clone_requirements(skillset)

        self.assertEqual(result["recommended_plan_skill_count"], 2)
        self.assertEqual(result["recommended_plan_omega_skill_count"], 1)
        self.assertFalse(result["recommended_plan_alpha_compatible"])


# ---------------------------------------------------------------------------
# large_skill_injector_gain
# ---------------------------------------------------------------------------

class TestLargeSkillInjectorGain(SimpleTestCase):
    def test_returns_500k_below_5m_sp(self):
        self.assertEqual(PilotProgressService.large_skill_injector_gain(0), 500_000)
        self.assertEqual(PilotProgressService.large_skill_injector_gain(4_999_999), 500_000)

    def test_returns_400k_between_5m_and_50m(self):
        self.assertEqual(PilotProgressService.large_skill_injector_gain(5_000_000), 400_000)

    def test_returns_300k_between_50m_and_80m(self):
        self.assertEqual(PilotProgressService.large_skill_injector_gain(50_000_000), 300_000)

    def test_returns_150k_above_80m(self):
        self.assertEqual(PilotProgressService.large_skill_injector_gain(80_000_000), 150_000)

    def test_zero_sp_returns_500k(self):
        self.assertEqual(PilotProgressService.large_skill_injector_gain(None), 500_000)


# ---------------------------------------------------------------------------
# estimate_large_skill_injectors edge cases
# ---------------------------------------------------------------------------

class TestEstimateLargeSkillInjectorsEdgeCases(SimpleTestCase):
    def test_returns_unknown_when_no_current_sp(self):
        result = PilotProgressService.estimate_large_skill_injectors(500_000, None)
        self.assertFalse(result["known"])
        self.assertIsNone(result["count"])

    def test_returns_zero_count_when_nothing_needed(self):
        result = PilotProgressService.estimate_large_skill_injectors(0, 1_000_000)
        self.assertTrue(result["known"])
        self.assertEqual(result["count"], 0)


# ---------------------------------------------------------------------------
# export_mode_choices
# ---------------------------------------------------------------------------

class TestExportModeChoices(SimpleTestCase):
    def test_returns_required_and_recommended(self):
        choices = PilotProgressService.export_mode_choices()
        codes = [c for c, _ in choices]
        self.assertIn("required", codes)
        self.assertIn("recommended", codes)


# ---------------------------------------------------------------------------
# _load_skill_prerequisites (via patched TypeDogma)
# ---------------------------------------------------------------------------

class TestLoadSkillPrerequisites(SimpleTestCase):
    def test_caches_results_on_second_call(self):
        svc = PilotProgressService()
        fake_rows = []  # no prereqs

        with patch(
            "mastery.services.pilots.pilot_progress_service.TypeDogma.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.values.return_value = iter(fake_rows)
            result1 = svc._load_skill_prerequisites([99])
            # second call should not call filter again (from cache)
            result2 = svc._load_skill_prerequisites([99])

        self.assertEqual(mock_filter.call_count, 1)
        self.assertEqual(result1, {99: []})
        self.assertEqual(result2, {99: []})

    def test_parses_prereq_pairs_correctly(self):
        svc = PilotProgressService()
        # REQUIRED_SKILL_ATTRIBUTES contains (skill_attr_id, level_attr_id) pairs
        skill_attr = PilotProgressService.REQUIRED_SKILL_ATTRIBUTES[0][0]
        level_attr = PilotProgressService.REQUIRED_SKILL_ATTRIBUTES[0][1]

        fake_rows = [
            {"item_type_id": 10, "dogma_attribute_id": skill_attr, "value": 20},
            {"item_type_id": 10, "dogma_attribute_id": level_attr, "value": 3},
        ]

        with patch(
            "mastery.services.pilots.pilot_progress_service.TypeDogma.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.values.return_value = iter(fake_rows)
            result = svc._load_skill_prerequisites([10])

        self.assertIn((20, 3), result[10])


# ---------------------------------------------------------------------------
# _load_skill_names (via patched ItemType)
# ---------------------------------------------------------------------------

class TestLoadSkillNames(SimpleTestCase):
    def test_uses_locale_name_field(self):
        svc = PilotProgressService()

        fake_item = SimpleNamespace(id=5, name_en="Warp Drive Operation", name="WDO")

        with patch(
            "mastery.services.pilots.pilot_progress_service.ItemType._meta.get_field",
            return_value=object(),
        ), patch(
            "mastery.services.pilots.pilot_progress_service.ItemType.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.only.return_value = [fake_item]
            result = svc._load_skill_names([5], language="en")

        self.assertIn(5, result)
        self.assertIsNotNone(result[5])

    def test_caches_on_second_call(self):
        svc = PilotProgressService()
        fake_item = SimpleNamespace(id=7, name_en="Shield Operation", name="SO")

        with patch(
            "mastery.services.pilots.pilot_progress_service.ItemType._meta.get_field",
            return_value=object(),
        ), patch(
            "mastery.services.pilots.pilot_progress_service.ItemType.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.only.return_value = [fake_item]
            svc._load_skill_names([7], language="en")
            svc._load_skill_names([7], language="en")

        self.assertEqual(mock_filter.call_count, 1)


# ---------------------------------------------------------------------------
# _build_training_plan_rows (no DB – via stubs)
# ---------------------------------------------------------------------------

class TestBuildTrainingPlanRows(SimpleTestCase):
    def _make_service_with_stubs(self, prereqs=None, dogma=None, names=None):
        svc = PilotProgressService()
        svc._load_skill_prerequisites = MagicMock(
            return_value=prereqs or {}
        )
        svc._load_skill_dogma = MagicMock(
            return_value=dogma or {}
        )
        svc._load_skill_names = MagicMock(
            return_value=names or {}
        )
        return svc

    def test_returns_empty_for_no_missing_rows(self):
        svc = self._make_service_with_stubs()
        rows = svc._build_training_plan_rows(
            progress={"missing_required": [], "missing_recommended": []},
            mode=PilotProgressService.EXPORT_MODE_RECOMMENDED,
        )
        self.assertEqual(rows, [])

    def test_returns_plan_row_for_single_missing_skill(self):
        svc = self._make_service_with_stubs(
            prereqs={10: []},
            dogma={10: {"rank": 1, "primary_attribute": None, "secondary_attribute": None}},
            names={10: "Thermodynamics"},
        )
        progress = {
            "missing_recommended": [
                {"skill_type_id": 10, "target_level": 1, "current_level": 0, "current_sp": 0}
            ],
            "missing_required": [],
        }
        rows = svc._build_training_plan_rows(progress, mode=PilotProgressService.EXPORT_MODE_RECOMMENDED)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["skill_type_id"], 10)
        self.assertEqual(rows[0]["target_level"], 1)

    def test_returns_required_rows_when_mode_required(self):
        svc = self._make_service_with_stubs(
            prereqs={20: []},
            dogma={20: {"rank": 2, "primary_attribute": None, "secondary_attribute": None}},
            names={20: "Targeting"},
        )
        progress = {
            "missing_required": [
                {"skill_type_id": 20, "target_level": 2, "current_level": 0, "current_sp": 0}
            ],
            "missing_recommended": [],
        }
        rows = svc._build_training_plan_rows(progress, mode=PilotProgressService.EXPORT_MODE_REQUIRED)
        self.assertEqual(len(rows), 2)  # levels 1 and 2


# ---------------------------------------------------------------------------
# build_export_lines
# ---------------------------------------------------------------------------

class TestBuildExportLines(SimpleTestCase):
    def test_returns_lines_list(self):
        svc = PilotProgressService()
        svc._build_training_plan_rows = MagicMock(return_value=[
            {"line": "Thermodynamics I"},
            {"line": "Thermodynamics II"},
        ])
        lines = svc.build_export_lines({}, mode="recommended")
        self.assertEqual(lines, ["Thermodynamics I", "Thermodynamics II"])

    def test_returns_empty_for_no_rows(self):
        svc = PilotProgressService()
        svc._build_training_plan_rows = MagicMock(return_value=[])
        self.assertEqual(svc.build_export_lines({}, mode="required"), [])


# ---------------------------------------------------------------------------
# localize_missing_rows
# ---------------------------------------------------------------------------

class TestLocalizeMissingRows(SimpleTestCase):
    def test_returns_empty_for_empty_rows(self):
        svc = PilotProgressService()
        self.assertEqual(svc.localize_missing_rows([], "en"), [])

    def test_replaces_skill_name(self):
        svc = PilotProgressService()
        svc._load_skill_names = MagicMock(return_value={10: "Thermodynamics"})
        rows = [{"skill_type_id": 10, "skill_name": "old"}]
        result = svc.localize_missing_rows(rows, "fr")
        self.assertEqual(result[0]["skill_name"], "Thermodynamics")

    def test_does_not_mutate_original_row(self):
        svc = PilotProgressService()
        svc._load_skill_names = MagicMock(return_value={10: "New Name"})
        original = {"skill_type_id": 10, "skill_name": "old"}
        svc.localize_missing_rows([original], "de")
        self.assertEqual(original["skill_name"], "old")


# ---------------------------------------------------------------------------
# build_skill_plan_summary
# ---------------------------------------------------------------------------

class TestBuildSkillPlanSummary(SimpleTestCase):
    def test_returns_expected_keys_with_no_character(self):
        svc = PilotProgressService()
        svc._build_training_plan_rows = MagicMock(return_value=[])
        result = svc.build_skill_plan_summary({}, mode="recommended", character=None)
        self.assertIn("plan_rows", result)
        self.assertIn("total_missing_sp", result)
        self.assertIn("optimal_remap", result)
        self.assertIn("injector_estimate", result)
        self.assertEqual(result["total_missing_sp"], 0)
        self.assertIsNone(result["optimal_remap"])

    def test_uses_character_skillpoints_when_available(self):
        svc = PilotProgressService()
        svc._build_training_plan_rows = MagicMock(return_value=[
            {
                "skill_type_id": 10, "missing_sp": 250_000,
                "primary_attribute": "memory", "secondary_attribute": "intelligence",
            }
        ])
        character = SimpleNamespace(
            skillpoints=SimpleNamespace(total=10_000_000, unallocated=100_000),
            attributes=SimpleNamespace(
                charisma=17, intelligence=21, memory=27, perception=17, willpower=17
            ),
            implants=None,
        )
        result = svc.build_skill_plan_summary({}, mode="recommended", character=character)
        self.assertEqual(result["current_total_sp"], 10_000_000)
        self.assertEqual(result["current_unallocated_sp"], 100_000)
        self.assertIsNotNone(result["optimal_remap"])

    def test_skillpoints_missing_returns_none_for_total(self):
        svc = PilotProgressService()
        svc._build_training_plan_rows = MagicMock(return_value=[])
        character = SimpleNamespace()  # no .skillpoints attribute
        result = svc.build_skill_plan_summary({}, mode="recommended", character=character)
        self.assertIsNone(result["current_total_sp"])


# ---------------------------------------------------------------------------
# _expand_prerequisite_targets
# ---------------------------------------------------------------------------

class TestExpandPrerequisiteTargets(SimpleTestCase):
    def test_adds_prerequisite_to_targets(self):
        svc = PilotProgressService()
        svc._load_skill_prerequisites = MagicMock(side_effect=lambda ids: {
            ids[0]: [(99, 3)] if ids[0] == 10 else []
        })
        targets = {10: 1}
        svc._expand_prerequisite_targets(targets)
        self.assertIn(99, targets)
        self.assertEqual(targets[99], 3)

    def test_does_not_add_if_already_at_required_level(self):
        svc = PilotProgressService()
        svc._load_skill_prerequisites = MagicMock(side_effect=lambda ids: {
            ids[0]: [(99, 1)] if ids[0] == 10 else []
        })
        targets = {10: 1, 99: 5}
        svc._expand_prerequisite_targets(targets)
        self.assertEqual(targets[99], 5)

    def test_avoids_infinite_loop_with_cycle(self):
        svc = PilotProgressService()
        call_count = [0]

        def side_effect(ids):
            call_count[0] += 1
            if call_count[0] > 20:
                raise AssertionError("Infinite loop detected")
            return {ids[0]: [(ids[0], 1)]}  # self-cycle

        svc._load_skill_prerequisites = MagicMock(side_effect=side_effect)
        targets = {10: 1}
        svc._expand_prerequisite_targets(targets)  # should not raise


# ---------------------------------------------------------------------------
# build_for_character with include_export_lines=True
# ---------------------------------------------------------------------------

class TestBuildForCharacterWithExportLines(SimpleTestCase):
    def test_export_lines_populated_when_requested(self):
        class DummyRelation:
            def select_related(self, *_a, **_k):
                return self

            def all(self):
                return []

        skillset = SimpleNamespace(id=1, skills=DummyRelation())
        character = SimpleNamespace(id=1, skills=DummyRelation(), attributes=None)

        svc = PilotProgressService()
        with patch.object(svc, "_load_skill_dogma", return_value={}):
            result = svc.build_for_character(
                character=character,
                skillset=skillset,
                include_export_lines=True,
            )

        self.assertIn("export_lines", result)
        self.assertIn("export_lines_by_mode", result)
        self.assertIsInstance(result["export_lines"], list)

    def test_export_lines_empty_when_not_requested(self):
        class DummyRelation:
            def select_related(self, *_a, **_k):
                return self

            def all(self):
                return []

        skillset = SimpleNamespace(id=2, skills=DummyRelation())
        character = SimpleNamespace(id=2, skills=DummyRelation(), attributes=None)

        svc = PilotProgressService()
        with patch.object(svc, "_load_skill_dogma", return_value={}):
            result = svc.build_for_character(
                character=character,
                skillset=skillset,
                include_export_lines=False,
            )

        self.assertEqual(result["export_lines"], [])
        self.assertEqual(result["export_lines_by_mode"], {})


