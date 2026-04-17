from datetime import datetime, timezone
from collections import defaultdict
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from mastery.services.doctrine.doctrine_skill_service import DoctrineSkillService
from mastery.services.doctrine.doctrine_map_service import DoctrineMapService
from mastery.services.fittings.approval_service import FittingApprovalService
from mastery.services.fittings.skill_extractor import FittingSkillExtractor
from mastery.services.fittings.fitting_map_service import FittingMapService
from mastery.services.pilots.pilot_access_service import PilotAccessService
from mastery.services.sde.mastery_service import MasteryService
from mastery.services.sde.version_service import SdeVersionService
from mastery.services.skill_requirements import merge_skill_maps, normalize_default_skill_map
from mastery.services.skills.skill_control_service import SkillControlService
from mastery.services.skills.skillcheck_service import SkillCheckService
from mastery.services.skills.suggestion_service import SkillSuggestionService


class TestSdeVersionService(SimpleTestCase):
    @patch("mastery.services.sde.version_service.requests.get")
    def test_fetch_latest_parses_payload(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "buildNumber": 42,
            "releaseDate": "2026-04-15T12:30:00+00:00",
        }
        mock_get.return_value = response

        result = SdeVersionService().fetch_latest()

        self.assertEqual(result["build_number"], 42)
        self.assertEqual(result["release_date"], datetime(2026, 4, 15, 12, 30, tzinfo=timezone.utc))
        response.raise_for_status.assert_called_once_with()

    @patch.object(SdeVersionService, "get_current", return_value=None)
    @patch.object(SdeVersionService, "fetch_latest", return_value={"build_number": 5})
    def test_is_up_to_date_false_when_no_current(self, _mock_fetch, _mock_current):
        self.assertFalse(SdeVersionService().is_up_to_date())

    @patch.object(SdeVersionService, "get_current", return_value=Mock(build_number=5))
    @patch.object(SdeVersionService, "fetch_latest", return_value={"build_number": 5})
    def test_is_up_to_date_true_when_build_matches(self, _mock_fetch, _mock_current):
        self.assertTrue(SdeVersionService().is_up_to_date())

    @patch.object(SdeVersionService, "get_current", return_value=Mock(build_number=4))
    @patch.object(SdeVersionService, "fetch_latest", return_value={"build_number": 5})
    def test_is_up_to_date_false_when_build_differs(self, _mock_fetch, _mock_current):
        self.assertFalse(SdeVersionService().is_up_to_date())


class TestMasteryService(SimpleTestCase):
    @patch("mastery.services.sde.mastery_service.CertificateSkill.objects.filter")
    @patch("mastery.services.sde.mastery_service.ShipMasteryCertificate.objects.filter")
    def test_get_ship_skills_filters_empty_levels_and_uses_cache(self, mock_mastery_filter, mock_skill_filter):
        mock_mastery_filter.return_value.values_list.return_value = [1, 2]
        mock_skill_filter.return_value.values.return_value = [
            {"skill_type_id": 10, "level_elite": 5},
            {"skill_type_id": 11, "level_elite": 0},
            {"skill_type_id": 12, "level_elite": None},
        ]

        service = MasteryService()
        first = service.get_ship_skills(ship_type_id=177, mastery_level=4)
        second = service.get_ship_skills(ship_type_id=177, mastery_level=4)

        self.assertEqual(first, {10: 5})
        self.assertEqual(second, {10: 5})
        mock_skill_filter.assert_called_once()


