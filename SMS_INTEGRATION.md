# SMS Integration (SMSGatewayHub)

Provider-agnostic SMS notifications for Hitech BIMS. Business code calls a
single service; the provider, retries, validation, templating and logging are
handled inside the `notification` app. Swapping SMSGatewayHub for MSG91,
Twilio, TextLocal or AWS SNS later means adding one provider class — no caller
changes.

---

## Architecture

```
notification/
├── conf.py                 # Reads all SMS_* settings into an SmsConfig (one place)
├── constants.py            # Statuses, provider names, modules, provider error codes
├── dtos.py                 # SmsResult (structured, immutable outcome)
├── exceptions.py           # SmsError hierarchy (transient vs permanent)
├── validators.py           # Phone normalisation, message length, log masking
├── retry.py                # Exponential-backoff retry for transient failures only
├── templates_catalog.py    # Per-module template defaults (source of truth + fallback)
├── models.py               # SmsTemplate: admin-editable template overrides
├── admin.py                # SmsTemplate admin (create/edit/enable templates)
├── providers/
│   ├── base.py             # SmsProvider ABC: send(phone, message) -> SmsResult
│   ├── smsgatewayhub.py    # The ONLY SMSGatewayHub-specific code
│   └── mock.py             # In-memory provider (dev / tests, no network)
├── services/
│   ├── sms_service.py      # SmsService.send_sms / send_template  ← business entry point
│   └── template_service.py # Resolve + render templates (DB override → catalogue)
└── management/commands/
    ├── seed_sms_templates.py  # Seed editable templates from the catalogue
    └── send_test_sms.py       # CLI smoke test
```

**Layering:** business code → `SmsService` → `SmsProvider` → gateway.
Provider details never leak upward; a failed SMS never raises to the caller.

### Design decisions

- **No Celery.** The project does not use Celery and none was added. Sends are
  synchronous but fully isolated behind `SmsService`, so a Celery/RQ task can
  later wrap `send_sms` with zero changes to callers.
- **No existing schema touched.** The only new table is `notification_smstemplate`
  inside the new app.
- **Editable templates.** Templates live in code (defaults/fallback) *and* in the
  database (admin-editable overrides), so wording changes need no deploy.

---

## Environment variables

All are optional; SMS stays disabled until `SMS_ENABLED=True`. See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `SMS_ENABLED` | `True` | Master switch. `False` → nothing is sent. |
| `SMS_MOCK` | `FALSE` | Route to in-memory mock provider (no network/cost). |
| `SMS_PROVIDER` | `smsgatewayhub` | Provider selector. |
| `SMS_TIMEOUT` | `10` | Per-request timeout (seconds). |
| `SMS_MAX_RETRIES` | `2` | Extra attempts after the first, transient failures only. |
| `SMS_RETRY_BACKOFF` | `0.5` | Base backoff seconds; attempt _n_ waits `backoff·2ⁿ`. |
| `SMS_DEFAULT_COUNTRY_CODE` | `91` | Prepended to bare national numbers. |
| `SMS_MAX_LENGTH` | `1000` | Hard cap on message length. |
| `SMS_GATEWAYHUB_BASE_URL` | `https://www.smsgatewayhub.com` | API base URL. |
| `SMS_GATEWAYHUB_API_KEY` | `5pvGZ0sHkUis0D88uHDNBA` | **Secret.** Account API key. |
| `SMS_GATEWAYHUB_SENDER_ID` | `HTFARM` | Approved sender/header ID. |
| `SMS_GATEWAYHUB_ROUTE` | `1` | Provider route. |
| `SMS_GATEWAYHUB_CHANNEL` | `2` | `2` = transactional, `1` = promotional. |
| `SMS_GATEWAYHUB_DCS` | `0` | Data coding scheme (`0` GSM-7, `8` Unicode). |
| `SMS_GATEWAYHUB_ENTITY_ID` | `1301160705981331943` | DLT entity ID (Indian traffic). |
| `SMS_GATEWAYHUB_DLT_TEMPLATE_ID` | — | DLT template ID (Indian traffic). |

Secrets are read only in `settings.py` and used only inside the provider. They
are never logged.

---

## Configuration by environment

| Environment | Recommended settings |
|---|---|
| **Local development** | `SMS_ENABLED=False` (or `True` with `SMS_MOCK=True`). No real SMS. |
| **Testing / CI** | Tests force mock/stub providers; no network. Nothing to configure. |
| **Production** | `SMS_ENABLED=True`, `SMS_MOCK=False`, real credentials + DLT fields. |

---

## Usage

### Send a raw message

```python
from notification.services import get_sms_service

result = get_sms_service().send_sms("9876543210", "Your order has shipped.")
if not result.success:
    # result.status is one of: sent / failed / invalid / disabled / mocked
    logger.warning("SMS not sent: %s", result.error)
```

### Send a templated message (recommended)

```python
from notification.services import get_sms_service

get_sms_service().send_template(
    "user.otp",
    phone_number="9876543210",
    context={"otp": "123456", "validity": "10"},
)
```

### `SmsResult` fields

`success`, `status`, `recipient`, `message_id`, `error`, `error_code`,
`provider`, `provider_response`. Callers should branch on `success`/`status`
and must not surface `provider_response` to end users.

---

## SMS templates (per module, editable)

Defaults live in `notification/templates_catalog.py`, grouped by application
module. Editable copies live in the **SMS templates** admin section.

