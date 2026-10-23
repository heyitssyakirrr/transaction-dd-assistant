"""The four columns this app uses. Their names in the bank's file are set here, and only here.

Every other column in the file (account number, transaction code, channel, teller, customer details)
is ignored when the file is read: it is never stored, shown or sent to the AI.
If the bank renames a column, change the right-hand side below. Names are matched without regard to case.
"""
from __future__ import annotations

# our name -> column name in the bank's file
COLUMNS: dict[str, str] = {
    "date": "TXN_DATE",                 # DD/MM/YYYY or YYYY-MM-DD, with or without a time
    "seq": "TRANSACTION_SEQ_NO",        # order of the transactions within one day (1 = first)
    "direction": "CREDIT_DEBIT_CODE",   # C = money in, D = money out
    "amount": "AMOUNT",                 # RM, always positive; the direction says in or out
}
