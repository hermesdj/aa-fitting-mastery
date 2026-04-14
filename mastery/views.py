from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import List

from allianceauth.authentication.decorators import permissions_required
from allianceauth.eveonline.models import EveCharacter
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponseBadRequest, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from eve_sde.models import ItemType, TypeDogma
from fittings.models import Doctrine, Fitting
from memberaudit.models import Character

from mastery import app_settings
from mastery.models import DoctrineSkillSetGroupMap, FittingSkillsetMap, SummaryAudienceGroup, SummaryAudienceEntity
from mastery.services.doctrine.doctrine_map_service import DoctrineMapService
from mastery.services.doctrine.doctrine_skill_service import DoctrineSkillService
from mastery.services.fittings import FittingSkillExtractor, FittingMapService
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
pilot_access_service = PilotAccessService()
pilot_progress_service = PilotProgressService()
doctrine_skill_service = DoctrineSkillService(
    extractor=extractor_service,
    mastery_service=mastery_service,
    control_service=control_service,
    suggestion_service=suggestion_service,
    fitting_map_service=fitting_map_service
)
doctrine_map_service = DoctrineMapService(doctrine_skill_service=doctrine_skill_service)
def _get_mastery_label(level: int) -> str:
    return MASTERY_LEVEL_LABELS.get(level, str(level))


def _parse_mastery_level(raw_value: str):
    if raw_value in (None, ""):
        return None

    level = int(raw_value)

    if level not in MASTERY_LEVEL_LABELS:
        raise ValueError(f"Invalid mastery level: {level}")

    return level


def _parse_posted_int(raw_value: str, field_name: str) -> int:
    if raw_value in (None, ""):
        raise ValueError(f"{field_name} is required")

    normalized = str(raw_value).strip()
    normalized = normalized.replace("\u202f", "").replace("\xa0", "").replace(" ", "")

    if "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")

    try:
        number = Decimal(normalized)
    except InvalidOperation as ex:
        raise ValueError(f"Invalid integer for {field_name}: {raw_value}") from ex

    if number != number.to_integral_value():
        raise ValueError(f"{field_name} must be an integer: {raw_value}")

    return int(number)


def _get_doctrine_and_map_for_fitting(fitting_id: int):
    fitting = get_object_or_404(Fitting.objects.select_related("ship_type"), id=fitting_id)
    fitting_map = FittingSkillsetMap.objects.select_related("doctrine_map").filter(fitting_id=fitting_id).first()

    doctrine = None
    doctrine_map = None

    if fitting_map:
        doctrine_map = fitting_map.doctrine_map
        doctrine = doctrine_map.doctrine
    else:
        doctrine = Doctrine.objects.filter(fittings__id=fitting_id).first()

    return fitting, doctrine, doctrine_map, fitting_map


def _group_preview_skills(skill_rows: List[dict]) -> dict:
    item_types = {
        item_type.id: item_type
        for item_type in ItemType.objects.select_related("group").filter(
            id__in=[row["skill_type_id"] for row in skill_rows]
        )
    }

    grouped = defaultdict(lambda: {"skills": [], "suggestion_count": 0})

    for row in sorted(skill_rows, key=lambda x: (x.get("group_name", "Other"), x.get("skill_name", ""))):
        item_type = item_types.get(row["skill_type_id"])
        skill_name = item_type.name if item_type else f"Skill {row['skill_type_id']}"
        skill_description = "" if not item_type else (getattr(item_type, "description", "") or "")
        group_name = item_type.group.name if item_type and item_type.group else "Other"
        group_id = item_type.group.id if item_type and item_type.group else None

        row_payload = {
            **row,
            "skill_name": skill_name,
            "skill_description": skill_description,
            "group_name": group_name,
            "group_id": group_id,
        }
        grouped[group_name]["skills"].append(row_payload)
        if row_payload.get("is_suggested"):
            grouped[group_name]["suggestion_count"] += 1

    return dict(sorted(grouped.items(), key=lambda x: (x[0] or "").lower()))


def _get_skill_name_options() -> List[str]:
    return list(
        ItemType.objects.filter(group__category__name__iexact="Skill")
        .order_by("name")
        .values_list("name", flat=True)
    )


def _build_fitting_preview_context(
        fitting: Fitting,
        doctrine_map: DoctrineSkillSetGroupMap,
        fitting_map: FittingSkillsetMap = None,
        mastery_level: int = None,
) -> dict:
    preview = doctrine_skill_service.preview_fitting(
        doctrine_map=doctrine_map,
        fitting=fitting,
        mastery_level=mastery_level,
    )
    effective_mastery_level = preview["effective_mastery_level"]
    all_rows = list(preview["skills"])
    active_rows = [row for row in all_rows if not row.get("is_blacklisted")]

    return {
        "fitting": fitting,
        "doctrine_map": doctrine_map,
        "fitting_map": fitting_map,
        "grouped_skills": _group_preview_skills(all_rows),
        "effective_mastery_level": effective_mastery_level,
        "effective_mastery_label": _get_mastery_label(effective_mastery_level),
        "doctrine_default_mastery_level": doctrine_map.default_mastery_level,
        "doctrine_default_mastery_label": _get_mastery_label(doctrine_map.default_mastery_level),
        "fitting_mastery_override": None if not fitting_map else fitting_map.mastery_level,
        "mastery_choices": MASTERY_LEVEL_CHOICES,
        "recommended_choices": list(range(6)),
        "suggestion_count": sum(1 for row in all_rows if row.get("is_suggested")),
        "skill_name_options": _get_skill_name_options(),
        "skillset_skill_count": (
            fitting_map.skillset.skills.count() if fitting_map and fitting_map.skillset else None
        ),
        "last_synced_at": (
            fitting_map.last_synced_at if fitting_map else None
        ),
        "skillset_id": (
            fitting_map.skillset.pk if fitting_map and fitting_map.skillset else None
        ),
        **_build_plan_kpis(active_rows),
        "plan_estimate_sp_per_hour": app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR,
    }


