from django.db import models

class SdeVersion(models.Model):
    build_number = models.BigIntegerField()
    release_date = models.DateTimeField()

    imported_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)