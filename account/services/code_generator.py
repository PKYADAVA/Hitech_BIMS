"""Automatic account code generation.

Codes are hierarchical six-digit numbers allocated from the owning account
type's range (Asset 100000-199999, Liability 200000-299999, ...):

    100000 Assets                 (root  - range start)
    110000   Current Assets       (level 1 group - step 10,000)
    111000     Cash               (level 2 group - step 1,000)
    111001       Cash In Hand     (postable leaf - step 1)

Users never type codes; every create path calls :class:`AccountCodeGenerator`.
Uniqueness is enforced per company both here and by the database constraint
``uniq_coa_company_code``, so a concurrent duplicate insert fails cleanly
instead of silently colliding.
"""
import re

from account.models import ChartOfAccount

# Step for a *group* child, keyed by the child's tree level.
GROUP_LEVEL_STEP = {0: 100000, 1: 10000, 2: 1000, 3: 100, 4: 10}
NUMERIC_CODE_RE = re.compile(r"^\d+$")


class CodeRangeExhausted(Exception):
    """No free code remains in the relevant range."""


class AccountCodeGenerator:
    def __init__(self, company):
        self.company = company

    # ------------------------------------------------------------------ API

    def next_code(self, parent=None, account_type=None, is_group=False):
        """Return the next free code for a new account.

        Roots are allocated from the account type's range; group children step
        by a decreasing power of ten per level; postable leaves increment by 1
        after the last sibling.
        """
        if parent is None:
            if account_type is None:
                raise ValueError("account_type is required for root accounts")
            return self._next_root_code(account_type)
        if is_group:
            return self._next_child_code(parent, GROUP_LEVEL_STEP.get(parent.level + 1, 1))
        return self._next_child_code(parent, 1)

    # ------------------------------------------------------------- internals

    def _existing_codes(self):
        return set(
            ChartOfAccount.all_objects.filter(company=self.company)
            .values_list("code", flat=True)
        )

    def _next_root_code(self, account_type):
        start, end = account_type.code_range_start, account_type.code_range_end
        existing = self._numeric_codes_between(start, end, level=0)
        candidate = max(existing) + GROUP_LEVEL_STEP[1] if existing else start
        return self._first_free(candidate, GROUP_LEVEL_STEP[1], end)

    def _next_child_code(self, parent, step):
        parent_code = int(parent.code) if NUMERIC_CODE_RE.match(parent.code) else None
        if parent_code is None:
            # Non-numeric legacy parent: fall back to a plain suffix sequence.
            return self._next_suffix_code(parent)
        span = self._parent_span(parent)
        end = parent_code + span - 1
        siblings = [
            int(c) for c in ChartOfAccount.all_objects.filter(
                company=self.company, parent=parent
            ).values_list("code", flat=True)
            if NUMERIC_CODE_RE.match(c)
        ]
        candidate = (max(siblings) + step) if siblings else (parent_code + step)
        return self._first_free(candidate, step, end)

    def _parent_span(self, parent):
        """How many codes the parent's subtree owns (its own step width)."""
        return GROUP_LEVEL_STEP.get(parent.level, 10) if parent.level > 0 else 100000

    def _numeric_codes_between(self, start, end, level=None):
        qs = ChartOfAccount.all_objects.filter(company=self.company)
        if level is not None:
            qs = qs.filter(level=level)
        return [
            int(c) for c in qs.values_list("code", flat=True)
            if NUMERIC_CODE_RE.match(c) and start <= int(c) <= end
        ]

    def _first_free(self, candidate, step, end):
        existing = self._existing_codes()
        while candidate <= end:
            code = str(candidate)
            if code not in existing:
                return code
            candidate += step
        raise CodeRangeExhausted(f"No free account code before {end}")

    def _next_suffix_code(self, parent):
        existing = self._existing_codes()
        seq = 1
        while f"{parent.code}-{seq:03d}" in existing:
            seq += 1
        return f"{parent.code}-{seq:03d}"
