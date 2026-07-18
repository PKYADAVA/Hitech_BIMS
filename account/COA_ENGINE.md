# Chart of Accounts Engine

Template-driven COA generation for Hitech BIMS. Instead of a hand-typed flat
account list, every company's chart of accounts is **generated** from an
industry template during setup and stays fully editable afterwards.

## Architecture

```
account/
├── models.py            AccountType, AccountGroup, CoATemplate, CoATemplateAccount,
│                        ChartOfAccount (tree), CoAGenerationLog, AccountAuditLog, CostCenter
├── coa_seed.py          Seed data: 6 system types, 15 groups, base tree + 11 industry overlays
├── services/
│   ├── code_generator.py   AccountCodeGenerator - automatic hierarchical codes
│   ├── coa_generator.py    CoAGeneratorService - template → company COA pipeline
│   └── auto_ledger.py      sync_ledger - sub-ledger creation for master records
├── signals.py           post_save receivers (Customer/Supplier/Employee/BankCode/Warehouse)
├── api_views.py         REST endpoints under /api/chart-of-accounts/
├── templates/coa.html   Tree explorer UI + generation wizard
└── management/commands/seed_coa_templates.py
```

### Data model

* **AccountType** – fixed system table (Asset, Liability, Equity, Income,
  Cost Of Goods Sold, Expense). Cannot be deleted or renamed (model +
  admin enforcement). Each type owns a numeric code range used by the code
  generator (Asset 100000–199999, Liability 200000–299999, …).
* **AccountGroup** – configurable classification (Current Assets, Tax,
  Manufacturing Expense, …). Users can add more.
* **CoATemplate / CoATemplateAccount** – the master hierarchy per
  industry+country. Seeded templates: General, Trading, Manufacturing,
  Retail, Distribution, Poultry, Hatchery, Agriculture, Service, Hospital,
  Construction (all `India … Standard`, country `IN`, currency `INR`).
* **ChartOfAccount** – the per-company tree. Materialized `path`
  (`100000/110000/111000`) + `level` + `(company, code)` unique constraint +
  composite indexes make subtree queries cheap without recursive CTEs; the
  full tree endpoint builds the hierarchy from one query.
  * `is_group` / `is_postable`: groups can never be posted to (enforced in
    `clean()`/`save()`); only postable leaves accept journal lines.
  * `system_role` anchors (`ACCOUNTS_RECEIVABLE`, `GST_PAYABLE`, …) let
    services find accounts without hard-coding codes.
  * Soft delete (`deleted_at/by`): the default manager hides deleted rows,
    `all_objects` sees everything. Nothing is permanently removed.
  * Legacy compatibility: the old flat fields (`type`, `status`, `schedule`,
    `control_type`) are kept and synced, so existing hatchery/broiler FKs and
    `status='Active'` filters keep working unchanged.
* **CompanyProfile** – now multi-company capable: the first company keeps
  pk=1 (what `get_solo()` and legacy single-company code use); additional
  companies get their own COA, isolated by the `company` FK on every engine
  table. All APIs accept `?company=<id>` and default to company 1.

### Generation pipeline (`CoAGeneratorService.generate()`)

Runs inside **one transaction** (full rollback on failure) and writes a
`CoAGenerationLog` row either way:

1. copy template hierarchy (level order, parents first)
2. ensure anchor groups exist
3. tax accounts by template country (`IN`: Input/Output CGST/SGST/IGST, GST
   Receivable/Payable, TDS, TCS, Round Off)
4. inventory accounts (Raw Material … Broiler/Egg/Chick Inventory,
   Adjustment/Gain/Loss/Stock Difference)
5. cash accounts (Cash In Hand, Petty Cash)
6. bank ledgers – one per `BankCode` row
7. fixed assets – Cost + Accumulated Depreciation + Depreciation Expense per
   class (Land gets cost only)
8. equity accounts (Capital, Retained Earnings, Opening Balance Equity, P&L)

The run is **idempotent**: accounts are matched by `system_role`, then code;
re-running only adds what is missing (`skipped` counters in the log summary).

### Automatic account codes

`AccountCodeGenerator` – users never type codes:

```
100000 Assets            root  = type range start
110000  Current Assets   level-1 group step 10 000
111000   Cash            level-2 group step 1 000
111001    Cash In Hand   leaf step 1
```

