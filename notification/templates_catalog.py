"""Per-module SMS template catalogue.

This is the source of truth for the templates shipped with the application and
the fallback used when no active database override exists. Each application
module that sends SMS owns a group of templates here; the editable copies live
in :class:`~notification.models.SmsTemplate` and are seeded from this catalogue
via ``manage.py seed_sms_templates``.

Placeholders use ``str.format`` syntax, e.g. ``{name}``.
"""

from dataclasses import dataclass

from .constants import SmsModule


@dataclass(frozen=True)
class TemplateDef:
    """A single named template belonging to an application module."""

    key: str
    module: str
    name: str
    body: str
    description: str = ""
    dlt_template_id: str = ""


DEFAULT_TEMPLATES = (
    # --- User / authentication ---
    TemplateDef(
        key="user.otp",
        module=SmsModule.USER,
        name="Login OTP",
        body=("Your Hi Tech Farms OTP is {otp}. It is valid for {validity} minutes. "
              "Do not share it with anyone."),
        description="One-time password for login or verification.",
    ),
    TemplateDef(
        key="user.password_reset",
        module=SmsModule.USER,
        name="Password reset OTP",
        body=("Hi {name}, use OTP {otp} to reset your Hi Tech Farms password. "
              "If this wasn't you, please ignore this message."),
        description="Password reset one-time password.",
    ),
    TemplateDef(
        key="user.registration_confirmation",
        module=SmsModule.USER,
        name="Registration confirmation",
        body="Welcome to Hi Tech Farms, {name}! Your account ({username}) is now active.",
        description="Sent after a user account is created.",
    ),
    # --- Broiler ---
    TemplateDef(
        key="broiler.vaccination_reminder",
        module=SmsModule.BROILER,
        name="Vaccination reminder",
        body=("Reminder: Batch {batch} at {farm} is due for {vaccine} vaccination on "
              "{date}. - Hi Tech Farms"),
        description="Upcoming vaccination reminder for a broiler batch.",
    ),
    TemplateDef(
        key="broiler.dispatch_notification",
        module=SmsModule.BROILER,
        name="Dispatch notification",
        # Wording must match the DLT-registered content template exactly.
        body=("Dear {name}, Date {date} Order for {quantity} Broiler Chicks "
              "(including free chicks) has been dispatched For Place {place} via "
              "{vehicle} Driver: {driver}. Delivery Challan No:{challan}.Please be "
              "ready for receipt. - Hitech Hatcheries/Farms"),
        description="Notification when a broiler chicks order is dispatched.",
        dlt_template_id="1707177597686267032",
    ),
    TemplateDef(
        key="broiler.daily_report",
        module=SmsModule.BROILER,
        name="Daily report",
        body=("Daily report {date} - {farm}: Mortality {mortality}, Feed {feed}kg, "
              "Avg wt {avg_weight}g. - Hi Tech Farms"),
        description="Daily operational summary for a farm.",
    ),
    # --- DLT-registered production templates (SenderId HTFARM) ---
    # Wording below must match the DLT registration character-for-character.
    TemplateDef(
        key="broiler.bird_receipt",
        module=SmsModule.BROILER,
        name="Broiler bird receipt",
        body=("Dear {name}, Amount Rcvd Rs {amount} Against Live Broiler Bird via "
              "{mode}. Receipt No {receipt_no} Date: {date} Regards - HiTech Farms"),
        description="Payment receipt for live broiler birds.",
        dlt_template_id="1707177225716847167",
    ),
    TemplateDef(
        key="broiler.bird_sale",
        module=SmsModule.BROILER,
        name="Broiler sale",
        body=("Dear {name}, Broiler Bird {quantity} No. Wt {weight} Kg's @Rs {rate} "
              "Invoice Value Rs {invoice_value} DC No. {dc_no} Vehicle {vehicle} "
              "Date: {date} Regards,-Hi Tech Farms"),
        description="Broiler bird sale invoice summary.",
        dlt_template_id="1707177216907464820",
    ),
    TemplateDef(
        key="broiler.chicks_payment",
        module=SmsModule.BROILER,
        name="Chicks payment & dues",
        body=("Dear {name}, Date: {date} Amount Rcvd Rs {amount} Against Broiler "
              "Chicks via {mode} Receipt No {receipt_no} Total Dues {total_dues}. "
              "Regards - HiTech Hatcheries & Farms"),
        description="Payment receipt and outstanding dues for broiler chicks.",
        dlt_template_id="1707177616363258793",
    ),
    TemplateDef(
        key="broiler.chicks_post_delivery",
        module=SmsModule.BROILER,
        name="Chicks post delivery alert",
        body=("Delivery Alert: {quantity}+2% Broiler Chicks delivered against DC No: "
              "{dc_no} via {vehicle}. Total Invoice Amount: Rs{amount} @{rate} Date "
              "{date}. For any Discrepancy, call 9415210080 - Hitech Hatcheries & Farms"),
        description="Post-delivery alert for a broiler chicks consignment.",
        dlt_template_id="1707177614778164686",
    ),
    # --- Hatchery ---
    TemplateDef(
        key="hatchery.hatch_reminder",
        module=SmsModule.HATCHERY,
        name="Hatch reminder",
        body="Reminder: Setter batch {batch} is scheduled to hatch on {date}. - Hi Tech Farms",
        description="Reminder for an upcoming hatch date.",
    ),
    # --- HR ---
    TemplateDef(
        key="hr.payroll_processed",
        module=SmsModule.HR,
        name="Payroll processed",
        body="Hi {name}, your salary for {month} ({amount}) has been processed. - Hi Tech Farms",
        description="Notification sent when payroll is processed for an employee.",
    ),
    # --- Sales ---
    TemplateDef(
        key="sales.payment_reminder",
        module=SmsModule.SALES,
        name="Payment reminder",
        body=("Dear {name}, invoice {invoice} for {amount} is due on {due_date}. "
              "Kindly arrange payment. - Hi Tech Farms"),
        description="Outstanding payment reminder for a customer.",
    ),
    TemplateDef(
        key="sales.dispatch_notification",
        module=SmsModule.SALES,
        name="Order dispatch notification",
        body=("Dear {name}, your order {order} was dispatched on {date}. "
              "Vehicle {vehicle}. - Hi Tech Farms"),
        description="Notification when a customer order is dispatched.",
    ),
    # --- Purchase ---
    TemplateDef(
        key="purchase.order_confirmation",
        module=SmsModule.PURCHASE,
        name="Purchase order confirmation",
        body="PO {po_number} for {amount} was raised to {vendor} on {date}. - Hi Tech Farms",
        description="Confirmation that a purchase order was created.",
    ),
    # --- Account ---
    TemplateDef(
        key="account.payment_reminder",
        module=SmsModule.ACCOUNT,
        name="Account payment reminder",
        body="Payment reminder: {amount} against {reference} is due on {due_date}. - Hi Tech Farms",
        description="Accounts payable/receivable payment reminder.",
    ),
    TemplateDef(
        key="account.payment_due_reminder",
        module=SmsModule.ACCOUNT,
        name="Payment due reminder",
        body=("Payment Reminder : Dear {name}, that amount of Rs {amount} is due as of "
              "today, towards invoices. Kindly Clear the total dues, thank you! - "
              "Hi Tech Farms"),
        description="DLT-registered outstanding payment reminder.",
        dlt_template_id="1707177657120893377",
    ),
    # --- Inventory ---
    TemplateDef(
        key="inventory.feed_stock_alert",
        module=SmsModule.INVENTORY,
        name="Feed stock alert",
        body=("Stock alert: {item} at {warehouse} is low ({quantity} {unit} left, "
              "below {threshold}). Please reorder. - Hi Tech Farms"),
        description="Low-stock alert for an inventory item.",
    ),
)

# Indexed for O(1) lookup by key.
DEFAULT_TEMPLATES_BY_KEY = {template.key: template for template in DEFAULT_TEMPLATES}
