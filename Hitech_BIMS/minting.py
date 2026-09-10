"""Minting a number that has to be unique, when two people save at once.

Every document number in this ERP is issued the same way: read the highest one
already used, add one, write the row. Between the reading and the writing there
is a gap, and two saves that land in it read the same highest and take the same
number.

Until now nothing said so. Some of these columns had a unique index and the
second save failed with a 500; others had none and quietly filed a second
record wearing the first one's number, which is worse — it looks like data
rather than like an error.

The gap cannot be closed by looking harder before writing; whatever is read can
go stale before the insert. It is closed by letting the database be the
arbiter: attempt the write, and if the number was taken in the meantime, mint
another and attempt again. The loser of a race waits a few milliseconds and
gets the next number, which is what would have happened had the two saves
arrived in sequence.

Used with a savepoint, so this works inside a view that is already in a
transaction — a failed attempt rolls back to the savepoint rather than
poisoning everything around it.
"""
import logging

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

#: Postgres SQLSTATE for a unique-constraint violation.
_UNIQUE_VIOLATION = "23505"


def is_unique_violation(error):
    """Whether an IntegrityError is a duplicate key rather than, say, a null
    in a column that forbids one.

    Retrying anything else would be pointless at best: a missing foreign key
    is not going to resolve itself on the second attempt.
    """
    sqlstate = getattr(getattr(error, "__cause__", None), "sqlstate", None)
    if sqlstate:
        return sqlstate == _UNIQUE_VIOLATION
    # No driver detail to read (SQLite in a test, say) — fall back to the text.
    return "unique" in str(error).lower()


def mint_with_retry(write, remint, *, attempts=5, label="number"):
    """Run ``write``; if the number it carried was taken, ``remint`` and retry.

    ``write`` performs the save. ``remint`` issues a fresh number onto the
    instance and is called only between attempts, never before the first —
    the common case must cost nothing but the savepoint.

    Gives up after ``attempts`` and lets the error through. Five is generous:
    each retry re-reads the maximum, so it only takes another loop if yet
    another save lands in the same instant, and a system with that much
    contention on one counter has a different problem.
    """
    for attempt in range(attempts):
        try:
            with transaction.atomic():
                return write()
        except IntegrityError as error:
            if attempt == attempts - 1 or not is_unique_violation(error):
                raise
            logger.info("minting: %s was taken, issuing another (attempt %d)",
                        label, attempt + 2)
            remint()
