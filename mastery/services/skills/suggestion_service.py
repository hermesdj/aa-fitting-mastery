"""Generates blacklist-addition suggestions for fittings."""
from collections import defaultdict

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag
from eve_sde.models import ItemType
from fittings.models import Fitting

from mastery import __title__

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class SkillSuggestionService:
    # mapping skill groups to features
    """Infer removable skills by matching fitting modules to skill feature groups."""
    SKILL_GROUP_FEATURES = {
        # Tank
        1210: "shield",
        1211: "armor",

        # Weapons
        255: "missiles",
        53: "turrets",

        # Drones
        273: "drones",

        # Command Bursts
        258: "command_bursts",

        # Subsystems (T3C)
        1240: "subsystems",
    }

    MODULE_GROUP_FEATURES = {
        77: "shield",
        38: "shield",
        295: "shield",

        62: "armor",
        328: "armor",

        60: "hull",

        46: "propulsion",

        506: "missiles",
        510: "missiles",
        367: "missiles",

        53: "turrets",

        18: "drones",

        330: "cloacking",

        481: "scan",

        316: "command_bursts"
    }

    # Some fittings expose drones/items with categories that are more stable than groups.
    MODULE_CATEGORY_FEATURES = {
        18: "drones",  # Drone category
    }

    ALWAYS_KEEP_GROUPS = {
        "Engineering",
        "Navigation",
        "Spaceship Command",
        "Targeting",
        "Electronic Systems"
    }

    def __init__(self):
        """Initialize in-memory cache for skill type metadata lookups."""
        self._group_cache = {}

    def get_group(self, skill_type_id: int):
        """Return cached ItemType+group data for a skill type ID."""
        if skill_type_id not in self._group_cache:
            try:
                self._group_cache[skill_type_id] = ItemType.objects.select_related('group__category').get(
                    id=skill_type_id
                )
            except ItemType.DoesNotExist:
                self._group_cache[skill_type_id] = None
        return self._group_cache[skill_type_id]

    def detect_features(self, fitting: Fitting):
        """Detect feature flags present in fitting modules (shield, armor, missiles, ...)."""
        features = defaultdict(bool)

        for item in fitting.items.select_related("type_fk__group__category").all():
            group = item.type_fk.group
            group_id = group.id
            category = item.type_fk.group.category
            category_id = category.id
            feature = self.MODULE_GROUP_FEATURES.get(group_id)

            # Fallback for cases where group mapping misses but category is explicit (e.g. drones).
            if not feature:
                feature = self.MODULE_CATEGORY_FEATURES.get(category_id)

            if feature:
                features[feature] = True

        return features

    def suggest(self, fitting: Fitting, skills: dict, fitting_required_skills: dict = None):
        """
        retourne {skill_type_id: reason}

        fitting_required_skills: dict {skill_type_id: level} tel que retourné par
        FittingSkillExtractor.get_required_skills_for_fitting(). Quand fourni, permet
        une vérification au niveau du skill individuel (en plus de la détection de
        feature par groupe de modules) afin de suggérer le retrait des skills d'une
        catégorie présente dans le fitting mais non utilisée par les modules réels
        (ex : "Heavy Assault Missiles" alors que le fitting ne contient que des
        lanceurs Heavy Missile).
        """

        suggestions = {}

        features = self.detect_features(fitting)

        for skill_type_id in skills:
            item = self.get_group(skill_type_id)

            if not item:
                continue

            group = item.group
            group_id = item.group_id

            if group.name in self.ALWAYS_KEEP_GROUPS:
                continue

            feature = self.SKILL_GROUP_FEATURES.get(group_id)

            if not feature:
                continue

            if not features.get(feature, False):
                # Aucun module du fitting n'utilise cette feature
                suggestions[skill_type_id] = {
                    "action": "remove",
                    "reason": f"{feature.replace('_', ' ').title()} not used in fitting",
                    "group": group.name,
                }
            elif fitting_required_skills is not None and skill_type_id not in fitting_required_skills:
                # La feature est présente dans le fitting, mais aucun module ne
                # requiert ce skill spécifique (ex : Heavy Assault Missiles alors
                # qu'il n'y a que des lanceurs Heavy Missile).
                suggestions[skill_type_id] = {
                    "action": "remove",
                    "reason": (
                        f"{feature.replace('_', ' ').title()} modules are present, "
                        f"but no module requires this specific skill"
                    ),
                    "group": group.name,
                }

        return suggestions