class TestDoctrineAndFittingMapServices(SimpleTestCase):
    @patch("mastery.services.doctrine.doctrine_map_service.DoctrineSkillSetGroupMap.objects.filter")
    def test_create_doctrine_map_returns_existing_map(self, mock_filter):
        existing_map = Mock()
        mock_filter.return_value.first.return_value = existing_map

        service = DoctrineMapService(doctrine_skill_service=Mock())
        result = service.create_doctrine_map(doctrine=Mock())

        self.assertIs(result, existing_map)

    @patch("mastery.services.doctrine.doctrine_map_service.DoctrineSkillSetGroupMap.objects.update_or_create")
    @patch("mastery.services.doctrine.doctrine_map_service.SkillSetGroup.objects.get_or_create")
    @patch("mastery.services.doctrine.doctrine_map_service.DoctrineSkillSetGroupMap.objects.filter")
    def test_create_doctrine_map_creates_and_syncs_when_missing(
        self,
        mock_filter,
        mock_group_get_or_create,
        mock_update_or_create,
    ):
        doctrine = Mock(name="Doctrine", description="desc")
        mock_filter.return_value.first.return_value = None
        group = Mock()
        mock_group_get_or_create.return_value = (group, True)
        doctrine_map = Mock()
        mock_update_or_create.return_value = (doctrine_map, True)

        service = DoctrineMapService(doctrine_skill_service=Mock())
        with patch.object(service, "sync") as mock_sync:
            result = service.create_doctrine_map(doctrine=doctrine)

        self.assertIs(result, doctrine_map)
        mock_group_get_or_create.assert_called_once_with(
            name=doctrine.name,
            defaults={
                "is_doctrine": True,
                "is_active": True,
                "description": doctrine.description,
            },
        )
        mock_update_or_create.assert_called_once_with(
            doctrine=doctrine,
            defaults={"skillset_group": group},
        )
        mock_sync.assert_called_once_with(doctrine)

    @patch("mastery.services.doctrine.doctrine_map_service.DoctrineSkillSetGroupMap.objects.update_or_create")
    @patch("mastery.services.doctrine.doctrine_map_service.SkillSetGroup.objects.get_or_create")
    @patch("mastery.services.doctrine.doctrine_map_service.DoctrineSkillSetGroupMap.objects.filter")
    def test_create_doctrine_map_reuses_existing_group_name(self, mock_filter, mock_group_get_or_create, mock_update_or_create):
        doctrine = Mock(name="COMBAT FLEET", description="desc")
        mock_filter.return_value.first.return_value = None
        existing_group = Mock()
        mock_group_get_or_create.return_value = (existing_group, False)
        doctrine_map = Mock()
        mock_update_or_create.return_value = (doctrine_map, False)

        service = DoctrineMapService(doctrine_skill_service=Mock())
        with patch.object(service, "sync") as mock_sync:
            result = service.create_doctrine_map(doctrine=doctrine)

        self.assertIs(result, doctrine_map)
        mock_group_get_or_create.assert_called_once()
        mock_update_or_create.assert_called_once_with(
            doctrine=doctrine,
            defaults={"skillset_group": existing_group},
        )
        mock_sync.assert_called_once_with(doctrine)

    @patch("mastery.services.fittings.fitting_map_service.FittingSkillsetMap.objects.filter")
    def test_create_fitting_map_returns_existing_map(self, mock_filter):
        existing_map = Mock()
        mock_filter.return_value.first.return_value = existing_map

        result = FittingMapService.create_fitting_map(doctrine_map=Mock(), fitting=Mock())

        self.assertIs(result, existing_map)

    @patch("mastery.services.fittings.fitting_map_service.FittingSkillsetMap.objects.create")
    @patch("mastery.services.fittings.fitting_map_service.SkillSet.objects.create")
    @patch("mastery.services.fittings.fitting_map_service.FittingSkillsetMap.objects.filter")
    def test_create_fitting_map_creates_skillset_and_map(self, mock_filter, mock_skillset_create, mock_map_create):
        fitting = Mock(name="Fit", description="desc", ship_type_type_id=587)
        doctrine_map = Mock()
        doctrine_map.skillset_group.skill_sets.add = Mock()
        mock_filter.return_value.first.return_value = None
        skillset = Mock()
        mock_skillset_create.return_value = skillset
        fitting_map = Mock()
        mock_map_create.return_value = fitting_map

        result = FittingMapService.create_fitting_map(doctrine_map=doctrine_map, fitting=fitting)

        self.assertIs(result, fitting_map)
        doctrine_map.skillset_group.skill_sets.add.assert_called_once_with(skillset)
        mock_map_create.assert_called_once()


