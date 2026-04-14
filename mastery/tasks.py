from celery import shared_task

from mastery.services.sde.importer import SdeMasteryImporter
from mastery.services.sde.version_service import SdeVersionService


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True)
def update_sde_masteries(self, force=False):
    version_service = SdeVersionService()

    latest = version_service.fetch_latest()
    current = version_service.get_current()

    if current and current.build_number == latest['build_number'] and not force:
        return f"SDE is up to date ({current.build_number})"

    importer = SdeMasteryImporter()

    zip_file = importer.download()

    masteries = importer.extract_yaml(zip_file, "masteries.yaml")
    certificates = importer.extract_yaml(zip_file, "certificates.yaml")

    importer.exec_import(latest, masteries, certificates)

    return f"SDE updated to {latest['build_number']}"
