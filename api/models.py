from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class IdempotencyRecord(models.Model):
    """One record per write the phone asked to be performed exactly once.

    A supervisor saves a day's entry on a farm with no signal. The phone holds
    it and sends it when the connection returns — but "the connection returned"
    is not the same as "the first attempt failed". A request that reached the
    server and was answered on a link that died before the answer arrived looks
    identical, from the phone, to one that never landed. Replaying it blind
    files the day twice, and a duplicated mortality figure moves stock.

    So the phone stamps each queued write with a key it generates once, and
    keeps that key across every retry. The first request to arrive with a key
    does the work and its response is stored here; anything later carrying the
    same key is answered from this row without touching the database again.

    Scoped to the user, not global: two phones must never be able to collide on
    a guessed key, and one user's stored response must never be served to
    another. ``response`` is null while the first attempt is still running,
    which is how a second request arriving mid-flight is told to wait.
    """

    key = models.CharField(max_length=100, help_text=_("Client-generated, unique per write"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="idempotency_records")
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Idempotency Record")
        verbose_name_plural = _("Idempotency Records")
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="uniq_idempotency_user_key"),
        ]
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self):
        return f"{self.method} {self.path} [{self.key}]"
