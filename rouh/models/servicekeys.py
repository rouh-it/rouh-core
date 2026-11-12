"""The keys and settings of the services this Rouh uses, typed into Anatomy, Connections, Keys
(`rouh/service_keys.py`): one row for each of the organisation's values, sealed with this
instance's key (`rouh/encryption.py`). Never given back: the page is told whether a secret is
set, its last four and when; only a value that is no secret (a chat id, an address) is shown."""
from django.db import models


class ServiceKey(models.Model):
    pk = models.CompositePrimaryKey("org_id", "name")
    org_id = models.TextField()
    #: The setting's own name, as the settings file has it: ELEVENLABS_API_KEY, ROUH_MAIL_FROM.
    name = models.TextField()
    value_sealed = models.TextField()
    last4 = models.TextField(blank=True, default="")
    saved_by = models.TextField(blank=True, default="")
    saved_at = models.FloatField(default=0)

    class Meta:
        db_table = "service_key"


class ServiceCheck(models.Model):
    """How a service's values last fared when checked with the service: never a value."""

    pk = models.CompositePrimaryKey("org_id", "service")
    org_id = models.TextField()
    service = models.TextField()
    checked_at = models.FloatField(default=0)
    ok = models.BooleanField(null=True)
    said = models.TextField(blank=True, default="")

    class Meta:
        db_table = "service_check"
