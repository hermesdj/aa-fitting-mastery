"""Celery tasks for Fitting Mastery."""

from celery import shared_task

from mastery.models import SdeCloneGradeSkill
from mastery.services.sde.importer import SdeMasteryImporter
from mastery.services.sde.version_service import SdeVersionService


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True)
def update_sde_masteries(self, force=False):  # pylint: disable=unused-argument
    """Fetch the latest SDE release and import masteries/certificates if outdated."""
    version_service = SdeVersionService()

    latest = version_service.fetch_latest()
    current = version_service.get_current()
    clone_grades_present = SdeCloneGradeSkill.objects.exists()

    if current and current.build_number == latest['build_number'] and clone_grades_present and not force:
        return f"SDE is up to date ({current.build_number})"

    importer = SdeMasteryImporter()

    zip_file = importer.download()

    masteries = importer.extract_yaml(zip_file, "masteries.yaml")
    certificates = importer.extract_yaml(zip_file, "certificates.yaml")
    clone_grades = importer.extract_yaml(zip_file, "cloneGrades.yaml")

    importer.exec_import(latest, masteries, certificates, clone_grades)

    if current and current.build_number == latest['build_number'] and not clone_grades_present:
        return f"SDE clone grades backfilled for {latest['build_number']}"

    return f"SDE updated to {latest['build_number']}"