class TestFittingApprovalService(SimpleTestCase):
    @patch("mastery.services.fittings.approval_service.timezone.now", return_value="2026-04-16T00:00:00Z")
    def test_mark_modified_clears_existing_approval_and_records_modifier(self, mock_now):
        fitting_map = Mock()

        result = FittingApprovalService.mark_modified(
            fitting_map,
            user=SimpleNamespace(username="editor"),
            status="in_progress",
        )

        self.assertIs(result, fitting_map)
        self.assertEqual(fitting_map.status, "in_progress")
        self.assertIsNone(fitting_map.approved_by)
        self.assertIsNone(fitting_map.approved_at)
        self.assertEqual(fitting_map.modified_by.username, "editor")
        self.assertEqual(fitting_map.modified_at, mock_now.return_value)
        fitting_map.save.assert_called_once_with(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "modified_by",
                "modified_at",
            ]
        )

    @patch("mastery.services.fittings.approval_service.timezone.now", return_value="2026-04-16T00:00:00Z")
    def test_approve_sets_approved_status_and_audit_fields(self, mock_now):
        fitting_map = Mock()
        approver = SimpleNamespace(username="reviewer")

        result = FittingApprovalService.approve(fitting_map, user=approver)

        self.assertIs(result, fitting_map)
        self.assertEqual(fitting_map.status, "approved")
        self.assertIs(fitting_map.approved_by, approver)
        self.assertEqual(fitting_map.approved_at, mock_now.return_value)
        fitting_map.save.assert_called_once_with(update_fields=["status", "approved_by", "approved_at"])


class TestFittingSkillExtractor(SimpleTestCase):
    def test_expand_required_skill_tree_recurses_and_keeps_highest_level(self):
        extractor = FittingSkillExtractor()

        with patch.object(
            extractor,
            "get_required_skills_for_type",
            side_effect=lambda type_id: {
                10: {1: {"l": 2}, 2: {"l": 1}},
                1: {3: {"l": 4}},
                2: {3: {"l": 2}},
                3: {},
            }.get(type_id, {}),
        ):
            result = extractor._expand_required_skill_tree({10: 3, 99: 0})

        self.assertEqual(result, {10: 3, 1: 2, 2: 1, 3: 4})

    def test_get_required_skills_for_fitting_merges_ship_and_modules_before_expanding(self):
        extractor = FittingSkillExtractor()
        fitting = Mock(ship_type_type_id=500)
        fitting.items.all.return_value = [Mock(type_id=600), Mock(type_id=601)]

        skill_map = {
            500: {1: {"l": 2}},
            600: {1: {"l": 3}, 2: {"l": 1}},
            601: {3: {"l": 4}},
        }

        with patch.object(
            extractor,
            "get_required_skills_for_type",
            side_effect=lambda type_id: skill_map.get(type_id, {}),
        ) as mock_get_required, patch.object(
            extractor,
            "_expand_required_skill_tree",
            side_effect=lambda skills: {**skills, 99: 5},
        ) as mock_expand:
            result = extractor.get_required_skills_for_fitting(fitting)

        self.assertEqual(result, {1: 3, 2: 1, 3: 4, 99: 5})
        self.assertEqual(mock_get_required.call_count, 3)
        mock_expand.assert_called_once_with({1: 3, 2: 1, 3: 4})

    @patch("mastery.services.fittings.skill_extractor.ItemType.objects.filter")
    @patch("mastery.services.fittings.skill_extractor.TypeDogma.objects.filter")
    def test_get_required_skills_for_type_builds_result_and_uses_cache(self, mock_dogma_filter, mock_itemtype_filter):
        extractor = FittingSkillExtractor()
        mock_dogma_filter.return_value = [
            Mock(item_type_id=700, dogma_attribute_id=182, value=1001),
            Mock(item_type_id=700, dogma_attribute_id=277, value=2),
            Mock(item_type_id=700, dogma_attribute_id=183, value=1002),
            Mock(item_type_id=700, dogma_attribute_id=278, value=4),
            Mock(item_type_id=700, dogma_attribute_id=277, value=1),
        ]
        mock_itemtype_filter.return_value = [
            SimpleNamespace(id=1001, name="Skill A"),
            SimpleNamespace(id=1002, name="Skill B"),
        ]

        first = extractor.get_required_skills_for_type(700)
        second = extractor.get_required_skills_for_type(700)

        self.assertEqual(
            first,
            {
                1001: {"s": 1001, "l": 2, "n": "Skill A"},
                1002: {"s": 1002, "l": 4, "n": "Skill B"},
            },
        )
        self.assertEqual(second, first)
        mock_dogma_filter.assert_called_once()
        mock_itemtype_filter.assert_called_once()