def _format_duration_from_seconds(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _seconds = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _build_plan_kpis(skill_rows: list[dict]) -> dict:
    required_targets = {}
    recommended_targets = {}

    for row in skill_rows:
        skill_type_id = int(row.get("skill_type_id", 0))
        if not skill_type_id:
            continue

        required_level = int(row.get("required_level") or 0)
        recommended_level = int(row.get("recommended_level") or 0)

        if required_level > 0:
            required_targets[skill_type_id] = max(required_targets.get(skill_type_id, 0), required_level)
        if recommended_level > 0:
            recommended_targets[skill_type_id] = max(recommended_targets.get(skill_type_id, 0), recommended_level)

    all_skill_ids = set(required_targets.keys()) | set(recommended_targets.keys())
    rank_by_skill = {skill_id: 1 for skill_id in all_skill_ids}
    if all_skill_ids:
        for row in TypeDogma.objects.filter(
                item_type_id__in=list(all_skill_ids),
                dogma_attribute_id=pilot_progress_service.DOGMA_SKILL_TIME_CONSTANT,
        ).values("item_type_id", "value"):
            rank_by_skill[int(row["item_type_id"])] = max(1, int(row["value"]))

    def _total_sp(targets: dict[int, int]) -> int:
        total = 0
        for skill_type_id, level in targets.items():
            rank = rank_by_skill.get(skill_type_id, 1)
            total += pilot_progress_service._sp_for_level(rank, level)
        return int(total)

    required_total_sp = _total_sp(required_targets)
    recommended_total_sp = _total_sp(recommended_targets)

    required_seconds = int((required_total_sp / app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR) * 3600) if required_total_sp else 0
    recommended_seconds = int((recommended_total_sp / app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR) * 3600) if recommended_total_sp else 0

    return {
        "required_plan_total_sp": required_total_sp,
        "required_plan_total_time": _format_duration_from_seconds(required_seconds),
        "recommended_plan_total_sp": recommended_total_sp,
        "recommended_plan_total_time": _format_duration_from_seconds(recommended_seconds),
    }


def _apply_preview_suggestions(
    fitting,
    doctrine_map,
    *,
    allowed_skill_ids=None,
) -> int:
    """Apply pending suggestion actions and return how many were applied."""
    preview = doctrine_skill_service.preview_fitting(doctrine_map=doctrine_map, fitting=fitting)
    applied_count = 0

    for row in preview["skill_rows"]:
        if not row.get("is_suggested"):
            continue

        skill_type_id = int(row["skill_type_id"])
        if allowed_skill_ids is not None and skill_type_id not in allowed_skill_ids:
            continue

        action = row.get("suggestion_action")
        if action == "remove":
            control_service.set_blacklist(fitting_id=fitting.id, skill_type_id=skill_type_id, value=True)
            applied_count += 1
        elif action == "add":
            control_service.set_blacklist(fitting_id=fitting.id, skill_type_id=skill_type_id, value=False)
            applied_count += 1

    if applied_count:
        doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return applied_count


def _get_member_characters(user):
    return Character.objects.filter(
        eve_character__character_ownership__user=user,
    ).select_related("eve_character").order_by("eve_character__character_name")


def _summary_group_users(summary_group):
    corp_ids = [entry.entity_id for entry in summary_group.entries.all() if
                entry.entity_type == SummaryAudienceEntity.TYPE_CORPORATION]
    alliance_ids = [entry.entity_id for entry in summary_group.entries.all() if
                    entry.entity_type == SummaryAudienceEntity.TYPE_ALLIANCE]
    if not corp_ids and not alliance_ids:
        return User.objects.none()

    filters = Q()
    if corp_ids:
        filters |= Q(profile__main_character__corporation_id__in=corp_ids)
    if alliance_ids:
        filters |= Q(profile__main_character__alliance_id__in=alliance_ids)

    return User.objects.filter(profile__main_character__isnull=False).filter(filters).distinct()


def _get_summary_group_by_id(group_id_raw: str):
    if not group_id_raw:
        return None
    try:
        group_id = int(group_id_raw)
    except (TypeError, ValueError):
        return None
    return SummaryAudienceGroup.objects.filter(id=group_id).prefetch_related("entries").first()


def _get_pilot_detail_characters(user, summary_group=None):
    # Elevated cross-account access is only allowed within an explicit summary group scope.
    if user.has_perm("mastery.doctrine_summary") and summary_group is not None:
        eligible_users = _summary_group_users(summary_group)
        return Character.objects.filter(
            eve_character__character_ownership__user__in=eligible_users,
        ).select_related("eve_character").order_by("eve_character__character_name")

    return _get_member_characters(user)


def _get_accessible_fitting_or_404(user, fitting_id: int):
    fitting = get_object_or_404(Fitting.objects.select_related("ship_type"), id=fitting_id)
    accessible_fit_ids = pilot_access_service.accessible_fitting_ids(user)
    if fitting.pk not in accessible_fit_ids and not user.has_perm("mastery.manage_fittings"):
        raise Http404("Fitting not accessible")

    fitting_map = FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").filter(
        fitting_id=fitting_id).first()
    doctrine = Doctrine.objects.filter(fittings__id=fitting_id).first()

    return fitting, fitting_map, doctrine


