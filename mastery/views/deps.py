"""Shared view dependencies and service singletons."""

from mastery.services.doctrine.doctrine_map_service import DoctrineMapService
from mastery.services.doctrine.doctrine_skill_service import DoctrineSkillService
from mastery.services.fittings import FittingApprovalService, FittingMapService, FittingSkillExtractor
from mastery.services.pilots import PilotAccessService, PilotProgressService
from mastery.services.sde import MasteryService
from mastery.services.skills import SkillSuggestionService
from mastery.services.skills.skill_control_service import SkillControlService

MASTERY_LEVEL_LABELS = {
    0: "I - Basic",
    1: "II - Standard",
    2: "III - Improved",
    3: "IV - Advanced",
    4: "V - Elite",
}
MASTERY_LEVEL_CHOICES = list(MASTERY_LEVEL_LABELS.items())

extractor_service = FittingSkillExtractor()
mastery_service = MasteryService()
control_service = SkillControlService()
suggestion_service = SkillSuggestionService()
fitting_map_service = FittingMapService()
approval_service = FittingApprovalService()
pilot_access_service = PilotAccessService()
pilot_progress_service = PilotProgressService()
doctrine_skill_service = DoctrineSkillService(
    extractor=extractor_service,
    mastery_service=mastery_service,
    control_service=control_service,
    suggestion_service=suggestion_service,
    fitting_map_service=fitting_map_service,
    approval_service=approval_service,
)
doctrine_map_service = DoctrineMapService(doctrine_skill_service=doctrine_skill_service)