class TestSkillSuggestionService(SimpleTestCase):
    @patch("mastery.services.skills.suggestion_service.ItemType.objects.select_related")
    def test_get_group_uses_cache(self, mock_select_related):
        item = Mock()
        mock_select_related.return_value.get.return_value = item
        service = SkillSuggestionService()

        first = service.get_group(55)
        second = service.get_group(55)

        self.assertIs(first, item)
        self.assertIs(second, item)
        mock_select_related.return_value.get.assert_called_once_with(id=55)

    def test_detect_features_uses_group_mapping_and_category_fallback(self):
        service = SkillSuggestionService()
        fitting = Mock()
        fitting.items.select_related.return_value.all.return_value = [
            Mock(type_fk=Mock(group=Mock(id=77, category=Mock(id=0)))),
            Mock(type_fk=Mock(group=Mock(id=999, category=Mock(id=18)))),
        ]

        features = service.detect_features(fitting)

        self.assertTrue(features["shield"])
        self.assertTrue(features["drones"])

    def test_suggest_removes_unused_or_non_required_feature_skills(self):
        service = SkillSuggestionService()
        fitting = Mock()
        engineering_item = SimpleNamespace(group=SimpleNamespace(name="Engineering"), group_id=1210)
        armor_item = SimpleNamespace(group=SimpleNamespace(name="Armor"), group_id=1211)
        missiles_item = SimpleNamespace(group=SimpleNamespace(name="Missiles"), group_id=255)

        with patch.object(
            service,
            "detect_features",
            return_value=defaultdict(bool, {"missiles": True}),
        ), patch.object(
            service,
            "get_group",
            side_effect=lambda skill_type_id: {
                1: engineering_item,
                2: armor_item,
                3: missiles_item,
                4: None,
            }[skill_type_id],
        ):
            result = service.suggest(
                fitting=fitting,
                skills={1: 5, 2: 4, 3: 3, 4: 2},
                fitting_required_skills={999: 1},
            )

        self.assertNotIn(1, result)
        self.assertEqual(result[2]["action"], "remove")
        self.assertIn("Armor not used in fitting", result[2]["reason"])
        self.assertEqual(result[3]["action"], "remove")
        self.assertIn("no module requires this specific skill", result[3]["reason"])
        self.assertNotIn(4, result)


class TestSkillCheckService(SimpleTestCase):
    @patch("mastery.services.skills.skillcheck_service.CharacterSkillSetCheck.objects.filter")
    def test_get_character_progress_returns_none_when_no_check(self, mock_filter):
        mock_filter.return_value.first.return_value = None

        result = SkillCheckService.get_character_progress(character=Mock(), skillset=Mock())

        self.assertIsNone(result)

    @patch("mastery.services.skills.skillcheck_service.SkillSetSkill.objects.filter")
    @patch("mastery.services.skills.skillcheck_service.CharacterSkillSetCheck.objects.filter")
    def test_get_character_progress_computes_percentages(self, mock_check_filter, mock_skill_filter):
        check = Mock()
        check.failed_required_skills.count.return_value = 1
        check.failed_recommended_skills.count.return_value = 2
        mock_check_filter.return_value.first.return_value = check

        required_qs = Mock()
        required_qs.count.return_value = 4
        recommended_qs = Mock()
        recommended_qs.count.return_value = 5
        mock_skill_filter.side_effect = [required_qs, recommended_qs]

        result = SkillCheckService.get_character_progress(character=Mock(), skillset=Mock())

        self.assertEqual(result["failed_required"], 1)
        self.assertEqual(result["failed_recommended"], 2)
        self.assertEqual(result["required_pct"], 75.0)
        self.assertEqual(result["recommended_pct"], 60.0)


