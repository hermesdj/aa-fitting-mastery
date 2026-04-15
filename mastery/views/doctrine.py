from allianceauth.authentication.decorators import permissions_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from .common import (
    Doctrine,
    DoctrineSkillSetGroupMap,
    FittingSkillsetMap,
    MASTERY_LEVEL_CHOICES,
    _get_mastery_label,
    _parse_mastery_level,
    doctrine_map_service,
)


@login_required
@permissions_required('mastery.manage_fittings')
def doctrine_list_view(request):
    doctrines = Doctrine.objects.prefetch_related("fittings")

    data = []

    for doctrine in doctrines:
        fittings = doctrine.fittings.all()
        total = fittings.count()

        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()
        initialized = doctrine_map is not None
        configured = 0 if doctrine_map is None else FittingSkillsetMap.objects.filter(doctrine_map=doctrine_map).count()

        data.append(
            {
                "id": doctrine.pk,
                "name": doctrine.name,
                "initialized": initialized,
                "total": total,
                "configured": configured,
                "icon_url": doctrine.icon_url,
                "default_mastery_level": None if doctrine_map is None else doctrine_map.default_mastery_level,
                "default_mastery_label": None if doctrine_map is None else _get_mastery_label(doctrine_map.default_mastery_level),
            }
        )

    return render(
        request,
        "mastery/doctrine_list.html",
        {
            "doctrines": data,
        },
    )


@login_required
@permissions_required('mastery.manage_fittings')
def doctrine_detail_view(request, doctrine_id):
    doctrine = Doctrine.objects.prefetch_related("fittings").get(id=doctrine_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()
    fittings_data = []

    for fitting in doctrine.fittings.all():
        fitting_map = FittingSkillsetMap.objects.filter(fitting=fitting).first()
        override_level = None if fitting_map is None else fitting_map.mastery_level
        doctrine_default_level = doctrine_map.default_mastery_level if doctrine_map else 4
        effective_level = override_level if override_level is not None else doctrine_default_level
        effective_level = int(effective_level or 4)

        fittings_data.append(
            {
                "id": fitting.id,
                "name": fitting.name,
                "ship_type_id": fitting.ship_type_type_id,
                "ship_name": fitting.ship_type.name,
                "configured": fitting_map is not None,
                "mastery_override": override_level,
                "effective_mastery_level": effective_level,
                "effective_mastery_label": _get_mastery_label(effective_level),
            }
        )

    return render(
        request,
        "mastery/doctrine_detail.html",
        {
            "doctrine": doctrine,
            "doctrine_map": doctrine_map,
            "doctrine_default_mastery_level": 4 if doctrine_map is None else doctrine_map.default_mastery_level,
            "doctrine_default_mastery_label": _get_mastery_label(4 if doctrine_map is None else doctrine_map.default_mastery_level),
            "mastery_choices": MASTERY_LEVEL_CHOICES,
            "fittings": fittings_data,
        },
    )


@login_required
@permissions_required('mastery.manage_fittings')
def generate_doctrine(request, doctrine_id):
    doctrine = Doctrine.objects.get(id=doctrine_id)
    has_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).exists()

    if not has_map:
        doctrine_map_service.create_doctrine_map(doctrine)

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def sync_doctrine(request, doctrine_id):
    doctrine = Doctrine.objects.get(id=doctrine_id)
    doctrine_map_service.sync(doctrine)

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def update_doctrine_mastery(request, doctrine_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    doctrine = get_object_or_404(Doctrine, id=doctrine_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    try:
        doctrine_map.default_mastery_level = _parse_mastery_level(request.POST.get("mastery_level")) or 4
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))
    doctrine_map.save(update_fields=["default_mastery_level"])

    doctrine_map_service.sync(doctrine)

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)