def _parse_export_mode(raw_value: str) -> str:
    valid_modes = {mode for mode, _label in pilot_progress_service.export_mode_choices()}
    if raw_value in valid_modes:
        return raw_value
    return pilot_progress_service.EXPORT_MODE_RECOMMENDED


def _parse_export_language(raw_value: str) -> str:
    return pilot_progress_service.normalize_export_language(raw_value)


def _parse_activity_days(raw_value: str, default: int = 14) -> int:
    try:
        days = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        return default
    return max(1, min(days, 90))


def _summary_groups_qs():
    return SummaryAudienceGroup.objects.prefetch_related("entries").order_by("name")


def _get_selected_summary_group(group_id_raw: str):
    groups = list(_summary_groups_qs())
    selected_group = None
    if group_id_raw:
        try:
            group_id = int(group_id_raw)
        except (TypeError, ValueError):
            group_id = None
        if group_id is not None:
            selected_group = next((group for group in groups if group.id == group_id), None)

    if selected_group is None and groups:
        selected_group = groups[0]

    return groups, selected_group


def _build_member_groups_for_summary(summary_group, activity_days: int, include_inactive: bool):
    if summary_group is None:
        return []

    eligible_users = _summary_group_users(summary_group)
    if not eligible_users.exists():
        return []

    cutoff = timezone.now() - timedelta(days=activity_days)
    groups = {}

    characters = Character.objects.filter(
        eve_character__character_ownership__user__in=eligible_users,
    ).select_related(
        "eve_character__character_ownership__user__profile__main_character",
        "online_status",
    )

    for character in characters:
        ownership = getattr(character.eve_character, "character_ownership", None)
        owner = None if ownership is None else ownership.user
        if owner is None:
            continue

        online_status = getattr(character, "online_status", None)
        last_login = None if online_status is None else online_status.last_login
        last_logout = None if online_status is None else online_status.last_logout
        last_seen = None
        for ts in (last_login, last_logout):
            if ts is None:
                continue
            if last_seen is None or ts > last_seen:
                last_seen = ts
        is_active = include_inactive or (last_seen is not None and last_seen >= cutoff)

        group = groups.setdefault(
            owner.id,
            {
                "user": owner,
                "main_character": getattr(owner.profile, "main_character", None),
                "characters": [],
                "active_count": 0,
                "total_count": 0,
                "last_seen": None,
            },
        )
        group["total_count"] += 1
        if last_seen and (group["last_seen"] is None or last_seen > group["last_seen"]):
            group["last_seen"] = last_seen

        if is_active:
            group["characters"].append(character)
            group["active_count"] += 1

    results = [obj for obj in groups.values() if obj["characters"]]
    return sorted(
        results,
        key=lambda x: (
            ((x["main_character"].character_name if x["main_character"] else x["user"].username) or "").lower()
        ),
    )


def _summary_entity_catalog() -> tuple[list[dict], list[dict]]:
    corp_map = {}
    alliance_map = {}

    for eve_char in EveCharacter.objects.all():

        corp_id = eve_char.corporation_id
        if corp_id:
            corp_obj = corp_map.setdefault(
                corp_id,
                {
                    "id": corp_id,
                    "name": eve_char.corporation_name or f"Corporation #{corp_id}",
                    "count": 0,
                },
            )
            corp_obj["count"] += 1

        alliance_id = eve_char.alliance_id
        if alliance_id:
            alliance_obj = alliance_map.setdefault(
                alliance_id,
                {
                    "id": alliance_id,
                    "name": eve_char.alliance_name or f"Alliance #{alliance_id}",
                    "count": 0,
                },
            )
            alliance_obj["count"] += 1

    corporations = sorted(corp_map.values(), key=lambda x: (x["name"] or "").lower())
    alliances = sorted(alliance_map.values(), key=lambda x: (x["name"] or "").lower())
    return corporations, alliances


def _progress_for_character(skillset, character, progress_cache: dict):
    cache_key = (skillset.id, character.id)
    if cache_key not in progress_cache:
        progress_cache[cache_key] = pilot_progress_service.build_for_character(
            character=character,
            skillset=skillset,
        )
    return progress_cache[cache_key]


