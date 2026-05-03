from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase

from mastery.services.sde.importer import SdeMasteryImporter


class TestSdeMasteryImporter(SimpleTestCase):
    def test_clone_grade_skill_caps_uses_canonical_grade(self):
        payload = {
            1: {
                "name": "Alpha Caldari",
                "skills": [
                    {"typeID": 3307, "level": 4},
                    {"typeID": 3332, "level": 5},
                ],
            },
            2: {
                "name": "Alpha Minmatar",
                "skills": [
                    {"typeID": 3307, "level": 4},
                ],
            },
        }

        caps = SdeMasteryImporter.clone_grade_skill_caps(payload)

        self.assertEqual(caps[3307], 4)
        self.assertEqual(caps[3332], 5)
        self.assertNotIn(11082, caps)

    def test_extract_yaml_returns_matching_payload(self):
        zip_file = Mock()
        zip_file.namelist.return_value = ["foo/bar/masteries.yaml"]
        zip_file.read.return_value = b"1:\n  1: [10]\n"

        payload = SdeMasteryImporter.extract_yaml(zip_file, "masteries.yaml")

        self.assertEqual(payload, {1: {1: [10]}})

    def test_extract_yaml_raises_when_file_missing(self):
        zip_file = Mock()
        zip_file.namelist.return_value = ["foo/bar/other.yaml"]

        with self.assertRaises(FileNotFoundError):
            SdeMasteryImporter.extract_yaml(zip_file, "masteries.yaml")

    @patch("mastery.services.sde.importer.CertificateSkill.objects")
    def test_import_certificates_replaces_existing_rows(self, mock_objects):
        payload = {
            1001: {
                "skillTypes": {
                    3300: {
                        "basic": 1,
                        "standard": 2,
                        "improved": 3,
                        "advanced": 4,
                        "elite": 5,
                    }
                }
            }
        }

        SdeMasteryImporter.import_certificates(payload)

        mock_objects.all.assert_called_once_with()
        mock_objects.all.return_value.delete.assert_called_once_with()
        bulk_args = mock_objects.bulk_create.call_args[0][0]
        self.assertEqual(len(bulk_args), 1)
        self.assertEqual(bulk_args[0].certificate_id, 1001)
        self.assertEqual(bulk_args[0].skill_type_id, 3300)

    @patch("mastery.services.sde.importer.ShipMasteryCertificate.objects")
    @patch("mastery.services.sde.importer.ShipMastery.objects")
    def test_import_masteries_rebuilds_mastery_and_links(self, mock_mastery_objects, mock_cert_objects):
        payload = {
            111: {
                1: [200, 201],
                2: [202],
            }
        }
        delete_qs = Mock()
        mock_mastery_objects.all.side_effect = [
            delete_qs,
            [
            SimpleNamespace(id=10, ship_type_id=111, level=1),
            SimpleNamespace(id=11, ship_type_id=111, level=2),
            ],
        ]

        SdeMasteryImporter.import_masteries(payload)

        self.assertEqual(mock_mastery_objects.all.call_count, 2)
        delete_qs.delete.assert_called_once_with()
        created_masteries = mock_mastery_objects.bulk_create.call_args[0][0]
        self.assertEqual(len(created_masteries), 2)

        created_links = mock_cert_objects.bulk_create.call_args[0][0]
        self.assertEqual(len(created_links), 3)
        self.assertEqual({link.mastery_id for link in created_links}, {10, 11})

    @patch("mastery.services.sde.importer.SdeCloneGradeSkill.objects")
    def test_import_clone_grades_replaces_existing_rows_from_canonical_grade(self, mock_objects):
        payload = {
            1: {
                "name": "Alpha Caldari",
                "skills": [
                    {"typeID": 3307, "level": 4},
                    {"typeID": 3332, "level": 5},
                ],
            },
            2: {
                "name": "Alpha Minmatar",
                "skills": [
                    {"typeID": 3307, "level": 4},
                ],
            },
        }

        SdeMasteryImporter.import_clone_grades(payload)

        mock_objects.all.assert_called_once_with()
        mock_objects.all.return_value.delete.assert_called_once_with()
        created_rows = mock_objects.bulk_create.call_args[0][0]
        self.assertEqual(len(created_rows), 2)
        self.assertEqual(created_rows[0].skill_type_id, 3307)
        self.assertEqual(created_rows[0].max_alpha_level, 4)

    @patch("mastery.services.sde.importer.SdeVersion.objects")
    @patch("mastery.services.sde.importer.SdeMasteryImporter.import_clone_grades")
    @patch("mastery.services.sde.importer.SdeMasteryImporter.import_masteries")
    @patch("mastery.services.sde.importer.SdeMasteryImporter.import_certificates")
    def test_exec_import_skips_db_write_in_dry_run(
        self,
        mock_import_certs,
        mock_import_masteries,
        mock_import_clone_grades,
        mock_version,
    ):
        latest = {"build_number": 999, "release_date": "2026-04-01"}

        SdeMasteryImporter.exec_import(latest, {1: {}}, {2: {}}, {3: {}}, dry_run=True)

        mock_import_certs.assert_not_called()
        mock_import_masteries.assert_not_called()
        mock_import_clone_grades.assert_not_called()
        mock_version.update_or_create.assert_not_called()


