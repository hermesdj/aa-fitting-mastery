from mastery.models import (
    ShipMasteryCertificate,
    CertificateSkill
)

MASTERY_TO_FIELD = {
    0: "level_basic",
    1: "level_standard",
    2: "level_improved",
    3: "level_advanced",
    4: "level_elite",
}


class MasteryService:
    def __init__(self):
        self._cache = {}

    def get_ship_skills(self, ship_type_id: int, mastery_level: int) -> dict:
        """
        retourne {skill_type_id: level}
        """
        key = (ship_type_id, mastery_level)

        if key in self._cache:
            return self._cache[key]

        level_field = MASTERY_TO_FIELD[mastery_level]

        rows = CertificateSkill.objects.filter(
            certificate_id__in=ShipMasteryCertificate.objects.filter(
                mastery__ship_type_id=ship_type_id,
                mastery__level=mastery_level
            ).values_list("certificate_id", flat=True)
        ).values("skill_type_id", level_field)

        result = {
            row["skill_type_id"]: row[level_field]
            for row in rows
            if row[level_field] and row[level_field] > 0
        }

        self._cache[key] = result

        return result
