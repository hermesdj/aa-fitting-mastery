"""Management command to import SDE masteries and certificates."""

import time

from django.core.management import BaseCommand

from mastery.services.sde.importer import SdeMasteryImporter
from mastery.services.sde.version_service import SdeVersionService


class Command(BaseCommand):
    """Import SDE mastery data into local mastery models."""

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force import even if SDE version is up to date",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without making any changes",
        )

    def handle(self, *args, **options):
        start = time.time()
        version_service = SdeVersionService()

        latest = version_service.fetch_latest()
        current = version_service.get_current()

        if current:
            self.stdout.write(f"Current SDE version: {current.build_number}")
        else:
            self.stdout.write("No SDE imported yet")

        self.stdout.write(f"Latest SDE version: {latest['build_number']}")

        if (
                current
                and current.build_number == latest["build_number"]
                and not options["force"]
        ):
            self.stdout.write(self.style.SUCCESS("SDE is up to date, skipping import"))
            return

        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in DRY-RUN mode"))

        # IMPORT
        importer = SdeMasteryImporter()
        zip_file = importer.download()

        masteries = importer.extract_yaml(zip_file, "masteries.yaml")
        self.stdout.write(f"Masteries loaded: {len(masteries)} ships")

        certificates = importer.extract_yaml(zip_file, "certificates.yaml")
        self.stdout.write(f"Certificates loaded: {len(certificates)} entries")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run: skipping DB import"))
            return

        importer.exec_import(latest, masteries, certificates, dry_run=dry_run)

        self.stdout.write(self.style.SUCCESS(f"SDE import complete, done in {time.time() - start:.2f}s"))