def _build_fitting_user_rows(fitting_map: FittingSkillsetMap, member_groups: list, progress_cache: dict) -> list:
    rows = []
    for group in member_groups:
        progress_rows = []
        for character in group["characters"]:
            progress = _progress_for_character(
                skillset=fitting_map.skillset,
                character=character,
                progress_cache=progress_cache,
            )
            progress_rows.append({"character": character, "progress": progress})

        if not progress_rows:
            continue

        best_row = max(
            progress_rows,
            key=lambda row: (
                row["progress"]["can_fly"],
                row["progress"]["recommended_pct"],
                row["progress"]["required_pct"],
            ),
        )
        flyable_count = sum(1 for row in progress_rows if row["progress"]["can_fly"])
        rows.append(
            {
                "user": group["user"],
                "main_character": group["main_character"],
                "best_character": best_row["character"],
                "best_progress": best_row["progress"],
                "flyable_count": flyable_count,
                "active_count": len(progress_rows),
                "total_count": group["total_count"],
                "last_seen": group["last_seen"],
                "character_rows": progress_rows,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["best_progress"]["can_fly"],
            row["flyable_count"],
            row["best_progress"]["recommended_pct"],
            row["best_progress"]["required_pct"],
        ),
        reverse=True,
    )


def _build_doctrine_summary(doctrine, fitting_maps: dict, member_groups: list, progress_cache: dict) -> dict:
    fittings = []
    users_with_any_flyable = set()
    unique_fittings = []
    seen_fit_ids = set()
    for fitting in doctrine.fittings.all():
        if fitting.id in seen_fit_ids:
            continue
        seen_fit_ids.add(fitting.id)
        unique_fittings.append(fitting)

    for fitting in unique_fittings:
        fitting_map = fitting_maps.get(fitting.id)
        if not fitting_map or not fitting_map.skillset:
            fittings.append(
                {
                    "fitting": fitting,
                    "configured": False,
                    "users_total": 0,
                    "users_with_flyable": 0,
                    "best_required_pct": 0,
                    "best_recommended_pct": 0,
                    "user_rows": [],
                }
            )
            continue

        user_rows = _build_fitting_user_rows(
            fitting_map=fitting_map,
            member_groups=member_groups,
            progress_cache=progress_cache,
        )
        for row in user_rows:
            if row["flyable_count"] > 0:
                users_with_any_flyable.add(row["user"].id)

        fittings.append(
            {
                "fitting": fitting,
                "fitting_map": fitting_map,
                "configured": True,
                "users_total": len(user_rows),
                "users_with_flyable": sum(1 for row in user_rows if row["flyable_count"] > 0),
                "best_required_pct": max((row["best_progress"]["required_pct"] for row in user_rows), default=0),
                "best_recommended_pct": max((row["best_progress"]["recommended_pct"] for row in user_rows), default=0),
                "user_rows": user_rows,
            }
        )

    configured_fittings = [obj for obj in fittings if obj["configured"]]
    return {
        "doctrine": doctrine,
        "fittings": fittings,
        "fittings_total": len(unique_fittings),
        "configured_fittings": len(configured_fittings),
        "users_tracked": len(member_groups),
        "users_with_any_flyable": len(users_with_any_flyable),
        "active_characters_total": sum(group["active_count"] for group in member_groups),
    }


