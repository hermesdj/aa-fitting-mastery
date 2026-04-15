"""Determines which doctrines/fittings a pilot can access."""
from django.db.models import Q

from fittings.models import Category, Doctrine, Fitting


class PilotAccessService:
    """Resolve which fittings and doctrines a user is allowed to view."""

    @staticmethod
    def _can_access_fittings(user) -> bool:
        """Return whether the user has at least one fitting-access permission."""
        return user.has_perm("fittings.manage") or user.has_perm("fittings.access_fittings")

    @staticmethod
    def _accessible_category_ids(user) -> set[int]:
        """Return fitting category IDs visible to this user through groups/perms."""
        if user.has_perm("fittings.manage"):
            return set(Category.objects.values_list("id", flat=True))

        public_ids = set(Category.objects.filter(groups__isnull=True).values_list("id", flat=True))
        group_ids = set(
            Category.objects.filter(groups__in=user.groups.all()).values_list("id", flat=True)
        )
        return public_ids | group_ids

    def accessible_fitting_ids(self, user) -> set[int]:
        """Return IDs of fittings directly or indirectly accessible to the user."""
        if not self._can_access_fittings(user):
            return set()

        if user.has_perm("fittings.manage"):
            return set(Fitting.objects.values_list("id", flat=True))

        category_ids = self._accessible_category_ids(user)
        fit_ids = set(
            Fitting.objects.filter(
                Q(category__isnull=True)
                | Q(category__id__in=category_ids)
                | Q(doctrines__category__isnull=True)
                | Q(doctrines__category__id__in=category_ids)
            )
            .distinct()
            .values_list("id", flat=True)
        )
        return fit_ids

    def accessible_doctrines(self, user):
        """Return doctrine queryset filtered by user's category visibility."""
        qs = Doctrine.objects.prefetch_related("fittings__ship_type", "category").order_by("name")
        if not self._can_access_fittings(user):
            return qs.none()

        if user.has_perm("fittings.manage"):
            return qs

        category_ids = self._accessible_category_ids(user)
        return qs.filter(Q(category__isnull=True) | Q(category__id__in=category_ids)).distinct()
