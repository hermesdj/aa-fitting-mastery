from django.db.models import Q

from fittings.models import Category, Doctrine, Fitting


class PilotAccessService:
    @staticmethod
    def _accessible_category_ids(user) -> set[int]:
        if user.has_perm("fittings.manage"):
            return set(Category.objects.values_list("id", flat=True))

        public_ids = set(Category.objects.filter(groups__isnull=True).values_list("id", flat=True))
        group_ids = set(
            Category.objects.filter(groups__in=user.groups.all()).values_list("id", flat=True)
        )
        return public_ids | group_ids

    def accessible_fitting_ids(self, user) -> set[int]:
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
        qs = Doctrine.objects.prefetch_related("fittings__ship_type", "category").order_by("name")
        if user.has_perm("fittings.manage"):
            return qs

        category_ids = self._accessible_category_ids(user)
        return qs.filter(Q(category__isnull=True) | Q(category__id__in=category_ids)).distinct()