@login_required
@permissions_required('mastery.basic_access')
def index(request):
    doctrines = pilot_access_service.accessible_doctrines(request.user)
    member_characters = list(_get_member_characters(request.user))
    selected_character_id = request.GET.get("character_id")
    selected_status = (request.GET.get("status") or "all").strip().lower()
    search_query = (request.GET.get("q") or "").strip().lower()

    try:
        selected_character_id = int(selected_character_id) if selected_character_id else None
    except (TypeError, ValueError):
        selected_character_id = None

    selected_character = None
    if selected_character_id:
        for character in member_characters:
            if character.id == selected_character_id:
                selected_character = character
                break

    fitting_maps = {
        obj.fitting.pk: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
    }

    doctrine_cards = []
    configured_fittings_count = 0
    flyable_fittings_count = 0
    for doctrine in doctrines:
        fitting_cards = []
        seen_fitting_ids = set()
        for fitting in doctrine.fittings.all():
            if fitting.id in seen_fitting_ids:
                continue
            seen_fitting_ids.add(fitting.id)

            fitting_map = fitting_maps.get(fitting.id)
            if not fitting_map:
                if search_query and search_query not in doctrine.name.lower() and search_query not in fitting.name.lower() and search_query not in fitting.ship_type.name.lower():
                    continue
                fitting_cards.append(
                    {
                        "fitting": fitting,
                        "is_configured": False,
                        "characters": [],
                        "best_required_pct": 0,
                        "best_recommended_pct": 0,
                        "can_any_fly": False,
                        "selected_progress": None,
                    }
                )
                continue

            character_rows = []
            for character in member_characters:
                progress = pilot_progress_service.build_for_character(
                    character=character,
                    skillset=fitting_map.skillset,
                )
                character_rows.append(
                    {
                        "character": character,
                        "progress": progress,
                    }
                )

            selected_progress = None
            if selected_character_id:
                for row in character_rows:
                    if row["character"].id == selected_character_id:
                        selected_progress = row["progress"]
                        break

            progress_for_filter = selected_progress
            if progress_for_filter is None and character_rows:
                progress_for_filter = max(character_rows,
                                          key=lambda row: (row["progress"]["can_fly"], row["progress"]["required_pct"],
                                                           row["progress"]["recommended_pct"]))["progress"]

            if search_query and search_query not in doctrine.name.lower() and search_query not in fitting.name.lower() and search_query not in fitting.ship_type.name.lower():
                continue

            if selected_status == "flyable" and (not progress_for_filter or not progress_for_filter["can_fly"]):
                continue
            if selected_status == "training":
                if selected_character_id:
                    # Un personnage ciblé : on filtre sur lui
                    if not progress_for_filter or progress_for_filter["can_fly"]:
                        continue
                else:
                    # "Best character available" : afficher si au moins un personnage a encore besoin de s'entraîner
                    if character_rows and all(row["progress"]["can_fly"] for row in character_rows):
                        continue
                    elif not character_rows and (not progress_for_filter or progress_for_filter["can_fly"]):
                        continue
            if selected_status == "elite" and (
                    not progress_for_filter or progress_for_filter["status_label"] != "Elite ready"):
                continue

            configured_fittings_count += 1
            if progress_for_filter and progress_for_filter["can_fly"]:
                flyable_fittings_count += 1

            fitting_cards.append(
                {
                    "fitting": fitting,
                    "is_configured": True,
                    "skillset": fitting_map.skillset,
                    "characters": character_rows,
                    "best_required_pct": max((row["progress"]["required_pct"] for row in character_rows), default=0),
                    "best_recommended_pct": max((row["progress"]["recommended_pct"] for row in character_rows),
                                                default=0),
                    "can_any_fly": any(row["progress"]["can_fly"] for row in character_rows),
                    "selected_progress": selected_progress,
                }
            )

        if fitting_cards:
            doctrine_cards.append(
                {
                    "doctrine": doctrine,
                    "fittings": sorted(fitting_cards, key=lambda x: x["fitting"].name.lower()),
                }
            )

    context = {
        "doctrine_cards": doctrine_cards,
        "character_count": len(member_characters),
        "member_characters": member_characters,
        "selected_character": selected_character,
        "selected_character_id": selected_character_id,
        "selected_status": selected_status,
        "search_query": request.GET.get("q", ""),
        "configured_fittings_count": configured_fittings_count,
        "flyable_fittings_count": flyable_fittings_count,
    }
    return render(request, "mastery/index.html", context)


@login_required
@permissions_required('mastery.basic_access')
def pilot_fitting_detail_view(request, fitting_id):
    fitting, fitting_map, doctrine = _get_accessible_fitting_or_404(request.user, fitting_id)
    if not fitting_map:
        return HttpResponseBadRequest("No skillset configured for this fitting yet")

    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    export_language = _parse_export_language(request.GET.get("export_language"))
    raw_group_id = request.GET.get("group_id")
    summary_group = _get_summary_group_by_id(raw_group_id)
    if request.user.has_perm("mastery.doctrine_summary") and raw_group_id and summary_group is None:
        return HttpResponseBadRequest("Invalid summary group")
    member_characters = list(_get_pilot_detail_characters(request.user, summary_group=summary_group))
    character_rows = []
    for character in member_characters:
        progress = pilot_progress_service.build_for_character(
            character=character,
            skillset=fitting_map.skillset,
        )
        character_rows.append(
            {
                "character": character,
                "progress": progress,
            }
        )

    selected_character = None
    selected_progress = None
    selected_character_id = request.GET.get("character_id")
    if selected_character_id:
        try:
            selected_character_id = int(selected_character_id)
        except (TypeError, ValueError):
            selected_character_id = None

    if selected_character_id:
        for row in character_rows:
            if row["character"].id == selected_character_id:
                selected_character = row["character"]
                selected_progress = row["progress"]
                break

    if selected_character is None and character_rows:
        selected_character = character_rows[0]["character"]
        selected_progress = character_rows[0]["progress"]

    if selected_progress is not None:
        # Keep display labels in sync with chosen export language.
        selected_progress = {
            **selected_progress,
            "missing_required": pilot_progress_service.localize_missing_rows(
                selected_progress.get("missing_required", []),
                language=export_language,
            ),
            "missing_recommended": pilot_progress_service.localize_missing_rows(
                selected_progress.get("missing_recommended", []),
                language=export_language,
            ),
        }

    export_lines = [] if not selected_progress else pilot_progress_service.build_export_lines(
        selected_progress,
        export_mode,
        character=selected_character,
        language=export_language,
    )
    export_mode_labels = dict(pilot_progress_service.export_mode_choices())
    selected_mode_stats = None if not selected_progress else (
            selected_progress.get("mode_stats", {}).get(export_mode)
            or selected_progress.get("mode_stats", {}).get(pilot_progress_service.EXPORT_MODE_RECOMMENDED)
    )

    context = {
        "fitting": fitting,
        "doctrine": doctrine,
        "skillset": fitting_map.skillset,
        "character_rows": character_rows,
        "selected_character": selected_character,
        "selected_progress": selected_progress,
        "export_mode": export_mode,
        "export_mode_choices": pilot_progress_service.export_mode_choices(),
        "export_mode_label": export_mode_labels.get(export_mode, export_mode.title()),
        "selected_mode_stats": selected_mode_stats,
        "selected_export_lines": export_lines,
        "export_language": export_language,
        "export_language_scope_label": "Affects export and selected missing-skill labels",
        "export_language_choices": pilot_progress_service.export_language_choices(),
        "summary_group_id": None if summary_group is None else summary_group.id,
    }
    return render(request, "mastery/pilot_fitting_detail.html", context)


