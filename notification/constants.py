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

# Sub-transactions per module a template can be tagged to. Blank on a
# template means "generic — any transaction of the module". The SMS
# Transaction page uses these codes to offer only matching templates.
SMS_MODULE_TRANSACTIONS = {
    SmsModule.USER: (
        ("registration", "User Registration"),
        ("login_otp", "Login / OTP"),
    ),
    SmsModule.BROILER: (
        ("bird_receipt", "Bird Receipt"),
        ("broiler_sale", "Broiler Sale"),
        ("broiler_batch", "Broiler Batch"),
    ),
    SmsModule.HATCHERY: (
        ("egg_purchase", "Egg Purchase"),
        ("egg_grading", "Egg Grading"),
        ("tray_set", "Tray Set"),
        ("hatch_entry", "Hatch Entry"),
        ("hatch_register", "Hatch Register"),
        ("delivery_challan", "Delivery Challan"),
        ("chick_sale", "Chick Sale"),
    ),
    SmsModule.HR: (
        ("attendance", "Attendance"),
        ("leave", "Leave"),
        ("payroll", "Payroll"),
    ),
    SmsModule.SALES: (
        ("sale_invoice", "Sale Invoice"),
        ("payment_receipt", "Payment Receipt"),
        ("payment_reminder", "Payment Due Reminder"),
    ),
    SmsModule.PURCHASE: (
        ("purchase_order", "Purchase Order"),
        ("purchase_invoice", "Purchase Invoice"),
    ),
    SmsModule.ACCOUNT: (
        ("payment_receipt", "Payment Receipt"),
        ("payment_due", "Payment Due"),
    ),
    SmsModule.INVENTORY: (
        ("stock_transfer", "Stock Transfer"),
    ),
}


def transaction_label(module, code):
    """Human label for a module's transaction code ('' when blank/unknown)."""
    for value, label in SMS_MODULE_TRANSACTIONS.get(module, ()):
        if value == code:
            return label
    return ""

# SMSGatewayHub REST contract. Endpoint/success code reflect the provider's
# published "Send SMS" JSON API; verify against your account documentation
# before going live, as provider contracts can change.
GATEWAYHUB_SENDSMS_ENDPOINT = "/api/mt/SendSMS"
GATEWAYHUB_SUCCESS_CODE = "000"

# Provider error codes that represent transient conditions worth retrying
# (server busy / internal error / rate limited). Everything else is treated as
# permanent so invalid requests are never retried.
GATEWAYHUB_TRANSIENT_ERROR_CODES = frozenset({"008", "017", "018"})
