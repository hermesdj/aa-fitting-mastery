"""General / miscellaneous mastery models."""
from django.db import models
from django.utils.translation import gettext_lazy as _


class General(models.Model):
    """
    Dummy model used solely to host app-level permissions.
    No database table is managed for this model.
    """

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        managed = False
        default_permissions = ()
        permissions = (
            ("basic_access", _("Can access the Fitting Mastery app")),
            ("manage_fittings", _("Can manage fitting skill plans")),
            ("doctrine_summary", _("Can view doctrine summaries")),
            ("manage_summary_groups", _("Can manage doctrine summary groups")),
        )