@login_required
@permissions_required('mastery.basic_access')
def pilot_fitting_skillplan_export_view(request, fitting_id):
    fitting, fitting_map, _ = _get_accessible_fitting_or_404(request.user, fitting_id)
    if not fitting_map:
        return HttpResponseBadRequest("No skillset configured for this fitting yet")

    character_id = request.GET.get("character_id")
    if not character_id:
        return HttpResponseBadRequest("character_id is required")

    try:
        character_id = int(character_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("invalid character_id")

    raw_group_id = request.GET.get("group_id")
    summary_group = _get_summary_group_by_id(raw_group_id)
    if request.user.has_perm("mastery.doctrine_summary") and raw_group_id and summary_group is None:
        return HttpResponseBadRequest("Invalid summary group")
    character = _get_pilot_detail_characters(request.user, summary_group=summary_group).filter(id=character_id).first()
    if character is None:
        return HttpResponseBadRequest("character not found")

    export_mode = _parse_export_mode(request.GET.get("mode"))
    export_language = _parse_export_language(request.GET.get("language"))
    progress = pilot_progress_service.build_for_character(character=character, skillset=fitting_map.skillset)
    lines = pilot_progress_service.build_export_lines(progress, export_mode, character=character,
                                                      language=export_language)
    content = "\n".join(lines) if lines else "No missing skills for this fitting."

    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response[
        "Content-Disposition"] = f'attachment; filename="skillplan-{export_mode}-fit-{fitting.id}-char-{character.id}.txt"'
    return response


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_list_view(request):
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    search_query = (request.GET.get("q") or "").strip().lower()
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    doctrines = pilot_access_service.accessible_doctrines(request.user).prefetch_related("fittings__ship_type")
    fitting_maps = {
        obj.fitting_id: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
    }
    progress_cache = {}

    doctrine_summaries = []
    for doctrine in doctrines:
        if search_query and search_query not in doctrine.name.lower():
            fitting_names = [f"{fit.name} {fit.ship_type.name}".lower() for fit in doctrine.fittings.all()]
            if not any(search_query in name for name in fitting_names):
                continue
        doctrine_summaries.append(
            _build_doctrine_summary(
                doctrine=doctrine,
                fitting_maps=fitting_maps,
                member_groups=member_groups,
                progress_cache=progress_cache,
            )
        )

    context = {
        "doctrine_summaries": doctrine_summaries,
        "summary_groups": summary_groups,
        "selected_group": selected_group,
        "activity_days": activity_days,
        "include_inactive": include_inactive,
        "search_query": request.GET.get("q", ""),
        "member_count": len(member_groups),
        "active_character_count": sum(group["active_count"] for group in member_groups),
    }
    return render(request, "mastery/summary_list_view.html", context)


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_doctrine_detail_view(request, doctrine_id):
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest("No summary group configured")

    doctrine = get_object_or_404(
        pilot_access_service.accessible_doctrines(request.user).prefetch_related("fittings__ship_type"),
        id=doctrine_id,
    )
    fitting_maps = {
        obj.fitting_id: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
    }
    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )
    progress_cache = {}
    summary = _build_doctrine_summary(
        doctrine=doctrine,
        fitting_maps=fitting_maps,
        member_groups=member_groups,
        progress_cache=progress_cache,
    )

    return render(
        request,
        "mastery/summary_doctrine_detail.html",
        {
            "summary": summary,
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "activity_days": activity_days,
            "include_inactive": include_inactive,
        },
    )


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_fitting_detail_view(request, fitting_id):
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest("No summary group configured")

    fitting, fitting_map, doctrine = _get_accessible_fitting_or_404(request.user, fitting_id)
    if not fitting_map or not fitting_map.skillset:
        return HttpResponseBadRequest("No skillset configured for this fitting yet")

    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    progress_cache = {}
    user_rows = _build_fitting_user_rows(
        fitting_map=fitting_map,
        member_groups=member_groups,
        progress_cache=progress_cache,
    )

    return render(
        request,
        "mastery/summary_fitting_detail.html",
        {
            "fitting": fitting,
            "fitting_map": fitting_map,
            "doctrine": doctrine,
            "user_rows": user_rows,
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "activity_days": activity_days,
            "include_inactive": include_inactive,
            "export_mode": export_mode,
            "export_mode_choices": pilot_progress_service.export_mode_choices(),
        },
    )