class TestPilotAccessService(SimpleTestCase):
    def test_accessible_fitting_ids_returns_empty_without_permission(self):
        user = Mock()
        user.has_perm.side_effect = lambda perm: False

        result = PilotAccessService().accessible_fitting_ids(user)

        self.assertEqual(result, set())

    @patch("mastery.services.pilots.pilot_access_service.Fitting.objects.values_list")
    def test_accessible_fitting_ids_returns_all_for_manage_permission(self, mock_values_list):
        user = Mock()
        user.has_perm.side_effect = lambda perm: perm == "fittings.manage"
        mock_values_list.return_value = [1, 2, 3]

        result = PilotAccessService().accessible_fitting_ids(user)

        self.assertEqual(result, {1, 2, 3})

    @patch("mastery.services.pilots.pilot_access_service.Fitting.objects.filter")
    @patch.object(PilotAccessService, "_accessible_category_ids", return_value={10, 11})
    def test_accessible_fitting_ids_filters_by_accessible_categories(self, _mock_categories, mock_filter):
        user = Mock()
        user.has_perm.side_effect = lambda perm: perm == "fittings.access_fittings"
        mock_filter.return_value.distinct.return_value.values_list.return_value = [4, 5]

        result = PilotAccessService().accessible_fitting_ids(user)

        self.assertEqual(result, {4, 5})

    @patch("mastery.services.pilots.pilot_access_service.Category.objects.filter")
    @patch("mastery.services.pilots.pilot_access_service.Category.objects.values_list")
    def test_accessible_category_ids_returns_all_for_manage_permission(self, mock_values_list, _mock_filter):
        user = Mock()
        user.has_perm.side_effect = lambda perm: perm == "fittings.manage"
        mock_values_list.return_value = [7, 8]

        result = PilotAccessService._accessible_category_ids(user)

        self.assertEqual(result, {7, 8})

    @patch("mastery.services.pilots.pilot_access_service.Category.objects.filter")
    def test_accessible_category_ids_combines_public_and_group_categories(self, mock_filter):
        user = Mock()
        user.has_perm.side_effect = lambda perm: False
        user.groups.all.return_value = [Mock()]

        public_qs = Mock()
        public_qs.values_list.return_value = [1, 2]
        group_qs = Mock()
        group_qs.values_list.return_value = [2, 3]
        mock_filter.side_effect = [public_qs, group_qs]

        result = PilotAccessService._accessible_category_ids(user)

        self.assertEqual(result, {1, 2, 3})

    def test_accessible_doctrines_returns_none_without_permission(self):
        user = Mock()
        user.has_perm.side_effect = lambda perm: False
        qs = Mock()
        ordered_qs = Mock()
        ordered_qs.none.return_value = "none"
        qs.order_by.return_value = ordered_qs

        with patch("mastery.services.pilots.pilot_access_service.Doctrine.objects.prefetch_related", return_value=qs):
            result = PilotAccessService().accessible_doctrines(user)

        self.assertEqual(result, "none")

    def test_accessible_doctrines_returns_prefetched_qs_for_manage_permission(self):
        user = Mock()
        user.has_perm.side_effect = lambda perm: perm == "fittings.manage"
        qs = Mock()
        ordered_qs = Mock()
        qs.order_by.return_value = ordered_qs

        with patch("mastery.services.pilots.pilot_access_service.Doctrine.objects.prefetch_related", return_value=qs):
            result = PilotAccessService().accessible_doctrines(user)

        self.assertIs(result, ordered_qs)