Duplicates are prevented by the in-service free-slot scan plus the
`uniq_coa_company_code` DB constraint (concurrent inserts fail loudly).

### Automatic ledgers

`post_save` signals create postable sub-ledgers under the right control group
and link them back to the source row via a generic FK (renames propagate, no
duplicates):

| Master             | Ledger under                     |
|--------------------|----------------------------------|
| sales.Customer     | Accounts Receivable              |
| purchase.Supplier  | Accounts Payable                 |
| account.BankCode   | Bank Accounts                    |
| hr.Employee        | Salary Payable + Employee Advances |
| inventory.Warehouse| Inventory                        |

Ledger sync never raises – if the COA isn't generated yet it's a silent no-op.

## REST API

All endpoints require login and are guarded by the Web-Access matrix under the
**Chart of Accounts** tab (`user/access.py`). Mutations are audit-logged with
user + IP.

| Endpoint | Method | Notes |
|---|---|---|
| `/api/chart-of-accounts/` | GET | paginated (`page`, `page_size`≤200), filters: `q`, `type`, `status`, `account_type`, `group`, `parent`, `system_role`, `postable`, `company` |
| `/api/chart-of-accounts/` | POST | create; code auto-generated |
| `/api/chart-of-accounts/<id>/` | GET/PUT/DELETE | DELETE = soft delete; locked/system accounts protected |
| `/api/chart-of-accounts/tree/` | GET | nested tree; `?parent=<id>` for lazy children |
| `/api/chart-of-accounts/search/?q=` | GET | top-50 flat matches |
| `/api/chart-of-accounts/templates/` | GET | active templates + account counts |
| `/api/chart-of-accounts/generate/` | POST | `{template, with_tax, with_inventory, with_cash, with_banks, with_fixed_assets}` |
| `/api/chart-of-accounts/import/` | POST | CSV/XLSX; `?dry_run=1` validates only; real run is all-or-nothing |
| `/api/chart-of-accounts/export/` | GET | `?format=csv|xlsx` |
| `/api/chart-of-accounts/opening-balance/` | GET/POST | bulk set; difference auto-posts to Opening Balance Equity |
| `/api/chart-of-accounts/audit/` | GET | paginated audit trail (`?account=<id>`) |

These endpoints are self-describing (types, posting flags, hierarchy paths,
balances in every payload), so an AI agent can reason about the account
hierarchy and posting rules without database access.

## Setup / deployment

```bash
python manage.py migrate                 # schema + seeds types/groups, backfills legacy accounts
python manage.py seed_coa_templates      # 11 industry templates (idempotent; --rebuild to refresh)
```

Company setup flow: create/complete **Company Profile** → open **Account ▸
Chart of Accounts** → **Generate CoA** → pick industry template + options →
Generate → enter **Opening Balances**. Master records (customers, suppliers,
banks, employees, warehouses) created afterwards get ledgers automatically.

Existing accounts are untouched: the backfill migration assigns them to
company 1 as level-0 postable leaves; they can be re-parented into the
generated tree from the UI.

## Testing

`python manage.py test account` – 16 tests cover: system-type protection,
hierarchical code generation and duplicate prevention, template generation
(incl. Poultry overlay + GST + fixed assets), idempotency, transaction
rollback with a Failed log row, posting rules, auto-ledger create/rename/
no-crash-without-COA, and the API surface (generate/tree/CRUD/soft-delete/
audit/system-protection/opening-balance rebalancing/import validation).

Strategy for future changes: every new generator step needs (a) an
idempotency assertion, (b) a rollback assertion, (c) an anchor-role lookup
test. UI changes are covered by driving the JSON endpoints the page uses.

## Journal Engine

`account/services/journal.py` + `account/journal_api.py` + the **Journal
Vouchers** tab (Account ▸ Transactions). All posting goes through this service.

* **Voucher / VoucherLine** – header + debit/credit legs; `date` is
  denormalized onto lines so ledger/trial-balance queries never join the
  header at scale. Lifecycle: Draft (editable/deletable) → Posted (immutable,
  voucher number assigned: `JV/2026-27/0001`, sequential per company + FY +
  type) → Cancelled (kept forever with reason; excluded from balances).
* **Posting rules**: debits = credits > 0; lines only on postable, active
  leaf accounts of the voucher's company; `allow_manual_entry` enforced for
  manual entry; voucher date must fall in an **Open** financial year (state is
  re-read from the DB at post/cancel time); Locked years block cancelling too.
