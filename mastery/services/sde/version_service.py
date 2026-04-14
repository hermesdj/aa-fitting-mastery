import requests
from django.utils.dateparse import parse_datetime

from mastery.models import SdeVersion


class SdeVersionService:
    URL = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"

    def fetch_latest(self):
        response = requests.get(self.URL, timeout=60)
        response.raise_for_status()

        data = response.json()

        return {
            "build_number": data["buildNumber"],
            "release_date": parse_datetime(data["releaseDate"])
        }

    @staticmethod
    def get_current():
        return SdeVersion.objects.filter(is_active=True).first()

    def is_up_to_date(self):
        latest = self.fetch_latest()
        current = self.get_current()

        if not current:
            return False

        return current.build_number == latest["build_number"]
