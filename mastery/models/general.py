"""General / miscellaneous mastery models."""
from django.db import models


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
            ("basic_access", "Can access the Fitting Mastery app"),
            ("manage_fittings", "Can manage fitting skill plans"),
            ("doctrine_summary", "Can view doctrine summaries"),
            ("manage_summary_groups", "Can manage doctrine summary groups"),
        )
