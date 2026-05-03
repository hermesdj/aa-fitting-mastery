from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from mastery.tasks import update_sde_masteries


class TestTasks(SimpleTestCase):
    @patch("mastery.tasks.SdeCloneGradeSkill.objects.exists", return_value=True)
    @patch("mastery.tasks.SdeMasteryImporter")
    @patch("mastery.tasks.SdeVersionService")
    def test_update_sde_masteries_skips_import_when_up_to_date(
        self,
        mock_version_service_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_service_cls.return_value
        service.fetch_latest.return_value = {"build_number": 123}
        service.get_current.return_value = Mock(build_number=123)

        result = update_sde_masteries.run(force=False)

        self.assertEqual(result, "SDE is up to date (123)")
        mock_importer_cls.assert_not_called()

    @patch("mastery.tasks.SdeCloneGradeSkill.objects.exists", return_value=True)
    @patch("mastery.tasks.SdeMasteryImporter")
    @patch("mastery.tasks.SdeVersionService")
    def test_update_sde_masteries_imports_when_outdated(
        self,
        mock_version_service_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_service_cls.return_value
        service.fetch_latest.return_value = {"build_number": 124}
        service.get_current.return_value = Mock(build_number=123)

        importer = mock_importer_cls.return_value
        importer.download.return_value = "archive.zip"
        importer.extract_yaml.side_effect = [{"m": 1}, {"c": 2}, {"g": 3}]

        result = update_sde_masteries.run(force=False)

        self.assertEqual(result, "SDE updated to 124")
        importer.download.assert_called_once_with()
        importer.extract_yaml.assert_any_call("archive.zip", "masteries.yaml")
        importer.extract_yaml.assert_any_call("archive.zip", "certificates.yaml")
        importer.extract_yaml.assert_any_call("archive.zip", "cloneGrades.yaml")
        importer.exec_import.assert_called_once_with({"build_number": 124}, {"m": 1}, {"c": 2}, {"g": 3})

    @patch("mastery.tasks.SdeCloneGradeSkill.objects.exists", return_value=True)
    @patch("mastery.tasks.SdeMasteryImporter")
    @patch("mastery.tasks.SdeVersionService")
    def test_update_sde_masteries_force_triggers_import_even_if_up_to_date(
        self,
        mock_version_service_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_service_cls.return_value
        service.fetch_latest.return_value = {"build_number": 123}
        service.get_current.return_value = Mock(build_number=123)

        importer = mock_importer_cls.return_value
        importer.download.return_value = "archive.zip"
        importer.extract_yaml.side_effect = [{"m": 1}, {"c": 2}, {"g": 3}]

        result = update_sde_masteries.run(force=True)

        self.assertEqual(result, "SDE updated to 123")
        importer.exec_import.assert_called_once()

    @patch("mastery.tasks.SdeCloneGradeSkill.objects.exists", return_value=False)
    @patch("mastery.tasks.SdeMasteryImporter")
    @patch("mastery.tasks.SdeVersionService")
    def test_update_sde_masteries_backfills_clone_grades_when_missing(
        self,
        mock_version_service_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_service_cls.return_value
        service.fetch_latest.return_value = {"build_number": 123}
        service.get_current.return_value = Mock(build_number=123)

        importer = mock_importer_cls.return_value
        importer.download.return_value = "archive.zip"
        importer.extract_yaml.side_effect = [{"m": 1}, {"c": 2}, {"g": 3}]

        result = update_sde_masteries.run(force=False)

        self.assertEqual(result, "SDE clone grades backfilled for 123")
        importer.exec_import.assert_called_once_with({"build_number": 123}, {"m": 1}, {"c": 2}, {"g": 3})