@login_required
@permissions_required('mastery.manage_summary_groups')
def summary_settings_view(request):
    selected_group_id = request.GET.get("group_id")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_group":
            name = (request.POST.get("name") or "").strip()
            description = (request.POST.get("description") or "").strip()
            if not name:
                return HttpResponseBadRequest("name is required")
            SummaryAudienceGroup.objects.create(name=name, description=description)
            messages.success(request, "Summary group created")
            return redirect("mastery:summary_settings")

        if action == "delete_group":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            group.delete()
            messages.success(request, "Summary group deleted")
            return redirect("mastery:summary_settings")

        if action == "toggle_group_active":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            group.is_active = not group.is_active
            group.save(update_fields=["is_active"])
            messages.success(request, "Summary group updated")
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group.id}")

        if action == "add_entry":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            entity_type = request.POST.get("entity_type")
            if entity_type not in {SummaryAudienceEntity.TYPE_CORPORATION, SummaryAudienceEntity.TYPE_ALLIANCE}:
                return HttpResponseBadRequest("invalid entity_type")
            try:
                entity_id = int(request.POST.get("entity_id"))
            except (TypeError, ValueError):
                return HttpResponseBadRequest("invalid entity_id")
            label = (request.POST.get("label") or "").strip()

            SummaryAudienceEntity.objects.update_or_create(
                group=group,
                entity_type=entity_type,
                entity_id=entity_id,
                defaults={"label": label},
            )
            messages.success(request, "Entry saved")
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group.id}")

        if action == "delete_entry":
            entry = get_object_or_404(SummaryAudienceEntity, id=request.POST.get("entry_id"))
            group_id = entry.group_id
            entry.delete()
            messages.success(request, "Entry deleted")
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group_id}")

        return HttpResponseBadRequest("Unsupported action")

    summary_groups, selected_group = _get_selected_summary_group(selected_group_id)
    corporation_options, alliance_options = _summary_entity_catalog()

    corp_name_map = {obj["id"]: obj["name"] for obj in corporation_options}
    alliance_name_map = {obj["id"]: obj["name"] for obj in alliance_options}
    selected_group_entries = []
    existing_corp_ids = set()
    existing_alliance_ids = set()
    if selected_group:
        for entry in selected_group.entries.all():
            if entry.entity_type == SummaryAudienceEntity.TYPE_CORPORATION:
                entity_name = corp_name_map.get(entry.entity_id) or f"Corporation #{entry.entity_id}"
                existing_corp_ids.add(entry.entity_id)
            else:
                entity_name = alliance_name_map.get(entry.entity_id) or f"Alliance #{entry.entity_id}"
                existing_alliance_ids.add(entry.entity_id)
            selected_group_entries.append(
                {
                    "entry": entry,
                    "entity_name": entity_name,
                }
            )

    corporation_options = [obj for obj in corporation_options if obj["id"] not in existing_corp_ids]
    alliance_options = [obj for obj in alliance_options if obj["id"] not in existing_alliance_ids]

    return render(
        request,
        "mastery/summary_settings.html",
        {
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "selected_group_entries": selected_group_entries,
            "entity_type_choices": SummaryAudienceEntity.TYPE_CHOICES,
            "corporation_options": corporation_options,
            "alliance_options": alliance_options,
        },
    )


@login_required
@permissions_required('mastery.manage_fittings')
def fitting_skills_view(request, fitting_id):
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)
        fitting_map = FittingSkillsetMap.objects.filter(fitting_id=fitting_id).first()

    context = _build_fitting_preview_context(
        fitting=fitting,
        doctrine_map=doctrine_map,
        fitting_map=fitting_map,
    )
    context["doctrine"] = doctrine

    return render(request, "mastery/fitting_skills.html", context)


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

        data.append({
            "id": doctrine.pk,
            "name": doctrine.name,
            "initialized": initialized,
            "total": total,
            "configured": configured,
            "icon_url": doctrine.icon_url,
            "default_mastery_level": None if doctrine_map is None else doctrine_map.default_mastery_level,
            "default_mastery_label": None if doctrine_map is None else _get_mastery_label(
                doctrine_map.default_mastery_level),
        })

    return render(request, "mastery/doctrine_list.html", {
        "doctrines": data
    })


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

        fittings_data.append({
            "id": fitting.id,
            "name": fitting.name,
            "ship_type_id": fitting.ship_type_type_id,
            "ship_name": fitting.ship_type.name,
            "configured": fitting_map is not None,
            "mastery_override": override_level,
            "effective_mastery_level": effective_level,
            "effective_mastery_label": _get_mastery_label(effective_level),
        })

    return render(request, "mastery/doctrine_detail.html", {
        "doctrine": doctrine,
        "doctrine_map": doctrine_map,
        "doctrine_default_mastery_level": 4 if doctrine_map is None else doctrine_map.default_mastery_level,
        "doctrine_default_mastery_label": _get_mastery_label(
            4 if doctrine_map is None else doctrine_map.default_mastery_level),
        "mastery_choices": MASTERY_LEVEL_CHOICES,
        "fittings": fittings_data,
    })


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


