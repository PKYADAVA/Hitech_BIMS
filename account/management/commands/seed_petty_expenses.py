"""Sample petty expenses, for a register that has something in it.

Demonstration data, not fixtures: it is written through the same service the
screens use, so what it produces is exactly what a user would produce -- real
vouchers, real ledger movement, real cost-centre tags. Nothing is inserted
behind the engine's back.

Everything it writes is marked (a SMP- reference and a "sample" tag), and
``--undo`` removes precisely that and nothing else.

    python manage.py seed_petty_expenses          # write the sample set
    python manage.py seed_petty_expenses --undo   # take it away again
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from account.models import (BankCashMaster, ChartOfAccount, PaymentMode,
                            PettyExpense, Voucher)
from account.services import journal
from account.services import petty_expense as service
from account.services.bank_cash import ledger_for_bank_cash
from broiler.models import Branch, BroilerFarm, BroilerFarmShed

TAG = "sample"
FUNDING_REFERENCE = "SMP-FUND"

# days ago, sub-category code, [(what, qty, rate)], paid to, mode, cash?, farm, shed, extras
ROWS = [
    (42, "640005", [("Charcoal for brooding", 12, 420)],
     "Ram Fuel Depot", "Cash", True, 0, 0, {}),
    (38, "640002", [("Paddy husk for litter", 30, 180)],
     "Sharma Traders", "Cash", True, 0, 1, {"other_charges": 120}),
    (35, "640004", [("Loading labour at placement", 6, 450)],
     "Mukesh & team", "Cash", True, 0, None, {}),
    (30, "640001", [("Ice packs for the vaccine carrier", 4, 90),
                    ("Disposable syringes", 1, 500)],
     "Anand Medicals", "Cash", True, 0, 0, {}),
    (27, "670003", [("Diesel for the generator", 25, 94)],
     "HP Petrol Pump", "Cash", True, 1, None, {}),
    (21, "610003", [("Tea and refreshments, auditor visit", 1, 640)],
     "Gupta Tea Stall", "Cash", True, None, None, {}),
    (18, "610007", [("Brooder hover repair", 1, 1250)],
     "Irfan Welding Works", "Cash", True, 0, 0, {}),
    (12, "610004", [("Daily entry registers", 10, 65)],
     "Bahraich Stationers", "Cash", True, None, None, {"adjustment": 50}),
    (9, "670001", [("Farm electricity bill, August", 1, 3480)],
     "UPPCL", "Bank Transfer", False, 1, None, {}),
    (6, "610005", [("Broadband, September", 1, 1180)],
     "Airtel", "UPI", False, None, None, {}),
    (3, "670002", [("Water tanker", 2, 700)],
     "Singh Water Supply", "Cash", True, 0, None, {}),
    (2, "630001", [("Cheque book and quarterly charges", 1, 236)],
     "HDFC Bank", "Bank Transfer", False, None, None, {}),
]

# Entered, not yet posted -- what a register looks like on a working morning.
DRAFTS = [
    (1, "640004", [("Shed cleaning, three workers", 3, 500)],
     "Ramesh Kumar", "Cash", True, 0, 1, {}),
    (0, "670003", [("Diesel for the pickup", 15, 95)],
     "HP Petrol Pump", "Cash", True, 1, None, {}),
    (0, "610003", [("Sanitiser and gloves", 1, 880)],
     "Bahraich Medicals", "Cash", True, None, None, {}),
]

# Posted, then reversed -- the third state the register has to be able to show.
CANCELLED = (15, "640002", [("Wood shavings", 20, 210)],
             "Sharma Traders", "Cash", True, 0, None, {})


class Command(BaseCommand):
    help = "Write (or remove) a set of sample petty expenses for the register."

    def add_arguments(self, parser):
        parser.add_argument("--undo", action="store_true",
                            help="Delete the sample expenses and the vouchers they raised.")
        parser.add_argument("--fund", type=int, default=60000, metavar="RUPEES",
                            help="Cash drawn from the bank into the petty cash box "
                                 "before the expenses are posted (default 60000).")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        if options["undo"]:
            return self.undo()
        return self.seed(options["fund"])

    # ------------------------------------------------------------------
    @transaction.atomic
    def seed(self, fund):
        if PettyExpense.objects.filter(tags__icontains=TAG).exists():
            raise CommandError(
                "Sample expenses are already here. Run --undo first if you want them rewritten.")

        company = service.company()
        today = datetime.date.today()

        cash = BankCashMaster.objects.filter(is_cash=True).order_by("code").first()
        bank = BankCashMaster.objects.filter(is_cash=False).order_by("code").first()
        if cash is None:
            raise CommandError("No cash account in the Bank/Cash Master to spend from.")

        branch = (Branch.objects.filter(broiler_farms__isnull=False).distinct().first()
                  or Branch.objects.first())
        if branch is None:
            raise CommandError("No branch to charge the expenses to.")
        farms = list(BroilerFarm.objects.filter(branch=branch).order_by("id")[:2])
        sheds = {f.pk: list(BroilerFarmShed.objects.filter(farm=f).order_by("unit_no")[:2])
                 for f in farms}
        centre = getattr(branch, "organization_centre", None)

        # The box has to have money in it before anything can come out: cash
        # drawn from the bank, as a contra, which is how it happens in life.
        funding = None
        if fund > 0 and bank is not None:
            cash_ledger, bank_ledger = ledger_for_bank_cash(cash), ledger_for_bank_cash(bank)
            if cash_ledger is None or bank_ledger is None:
                raise CommandError("Bank/Cash accounts have no ledgers in the chart of accounts.")
            funding = journal.create_voucher(
                company, today - datetime.timedelta(days=45),
                # No cost centre on a contra: moving money between two of your
                # own accounts is not a cost, and tagging it would inflate the
                # centre's debit by the whole float.
                [{"account": cash_ledger.pk,
                  "debit": fund, "credit": 0, "narration": "Cash drawn for petty expenses"},
                 {"account": bank_ledger.pk, "debit": 0, "credit": fund,
                  "narration": "Cash drawn for petty expenses"}],
                voucher_type="Contra", manual=False, system_generated=True,
                reference=FUNDING_REFERENCE,
                narration=f"Sample data: {fund:,} drawn from {bank} into {cash} "
                          f"so the petty cash box has something to spend.",
                post=True)
            self.stdout.write(f"Funded {cash} with {fund:,} ({funding.voucher_no}).")

        made = {"posted": 0, "draft": 0, "cancelled": 0}
        for row in ROWS:
            expense = self._write(company, branch, farms, sheds, centre, cash, bank, today, row)
            service.post(expense, user=None)
            made["posted"] += 1

        for row in DRAFTS:
            self._write(company, branch, farms, sheds, centre, cash, bank, today, row)
            made["draft"] += 1

        expense = self._write(company, branch, farms, sheds, centre, cash, bank, today, CANCELLED)
        service.post(expense, user=None)
        service.cancel(expense, user=None, reason="Goods returned to the supplier")
        made["cancelled"] += 1

        balance = service.balance_of(cash)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {made['posted']} posted, {made['draft']} draft and "
            f"{made['cancelled']} cancelled petty expenses. "
            f"{cash} now holds {balance:,.2f}."))
        self.stdout.write("Remove it all again with: manage.py seed_petty_expenses --undo")

    # ------------------------------------------------------------------
    def _write(self, company, branch, farms, sheds, centre, cash, bank, today, row):
        days, code, lines, payee, mode_name, from_cash, farm_i, shed_i, extras = row

        account = ChartOfAccount.objects.filter(company=company, code=code).first()
        if account is None:
            raise CommandError(f"No account {code} in the chart of accounts; "
                               f"generate the Poultry chart first.")
        mode = (PaymentMode.objects.filter(name=mode_name).first()
                or PaymentMode.objects.filter(is_active=True).first())
        farm = farms[farm_i] if farm_i is not None and farm_i < len(farms) else None
        shed = None
        if farm is not None and shed_i is not None:
            on_farm = sheds.get(farm.pk) or []
            shed = on_farm[shed_i] if shed_i < len(on_farm) else None

        expense = PettyExpense.objects.create(
            company=company,
            expense_date=today - datetime.timedelta(days=days),
            branch=branch, farm=farm, shed=shed, cost_centre=centre,
            paid_to_name=payee, payment_mode=mode,
            paid_from=cash if from_cash or bank is None else bank,
            reference=f"SMP-{code}-{days:02d}",
            other_charges=Decimal(str(extras.get("other_charges", 0))),
            adjustment=Decimal(str(extras.get("adjustment", 0))),
            tags=f"{TAG}, {'farm' if farm else 'branch'}",
        )
        for index, (what, qty, rate) in enumerate(lines, start=1):
            expense.items.create(line_no=index, account=account, description=what,
                                 quantity=Decimal(str(qty)), rate=Decimal(str(rate)))
        expense.recalculate()
        expense.narration = service.compose_narration(expense)
        expense.save()
        return expense

    # ------------------------------------------------------------------
    @transaction.atomic
    def undo(self):
        expenses = PettyExpense.objects.filter(tags__icontains=TAG)
        if not expenses.exists():
            self.stdout.write("No sample expenses on file; nothing to undo.")
            return

        # The vouchers go with them. Deleting rather than cancelling, because
        # this is demonstration data being withdrawn, not a real payment being
        # reversed -- a cancelled voucher would stay in the journal for ever.
        vouchers = list(Voucher.objects.filter(
            id__in=[e.journal_id for e in expenses if e.journal_id]))
        count = expenses.count()
        expenses.delete()
        for voucher in vouchers:
            voucher.delete()

        funding = Voucher.objects.filter(reference=FUNDING_REFERENCE)
        funded = funding.count()
        funding.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Removed {count} sample expenses, {len(vouchers)} vouchers "
            f"and {funded} funding voucher(s)."))