* **Opening voucher sync**: saving Opening Balances rebuilds a single
  system-generated `OPV` voucher dated at the active FY start, so ledgers and
  the trial balance include openings without double counting.
* **Reports**: per-account ledger with running Dr/Cr balance
  (`/api/chart-of-accounts/<id>/ledger/?from&to`, deep-linked from the tree's
  book icon) and Trial Balance with opening/period/closing columns
  (`/api/reports/trial-balance/?from&to`) — both computed purely from Posted
  voucher lines.
* **Voucher APIs**: `/api/vouchers/` (list/create, `{"post": true}` to post
  immediately), `/api/vouchers/<id>/` (detail/update-draft/delete-draft),
  `/<id>/post/`, `/<id>/cancel/`. Guarded by the "Journal Vouchers" tab in the
  Web-Access matrix.
* Other modules (sales/purchase/hatchery) should call
  `journal.create_voucher(..., manual=False, post=True)` to post documents.

## Automatic document posting

`account/services/auto_posting.py` — hatchery documents post vouchers
automatically through the journal service (called from the hatchery views
after save; `post_delete` signals cancel on delete):

* **EggPurchase → Purchase voucher**: Dr Egg Purchases (gross) + freight
  account + TCS Receivable; Cr supplier AP ledger (*pay_later*) or pay
  account (*pay_in_bill*); `freight_type='Exclude'` credits the pay account
  separately for freight. **ChickSale → Sales voucher**: Dr customer AR
  ledger / pay account (final amount); Cr Chick Sales + freight recovery
  when billed.
* One Posted voucher per document (generic FK `Voucher.source`). Edits with
  changed amounts cancel + re-post; unchanged saves are no-ops; document
  delete cancels the voucher. `sector` = the document's warehouse.
* Role accounts (`EGG_PURCHASES`, `CHICK_SALES`, `FREIGHT_INWARD`,
  `FREIGHT_RECOVERED`, `TCS_RECEIVABLE`) are created on demand under their
  anchors, so this works with any generated template.
* Posting failures never block the document save — they're logged; run
  `python manage.py repost_documents` (add `--all` to re-check documents
  that already have vouchers) to backfill.

## Profit & Loss / Balance Sheet

`journal.profit_and_loss(company, date_from=None, date_to=None)` and
`journal.balance_sheet(company, date_upto=None)` group the same posted
voucher lines as Trial Balance, by `AccountType.report` (`PL`/`BS`) and
`normal_balance`, into per-account amounts signed positive on the normal
side. Pages: Account ▸ Reports ▸ **Profit & Loss** / **Balance Sheet**
(`/reports/profit-loss/`, `/reports/balance-sheet/`), APIs at
`/api/reports/profit-loss/` and `/api/reports/balance-sheet/`.

* P&L is period-scoped (`date_from`/`date_to`); with no `date_from` it's
  cumulative since inception — there's no year-end closing yet to zero P&L
  accounts between years, so a prior year's income/expense still shows
  unless a date range excludes it.
* Balance Sheet is always "as of" a single date (`date_upto`), cumulative
  since inception. The current period's unclosed profit is folded into
  Equity as a computed **Current Earnings** line
  (`profit_and_loss(date_to=date_upto)['net_profit']`), which makes
  `Assets == Liabilities + Equity` hold exactly by double-entry construction
  (proven in `FinancialReportsTests.test_balance_sheet_always_balances`) -
  the API also returns a `balanced` boolean the UI displays as a check.

## Roadmap (not yet implemented)

* **Year-end closing** – close a year by generating next-year opening entries
  from closing balances (Voucher type `Closing` is reserved for this); once
  built, P&L becomes truly period-scoped instead of cumulative-since-inception.
* **Cash Flow statement**, comparatives (multi-period P&L/BS side by side).
* **Bank reconciliation**, **budgets**, **cost-center reporting**
  (`cost_center` is already accepted on voucher lines via API).
* **More document types** – purchase invoices/GRNs and sales invoices post
  nothing yet because those models don't exist (POs are commitments, not
  accounting events); when built, add a builder to `auto_posting.BUILDERS`.
* **Tree UI extras** – drag-drop move/merge; move works via `PUT {parent: …}`.
* **Per-company scoping of master records** – customers/suppliers/etc. have no
  company FK yet; auto-ledgers default to company 1 until they do.
