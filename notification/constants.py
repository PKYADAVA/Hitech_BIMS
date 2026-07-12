"""Provider-agnostic constants for the SMS notification subsystem."""


class SmsStatus:
    """Outcome states returned to callers via :class:`~notification.dtos.SmsResult`."""

    SENT = "sent"
    FAILED = "failed"
    INVALID = "invalid"
    DISABLED = "disabled"
    MOCKED = "mocked"


class SmsProviderName:
    """Identifiers used to select a provider implementation from settings."""

    SMSGATEWAYHUB = "smsgatewayhub"
    MOCK = "mock"


# Application modules that own SMS templates. Kept here so the template
# catalogue, admin filters and seeding command share a single source of truth.
class SmsModule:
    USER = "user"
    BROILER = "broiler"
    HATCHERY = "hatchery"
    HR = "hr"
    SALES = "sales"
    PURCHASE = "purchase"
    ACCOUNT = "account"
    INVENTORY = "inventory"


SMS_MODULE_CHOICES = (
    (SmsModule.USER, "User"),
    (SmsModule.BROILER, "Broiler"),
    (SmsModule.HATCHERY, "Hatchery"),
    (SmsModule.HR, "HR"),
    (SmsModule.SALES, "Sales"),
    (SmsModule.PURCHASE, "Purchase"),
    (SmsModule.ACCOUNT, "Account"),
    (SmsModule.INVENTORY, "Inventory"),
)

# SMSGatewayHub REST contract. Endpoint/success code reflect the provider's
# published "Send SMS" JSON API; verify against your account documentation
# before going live, as provider contracts can change.
GATEWAYHUB_SENDSMS_ENDPOINT = "/api/mt/SendSMS"
GATEWAYHUB_SUCCESS_CODE = "000"

# Provider error codes that represent transient conditions worth retrying
# (server busy / internal error / rate limited). Everything else is treated as
# permanent so invalid requests are never retried.
GATEWAYHUB_TRANSIENT_ERROR_CODES = frozenset({"008", "017", "018"})
