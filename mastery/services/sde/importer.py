"""Imports SDE certificate and mastery data into mastery models."""
import io
import zipfile

import requests
import yaml

from mastery.models import CertificateSkill, ShipMastery, ShipMasteryCertificate, SdeVersion


class SdeMasteryImporter:
    """Download and import EVE SDE mastery/certificate payloads into DB tables."""
    SDE_URL = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-yaml.zip"

    def download(self):
        """Download the latest SDE zip archive and return it as ZipFile."""
        response = requests.get(self.SDE_URL, timeout=60)
        response.raise_for_status()

        return zipfile.ZipFile(io.BytesIO(response.content))

    @staticmethod
    def extract_yaml(zip_file, filename):
        """Extract and parse a YAML file from the downloaded SDE archive."""
        for file in zip_file.namelist():
            if file.endswith(filename):
                return yaml.safe_load(zip_file.read(file))
        raise FileNotFoundError(filename)

    @staticmethod
    def import_certificates(data):
        """Replace CertificateSkill table content from SDE certificate payload."""
        objs = []

        for cert_id, cert_data in data.items():
            for skill_id, levels in cert_data.get("skillTypes", {}).items():
                objs.append(
                    CertificateSkill(
                        certificate_id=cert_id,
                        skill_type_id=skill_id,
                        level_basic=levels.get("basic"),
                        level_standard=levels.get("standard"),
                        level_improved=levels.get("improved"),
                        level_advanced=levels.get("advanced"),
                        level_elite=levels.get("elite"),
                    )
                )

        CertificateSkill.objects.all().delete()
        CertificateSkill.objects.bulk_create(objs, batch_size=1000)

    @staticmethod
    def import_masteries(data):
        """Replace ship mastery and mastery-certificate relation tables from SDE."""
        mastery_objs = []
        cert_objs = []

        for ship_id, levels in data.items():
            for level, certs in levels.items():
                mastery = ShipMastery(
                    ship_type_id=ship_id,
                    level=level
                )
                mastery_objs.append(mastery)

        ShipMastery.objects.all().delete()
        ShipMastery.objects.bulk_create(mastery_objs, batch_size=1000)

        mastery_map = {
            (m.ship_type_id, m.level): m.id
            for m in ShipMastery.objects.all()
        }

        for ship_id, levels in data.items():
            for level, certs in levels.items():
                mastery_id = mastery_map[(ship_id, level)]

                for cert_id in certs:
                    cert_objs.append(
                        ShipMasteryCertificate(
                            mastery_id=mastery_id,
                            certificate_id=cert_id
                        )
                    )

        ShipMasteryCertificate.objects.bulk_create(cert_objs, batch_size=1000)

    @staticmethod
    def exec_import(latest, masteries, certificates, dry_run=False):
        """Execute full import and update active SDE version marker."""
        importer = SdeMasteryImporter()
        if not dry_run:
            importer.import_certificates(certificates)
            importer.import_masteries(masteries)

            SdeVersion.objects.update_or_create(
                build_number=latest["build_number"],
                defaults={
                    "release_date": latest["release_date"],
                    "is_active": True
                }
            )
            SdeVersion.objects.exclude(
                build_number=latest["build_number"]
            ).update(is_active=False)
