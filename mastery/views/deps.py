"""Shared view dependencies and service singletons."""
from django.utils.translation import gettext_lazy as _

from mastery.services.doctrine.doctrine_map_service import DoctrineMapService
from mastery.services.doctrine.doctrine_skill_service import DoctrineSkillService
from mastery.services.fittings import FittingApprovalService, FittingMapService, FittingSkillExtractor
from mastery.services.pilots import PilotAccessService, PilotProgressService
from mastery.services.sde import CloneGradeService, MasteryService
from mastery.services.skills import SkillSuggestionService
from mastery.services.skills.skill_control_service import SkillControlService

MASTERY_LEVEL_LABELS = {
    0: _("I - Basic"),
    1: _("II - Standard"),
    2: _("III - Improved"),
    3: _("IV - Advanced"),
    4: _("V - Elite"),
}
MASTERY_LEVEL_CHOICES = list(MASTERY_LEVEL_LABELS.items())

extractor_service = FittingSkillExtractor()
mastery_service = MasteryService()
control_service = SkillControlService()
suggestion_service = SkillSuggestionService()
fitting_map_service = FittingMapService()
approval_service = FittingApprovalService()
clone_grade_service = CloneGradeService()
pilot_access_service = PilotAccessService()
pilot_progress_service = PilotProgressService()
doctrine_skill_service = DoctrineSkillService(
    extractor=extractor_service,
    mastery_service=mastery_service,
    control_service=control_service,
    suggestion_service=suggestion_service,
    fitting_map_service=fitting_map_service,
    approval_service=approval_service,
    clone_grade_service=clone_grade_service,
)
doctrine_map_service = DoctrineMapService(doctrine_skill_service=doctrine_skill_service)
