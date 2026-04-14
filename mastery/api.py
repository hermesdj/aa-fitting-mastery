import json

from allianceauth.authentication.decorators import permissions_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from fittings.models import Doctrine, Fitting

from mastery.services.skills.skill_control_service import SkillControlService
from mastery.services.doctrine.doctrine_map_service import DoctrineMapService
from mastery.services.doctrine.doctrine_skill_service import DoctrineSkillService
from mastery.services.fittings import FittingSkillExtractor, FittingMapService
from mastery.services.sde import MasteryService
from mastery.services.skills import SkillSuggestionService
from mastery.models import DoctrineSkillSetGroupMap

extractor_service = FittingSkillExtractor()
mastery_service = MasteryService()
control_service = SkillControlService()
suggestion_service = SkillSuggestionService()
fitting_map_service = FittingMapService()
doctrine_skill_service = DoctrineSkillService(
    extractor=extractor_service,
    mastery_service=mastery_service,
    control_service=control_service,
    suggestion_service=suggestion_service,
    fitting_map_service=fitting_map_service,
)
doctrine_map_service = DoctrineMapService(doctrine_skill_service=doctrine_skill_service)


@login_required
@require_POST
@permissions_required('mastery.manage_fittings')
def update_skill_level(request):
    return JsonResponse({"status": "not_implemented"}, status=501)


@login_required
@require_POST
@permissions_required('mastery.manage_fittings')
def toggle_blacklist(request):
    data = json.loads(request.body)

    fitting = Fitting.objects.filter(id=data['fitting_id']).first()
    doctrine = Doctrine.objects.filter(fittings__id=data['fitting_id']).first()

    if fitting is None or doctrine is None:
        return JsonResponse({"status": "error", "message": "Unable to locate fitting or doctrine"}, status=400)

    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()
    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    value = data.get('value')
    if isinstance(value, str):
        value = value.lower() == 'true'
    elif value is None:
        value = data['skill_type_id'] not in control_service.get_blacklist(data['fitting_id'])

    control_service.set_blacklist(
        fitting_id=data['fitting_id'],
        skill_type_id=data['skill_type_id'],
        value=bool(value)
    )

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return JsonResponse({"status": "ok", "blacklisted": bool(value)})