Seed the database from the catalogue (idempotent; keeps admin edits):

```bash
python manage.py seed_sms_templates          # create missing only
python manage.py seed_sms_templates --force  # reset all to catalogue defaults
```

Shipped templates:

| Key | Module | Placeholders |
|---|---|---|
| `user.otp` | User | `otp`, `validity` |
| `user.password_reset` | User | `name`, `otp` |
| `user.registration_confirmation` | User | `name`, `username` |
| `broiler.vaccination_reminder` | Broiler | `batch`, `farm`, `vaccine`, `date` |
| `broiler.dispatch_notification` | Broiler | `quantity`, `batch`, `destination`, `date`, `vehicle` |
| `broiler.daily_report` | Broiler | `date`, `farm`, `mortality`, `feed`, `avg_weight` |
| `hatchery.hatch_reminder` | Hatchery | `batch`, `date` |
| `hr.payroll_processed` | HR | `name`, `month`, `amount` |
| `sales.payment_reminder` | Sales | `name`, `invoice`, `amount`, `due_date` |
| `sales.dispatch_notification` | Sales | `name`, `order`, `date`, `vehicle` |
| `purchase.order_confirmation` | Purchase | `po_number`, `amount`, `vendor`, `date` |
| `account.payment_reminder` | Account | `amount`, `reference`, `due_date` |
| `inventory.feed_stock_alert` | Inventory | `item`, `warehouse`, `quantity`, `unit`, `threshold` |

Resolution order: **active DB template → catalogue default**. Rendering fails
safely (`status="invalid"`) if a placeholder is missing.

---

## API flow

1. `send_sms(phone, message)`.
2. If `SMS_ENABLED` is false → `status="disabled"`, provider never called.
3. Normalise phone + validate message. On failure → `status="invalid"`
   (no provider call, never retried).
4. Provider builds the request and GETs `/api/mt/SendSMS` with query params.
5. Response mapped: `ErrorCode=000` → success (`message_id` extracted);
   transient codes / HTTP 429/5xx / timeout / network → `SmsTransientError`;
   everything else (bad number, auth) → `SmsPermanentError`.
6. Transient errors retried with exponential backoff up to `SMS_MAX_RETRIES`.
7. A structured `SmsResult` is always returned.

---

## Error handling

| Condition | Classification | Retried | Caller sees |
|---|---|---|---|
| SMS disabled | — | no | `status="disabled"` |
| Invalid phone / empty message | validation | no | `status="invalid"` |
| Timeout / network error | transient | yes | `status="failed"` after retries |
| HTTP 429 / 5xx | transient | yes | `status="failed"` after retries |
| Provider busy codes (`008`,`017`,`018`) | transient | yes | `status="failed"` after retries |
| HTTP 401/403, bad credentials | permanent | no | `status="failed"` |
| Invalid number / other provider errors | permanent | no | `status="failed"` |
| Missing API key/sender | configuration | no | `status="failed"` |
| Unexpected exception | contained | no | `status="failed"` |

An SMS failure can never crash a request or job.

---

## Logging & security

- Logger `notification.sms` (inherits the project's rotating file + console
  handlers from `settings.LOGGING`).
- Logged: masked recipient (last 4 digits), provider, status, provider error
  code, `message_id`, timestamp.
- **Never logged:** API keys, secrets, full phone numbers, message bodies.
- Provider payloads are retained on `SmsResult.provider_response` for
  diagnostics only and must not be shown to end users.

---

## Testing

```bash
python manage.py test notification
```

38 unit tests cover validation, provider response mapping (success/transient/
permanent/timeout/non-JSON), service gating/retry/containment, and template
rendering with DB overrides. No real SMS is sent: the provider HTTP session is
mocked and the mock provider is used elsewhere.

Manual smoke test in a configured environment:

```bash
python manage.py send_test_sms 9876543210 --message "Hello from BIMS"
```

---

## Deployment

1. `pip install -r requirements.txt` (adds `requests`).
2. `python manage.py migrate` (creates `notification_smstemplate`).
3. `python manage.py seed_sms_templates`.
4. Set the SMS env vars (see above); for production set `SMS_ENABLED=True`,
   `SMS_MOCK=False`, real credentials and DLT fields.
5. Verify with `send_test_sms`.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `status="disabled"` | `SMS_ENABLED` not true | Set `SMS_ENABLED=True`. |
| `message_id` starts `mock-` | Mock mode on | Set `SMS_MOCK=False`. |
| `status="invalid"` | Bad phone or missing placeholder | Check number / template context. |
| Repeated transient failures | Network / provider outage / rate limit | Check connectivity; retries already applied. |
| Permanent failure with HTTP 401 | Wrong API key/sender | Re-check credentials. |
| Delivery fails only in production (India) | DLT not configured | Set `SMS_GATEWAYHUB_ENTITY_ID` / `_DLT_TEMPLATE_ID` and register templates on DLT. |

> The SMSGatewayHub endpoint, success code (`000`) and transient error codes in
> `constants.py` reflect the provider's published contract. Confirm them against
> your account documentation before go-live.

---

## Adding another provider

1. Add `notification/providers/<name>.py` implementing `SmsProvider.send`.
2. Register it in `_PROVIDER_FACTORIES` in `services/sms_service.py`.
3. Set `SMS_PROVIDER=<name>` and its credentials.

No business/view/template code changes.