class TestDoctrineSkillService(SimpleTestCase):
    def test_resolve_effective_mastery_level_prefers_explicit_then_fitting_then_doctrine(self):
        doctrine_map = SimpleNamespace(default_mastery_level=4)
        fitting_map = SimpleNamespace(mastery_level=2)

        self.assertEqual(
            DoctrineSkillService._resolve_effective_mastery_level(doctrine_map, fitting_map, mastery_level=1),
            1,
        )
        self.assertEqual(
            DoctrineSkillService._resolve_effective_mastery_level(doctrine_map, fitting_map, mastery_level=None),
            2,
        )
        self.assertEqual(
            DoctrineSkillService._resolve_effective_mastery_level(doctrine_map, None, mastery_level=None),
            4,
        )

    def test_preview_fitting_builds_rows_and_normalizes_suggestions(self):
        extractor = Mock()
        extractor.get_required_skills_for_fitting.return_value = {1: 3, 2: 1}
        mastery_service = Mock()
        mastery_service.get_ship_skills.return_value = {2: 4, 3: 2}
        control_service = Mock()
        control_service.get_blacklist.return_value = {3}
        control_service.get_controls_map.return_value = {
            2: {"recommended_level_override": 5, "is_manual": True},
            4: {"recommended_level_override": 1, "is_manual": False},
        }
        suggestion_service = Mock()
        suggestion_service.suggest.return_value = {
            3: {"action": "remove", "reason": "unused", "group": "Missiles"},
            4: {"action": "add", "reason": "restore", "group": "Armor"},
        }
        fitting_map_service = Mock()
        fitting_map = SimpleNamespace(mastery_level=2)
        fitting_map_service.create_fitting_map.return_value = fitting_map

        service = DoctrineSkillService(
            extractor=extractor,
            mastery_service=mastery_service,
            control_service=control_service,
            suggestion_service=suggestion_service,
            fitting_map_service=fitting_map_service,
            approval_service=Mock(),
        )
        fitting = SimpleNamespace(id=55, ship_type_type_id=9001)
        doctrine_map = SimpleNamespace(default_mastery_level=4)

        result = service.preview_fitting(doctrine_map=doctrine_map, fitting=fitting)

        self.assertEqual(result["effective_mastery_level"], 2)
        rows = {row["skill_type_id"]: row for row in result["skill_rows"]}
        self.assertEqual(rows[1]["recommended_level"], 3)
        self.assertEqual(rows[2]["recommended_level_override"], 5)
        self.assertEqual(rows[2]["recommended_level"], 5)
        self.assertTrue(rows[2]["is_manual"])
        self.assertTrue(rows[3]["is_blacklisted"])
        self.assertTrue(rows[3]["is_suggested"])
        self.assertEqual(rows[3]["suggestion_action"], "add")
        self.assertFalse(rows[4]["is_suggested"])
        self.assertEqual(result["suggestions"], {
            3: {
                "action": "add",
                "reason": "Skill is required/recommended for this fitting at the selected mastery level",
                "group": None,
            }
        })

    @patch("mastery.services.doctrine.doctrine_skill_service.app_settings.MASTERY_DEFAULT_SKILLS", [{"type_id": 28164, "required_level": 1}])
    def test_preview_fitting_injects_default_skills_into_required_map(self):
        extractor = Mock()
        extractor.get_required_skills_for_fitting.return_value = {1: 3}
        mastery_service = Mock()
        mastery_service.get_ship_skills.return_value = {}
        control_service = Mock()
        control_service.get_blacklist.return_value = set()
        control_service.get_controls_map.return_value = {}
        suggestion_service = Mock()
        suggestion_service.suggest.return_value = {}
        fitting_map_service = Mock()
        fitting_map_service.create_fitting_map.return_value = SimpleNamespace(mastery_level=None)

        service = DoctrineSkillService(
            extractor=extractor,
            mastery_service=mastery_service,
            control_service=control_service,
            suggestion_service=suggestion_service,
            fitting_map_service=fitting_map_service,
            approval_service=Mock(),
        )

        result = service.preview_fitting(
            doctrine_map=SimpleNamespace(default_mastery_level=4),
            fitting=SimpleNamespace(id=55, ship_type_type_id=9001),
        )

        rows = {row["skill_type_id"]: row for row in result["skill_rows"]}
        self.assertIn(28164, rows)
        self.assertEqual(rows[28164]["required_level"], 1)
        self.assertEqual(rows[28164]["recommended_level"], 1)

    @patch("mastery.services.doctrine.doctrine_skill_service.app_settings.MASTERY_DEFAULT_SKILLS", [{"type_id": 1, "required_level": 2}])
    def test_preview_fitting_keeps_highest_required_level_when_default_skill_already_exists(self):
        extractor = Mock()
        extractor.get_required_skills_for_fitting.return_value = {1: 4}
        mastery_service = Mock()
        mastery_service.get_ship_skills.return_value = {}
        control_service = Mock()
        control_service.get_blacklist.return_value = set()
        control_service.get_controls_map.return_value = {}
        suggestion_service = Mock()
        suggestion_service.suggest.return_value = {}
        fitting_map_service = Mock()
        fitting_map_service.create_fitting_map.return_value = SimpleNamespace(mastery_level=None)

        service = DoctrineSkillService(
            extractor=extractor,
            mastery_service=mastery_service,
            control_service=control_service,
            suggestion_service=suggestion_service,
            fitting_map_service=fitting_map_service,
            approval_service=Mock(),
        )

        result = service.preview_fitting(
            doctrine_map=SimpleNamespace(default_mastery_level=4),
            fitting=SimpleNamespace(id=55, ship_type_type_id=9001),
        )

        rows = {row["skill_type_id"]: row for row in result["skill_rows"]}
        self.assertEqual(rows[1]["required_level"], 4)