@login_required
@permissions_required('mastery.manage_fittings')
def update_fitting_mastery(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    doctrine_id = request.POST.get("doctrine_id")
    doctrine = get_object_or_404(Doctrine, id=doctrine_id)
    fitting = get_object_or_404(Fitting, id=fitting_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    fitting_map = fitting_map_service.create_fitting_map(doctrine_map, fitting)
    try:
        fitting_map.mastery_level = _parse_mastery_level(request.POST.get("mastery_level"))
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))
    fitting_map.save(update_fields=["mastery_level"])

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def toggle_skill_blacklist_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))
    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    current_blacklist = control_service.get_blacklist(fitting_id)
    should_blacklist = request.POST.get("value")

    if should_blacklist in ("true", "false"):
        value = should_blacklist == "true"
    else:
        value = skill_type_id not in current_blacklist

    control_service.set_blacklist(fitting_id=fitting_id, skill_type_id=skill_type_id, value=value)
    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def update_skill_recommended_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))
    raw_level = request.POST.get("recommended_level")
    try:
        level = None if raw_level in (None, "") else _parse_posted_int(raw_level, "recommended_level")
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    if level is not None and level not in range(0, 6):
        return HttpResponseBadRequest("recommended_level must be between 0 and 5")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    control_service.set_recommended_level(
        fitting_id=fitting_id,
        skill_type_id=skill_type_id,
        level=level,
    )
    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def update_skill_group_controls_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        skill_type_ids = [
            _parse_posted_int(skill_type_id, "skill_type_ids")
            for skill_type_id in request.POST.getlist("skill_type_ids")
            if skill_type_id not in (None, "")
        ]
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    if not skill_type_ids:
        return HttpResponseBadRequest("No skills provided")

    action = request.POST.get("action")
    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    if action == "blacklist_group":
        control_service.set_blacklist_batch(fitting_id=fitting_id, skill_type_ids=skill_type_ids, value=True)
    elif action == "unblacklist_group":
        control_service.set_blacklist_batch(fitting_id=fitting_id, skill_type_ids=skill_type_ids, value=False)
    elif action in {"set_group_recommended", "clear_group_recommended"}:
        level = None
        if action == "set_group_recommended":
            raw_level = request.POST.get("recommended_level")
            try:
                level = None if raw_level in (None, "") else _parse_posted_int(raw_level, "recommended_level")
            except ValueError as ex:
                return HttpResponseBadRequest(str(ex))
            if level is not None and level not in range(0, 6):
                return HttpResponseBadRequest("recommended_level must be between 0 and 5")

        control_service.set_recommended_level_batch(
            fitting_id=fitting_id,
            skill_type_ids=skill_type_ids,
            level=level,
        )
    else:
        return HttpResponseBadRequest("Unsupported action")

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def add_manual_skill_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    skill_name = (request.POST.get("skill_name") or "").strip()
    if not skill_name:
        return HttpResponseBadRequest("skill_name is required")

    try:
        recommended_level = _parse_posted_int(request.POST.get("recommended_level"), "recommended_level")
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    if recommended_level not in range(0, 6):
        return HttpResponseBadRequest("recommended_level must be between 0 and 5")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    skill = ItemType.objects.filter(
        name__iexact=skill_name,
        group__category__name__iexact="Skill",
    ).first()
    if skill is None:
        return HttpResponseBadRequest(f"Skill not found: {skill_name}")

    control_service.add_manual_skill(
        fitting_id=fitting_id,
        skill_type_id=skill.id,
        level=recommended_level,
    )

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def remove_manual_skill_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    control_service.remove_manual_skill(fitting_id=fitting_id, skill_type_id=skill_type_id)
    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def apply_suggestions_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        return HttpResponseBadRequest("No doctrine map found for fitting")

    applied_count = _apply_preview_suggestions(fitting=fitting, doctrine_map=doctrine_map)
    if applied_count:
        messages.success(request, f"Applied {applied_count} suggestion(s)")
    else:
        messages.info(request, "No pending suggestion to apply")

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def apply_group_suggestions_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        return HttpResponseBadRequest("No doctrine map found for fitting")

    try:
        allowed_skill_ids = {
            _parse_posted_int(skill_type_id, "skill_type_ids")
            for skill_type_id in request.POST.getlist("skill_type_ids")
            if skill_type_id not in (None, "")
        }
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    if not allowed_skill_ids:
        return HttpResponseBadRequest("No skills provided")

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        allowed_skill_ids=allowed_skill_ids,
    )
    if applied_count:
        messages.success(request, f"Applied {applied_count} suggestion(s) for this group")
    else:
        messages.info(request, "No pending suggestion in this group")

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def apply_skill_suggestion_view(request, fitting_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        return HttpResponseBadRequest("No doctrine map found for fitting")

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        allowed_skill_ids={skill_type_id},
    )
    if applied_count:
        messages.success(request, "Suggestion applied")
    else:
        messages.info(request, "No pending suggestion for this skill")

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect('mastery:fitting_skills', fitting_id=fitting_id)


@login_required
@permissions_required('mastery.manage_fittings')
def fitting_skills_preview_view(request, fitting_id):
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)
        fitting_map = FittingSkillsetMap.objects.filter(fitting_id=fitting_id).first()

    try:
        mastery_level = _parse_mastery_level(request.GET.get("mastery_level"))
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    context = _build_fitting_preview_context(
        fitting=fitting,
        doctrine_map=doctrine_map,
        fitting_map=fitting_map,
        mastery_level=mastery_level,
    )

    return render(request, "mastery/partials/fitting_skill_preview.html", context)