class TestImportSdeMasteriesCommand(SimpleTestCase):
    @patch("mastery.management.commands.import_sde_masteries.SdeCloneGradeSkill.objects.exists", return_value=True)
    @patch("mastery.management.commands.import_sde_masteries.SdeMasteryImporter")
    @patch("mastery.management.commands.import_sde_masteries.SdeVersionService")
    def test_command_skips_when_up_to_date_without_force(
        self,
        mock_version_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_cls.return_value
        service.fetch_latest.return_value = {"build_number": 42, "release_date": "2026-04-01"}
        service.get_current.return_value = SimpleNamespace(build_number=42)

        stdout = StringIO()
        call_command("import_sde_masteries", stdout=stdout)

        mock_importer_cls.assert_not_called()
        output = stdout.getvalue()
        self.assertIn("SDE is up to date", output)

    @patch("mastery.management.commands.import_sde_masteries.SdeCloneGradeSkill.objects.exists", return_value=False)
    @patch("mastery.management.commands.import_sde_masteries.SdeMasteryImporter")
    @patch("mastery.management.commands.import_sde_masteries.SdeVersionService")
    def test_command_backfills_when_version_is_current_but_clone_grades_missing(
        self,
        mock_version_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_cls.return_value
        service.fetch_latest.return_value = {"build_number": 42, "release_date": "2026-04-01"}
        service.get_current.return_value = SimpleNamespace(build_number=42)

        importer = mock_importer_cls.return_value
        importer.download.return_value = "zip"
        importer.extract_yaml.side_effect = [{1: {1: [10]}}, {2: {}}, {1: {"skills": []}}]
        importer.clone_grade_skill_caps.return_value = {}

        stdout = StringIO()
        call_command("import_sde_masteries", stdout=stdout)

        importer.exec_import.assert_called_once_with(
            {"build_number": 42, "release_date": "2026-04-01"},
            {1: {1: [10]}},
            {2: {}},
            {1: {"skills": []}},
            dry_run=False,
        )
        self.assertIn("clone grades are missing", stdout.getvalue())

    @patch("mastery.management.commands.import_sde_masteries.SdeCloneGradeSkill.objects.exists", return_value=True)
    @patch("mastery.management.commands.import_sde_masteries.SdeMasteryImporter")
    @patch("mastery.management.commands.import_sde_masteries.SdeVersionService")
    def test_command_dry_run_downloads_but_does_not_import(
        self,
        mock_version_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_cls.return_value
        service.fetch_latest.return_value = {"build_number": 43, "release_date": "2026-04-02"}
        service.get_current.return_value = None

        importer = mock_importer_cls.return_value
        importer.download.return_value = "zip"
        importer.extract_yaml.side_effect = [{1: {}}, {2: {}}, {1: {"skills": []}}]
        importer.clone_grade_skill_caps.return_value = {3307: 4}

        stdout = StringIO()
        call_command("import_sde_masteries", "--dry-run", stdout=stdout)

        importer.download.assert_called_once_with()
        importer.extract_yaml.assert_any_call("zip", "masteries.yaml")
        importer.extract_yaml.assert_any_call("zip", "certificates.yaml")
        importer.extract_yaml.assert_any_call("zip", "cloneGrades.yaml")
        importer.clone_grade_skill_caps.assert_called_once_with({1: {"skills": []}})
        importer.exec_import.assert_not_called()
        self.assertIn("Dry-run: skipping DB import", stdout.getvalue())

    @patch("mastery.management.commands.import_sde_masteries.SdeCloneGradeSkill.objects.exists", return_value=True)
    @patch("mastery.management.commands.import_sde_masteries.SdeMasteryImporter")
    @patch("mastery.management.commands.import_sde_masteries.SdeVersionService")
    def test_command_runs_import_when_outdated(
        self,
        mock_version_cls,
        mock_importer_cls,
        _mock_clone_exists,
    ):
        service = mock_version_cls.return_value
        service.fetch_latest.return_value = {"build_number": 44, "release_date": "2026-04-03"}
        service.get_current.return_value = SimpleNamespace(build_number=43)

        importer = mock_importer_cls.return_value
        importer.download.return_value = "zip"
        importer.extract_yaml.side_effect = [{1: {1: [10]}}, {2: {}}, {1: {"skills": []}}]
        importer.clone_grade_skill_caps.return_value = {3307: 4}

        stdout = StringIO()
        call_command("import_sde_masteries", stdout=stdout)

        importer.clone_grade_skill_caps.assert_called_once_with({1: {"skills": []}})
        importer.exec_import.assert_called_once_with(
            {"build_number": 44, "release_date": "2026-04-03"},
            {1: {1: [10]}},
            {2: {}},
            {1: {"skills": []}},
            dry_run=False,
        )
        self.assertIn("SDE import complete", stdout.getvalue())