class TestSkillRequirementsHelpers(SimpleTestCase):
    def test_normalize_default_skill_map_returns_empty_for_invalid_container(self):
        self.assertEqual(normalize_default_skill_map("invalid"), {})

    def test_normalize_default_skill_map_ignores_invalid_entries_and_keeps_highest_level(self):
        result = normalize_default_skill_map(
            [
                {"type_id": 10, "required_level": 2},
                {"type_id": 10, "required_level": 4},
                {"type_id": "oops", "required_level": 2},
                {"type_id": 11, "required_level": 0},
                {"type_id": 12, "required_level": 6},
                "bad-entry",
            ]
        )

        self.assertEqual(result, {10: 4})

    def test_merge_skill_maps_keeps_highest_level_per_skill(self):
        self.assertEqual(
            merge_skill_maps({1: 3, 2: 1}, {2: 4, 3: 2}),
            {1: 3, 2: 4, 3: 2},
        )

    @patch("mastery.services.doctrine.doctrine_skill_service.timezone.now", return_value="now")
    @patch("mastery.services.doctrine.doctrine_skill_service.transaction.atomic", return_value=nullcontext())
    def test_generate_for_fitting_creates_only_non_blacklisted_entries_and_syncs(
        self,
        _mock_atomic,
        mock_now,
    ):
        control_service = Mock()
        approval_service = Mock()
        service = DoctrineSkillService(
            extractor=Mock(),
            mastery_service=Mock(),
            control_service=control_service,
            suggestion_service=Mock(),
            fitting_map_service=Mock(),
            approval_service=approval_service,
        )
        fitting = SimpleNamespace(id=77)
        skillset = SimpleNamespace(skills=Mock())
        skillset.skills.all.return_value.delete = Mock()
        fitting_map = Mock(skillset=skillset)

        preview = {
            "fitting_map": fitting_map,
            "skill_rows": [
                {"skill_type_id": 1, "required_level": 2, "recommended_level": 4, "is_blacklisted": False},
                {"skill_type_id": 2, "required_level": 1, "recommended_level": 3, "is_blacklisted": True},
            ],
            "suggestions": {3: {"reason": "unused"}},
        }

        fake_skillsetskill = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
        fake_skillsetskill.objects.bulk_create = Mock()

        with patch.object(service, "preview_fitting", return_value=preview), patch(
            "mastery.services.doctrine.doctrine_skill_service.SkillSetSkill",
            fake_skillsetskill,
        ):
            service.generate_for_fitting(doctrine_map=Mock(), fitting=fitting)

        skillset.skills.all.return_value.delete.assert_called_once_with()
        entries = fake_skillsetskill.objects.bulk_create.call_args[0][0]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].eve_type_id, 1)
        self.assertEqual(entries[0].required_level, 2)
        self.assertEqual(entries[0].recommended_level, 4)
        fitting_map.save.assert_called_once_with(update_fields=["last_synced_at"])
        self.assertEqual(fitting_map.last_synced_at, mock_now.return_value)
        approval_service.mark_modified.assert_called_once_with(
            fitting_map,
            user=None,
            status=None,
        )
        control_service.sync_suggestions.assert_called_once_with(77, {3: {"reason": "unused"}})

    @patch("mastery.services.doctrine.doctrine_skill_service.Doctrine.objects.prefetch_related")
    def test_generate_for_doctrine_calls_generate_for_each_fitting(self, mock_prefetch_related):
        fitting_one = SimpleNamespace(id=1)
        fitting_two = SimpleNamespace(id=2)
        doctrine = Mock()
        doctrine.fittings.all.return_value = [fitting_one, fitting_two]
        mock_prefetch_related.return_value.get.return_value = doctrine

        doctrine_map = SimpleNamespace(doctrine=SimpleNamespace(id=99))
        service = DoctrineSkillService(
            extractor=Mock(),
            mastery_service=Mock(),
            control_service=Mock(),
            suggestion_service=Mock(),
            fitting_map_service=Mock(),
            approval_service=Mock(),
        )

        with patch.object(service, "generate_for_fitting") as mock_generate_for_fitting:
            service.generate_for_doctrine(doctrine_map=doctrine_map, mastery_level=3, modified_by=None, status=None)

        self.assertEqual(mock_generate_for_fitting.call_count, 2)
        mock_generate_for_fitting.assert_any_call(doctrine_map=doctrine_map, fitting=fitting_one, mastery_level=3, modified_by=None, status=None)
        mock_generate_for_fitting.assert_any_call(doctrine_map=doctrine_map, fitting=fitting_two, mastery_level=3, modified_by=None, status=None)


class TestSkillControlService(SimpleTestCase):
    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.filter")
    def test_get_blacklist_returns_set(self, mock_filter):
        mock_filter.return_value.values_list.return_value = [10, 11, 10]

        result = SkillControlService.get_blacklist(55)

        self.assertEqual(result, {10, 11})

    def test_apply_blacklist_filters_skills(self):
        service = SkillControlService()
        with patch.object(service, "get_blacklist", return_value={2}):
            result = service.apply_blacklist(1, {1: 3, 2: 4, 3: 5})

        self.assertEqual(result, {1: 3, 3: 5})

    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.update_or_create")
    def test_set_blacklist_updates_or_creates_control(self, mock_update_or_create):
        control = Mock()
        mock_update_or_create.return_value = (control, True)

        result = SkillControlService.set_blacklist(1, 2, True)

        self.assertIs(result, control)
        mock_update_or_create.assert_called_once_with(
            fitting_id=1,
            skill_type_id=2,
            defaults={"is_blacklisted": True},
        )

    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.filter")
    def test_get_controls_map_indexes_rows_by_skill_type(self, mock_filter):
        mock_filter.return_value.values.return_value = [
            {"skill_type_id": 1, "is_blacklisted": False, "is_suggested": False, "reason": None, "recommended_level_override": 4, "is_manual": True},
            {"skill_type_id": 2, "is_blacklisted": True, "is_suggested": True, "reason": "unused", "recommended_level_override": None, "is_manual": False},
        ]

        result = SkillControlService.get_controls_map(44)

        self.assertEqual(set(result.keys()), {1, 2})
        self.assertTrue(result[2]["is_blacklisted"])

    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.update_or_create")
    def test_add_manual_skill_sets_expected_defaults(self, mock_update_or_create):
        control = Mock()
        mock_update_or_create.return_value = (control, True)

        result = SkillControlService.add_manual_skill(3, 4, 5)

        self.assertIs(result, control)
        mock_update_or_create.assert_called_once_with(
            fitting_id=3,
            skill_type_id=4,
            defaults={"is_manual": True, "is_blacklisted": False, "recommended_level_override": 5},
        )

    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.filter")
    def test_remove_manual_skill_deletes_filtered_rows(self, mock_filter):
        mock_filter.return_value.delete.return_value = (1, {"x": 1})

        result = SkillControlService.remove_manual_skill(3, 4)

        self.assertEqual(result, (1, {"x": 1}))
        mock_filter.return_value.delete.assert_called_once_with()

    def test_batch_helpers_delegate_to_single_item_methods(self):
        service = SkillControlService()

        with patch.object(service, "set_blacklist") as mock_set_blacklist:
            service.set_blacklist_batch(8, [1, 2], True)
        self.assertEqual(mock_set_blacklist.call_count, 2)

        with patch.object(service, "set_recommended_level") as mock_set_recommended:
            service.set_recommended_level_batch(8, [1, 2], 4)
        self.assertEqual(mock_set_recommended.call_count, 2)

    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.update_or_create")
    @patch("mastery.services.skills.skill_control_service.FittingSkillControl.objects.filter")
    def test_sync_suggestions_resets_existing_rows_then_updates_pending(self, mock_filter, mock_update_or_create):
        service = SkillControlService()

        service.sync_suggestions(99, {1: {"reason": "unused"}, 2: {"reason": "not needed"}})

        mock_filter.return_value.update.assert_called_once_with(is_suggested=False, reason=None)
        self.assertEqual(mock_update_or_create.call_count, 2)


