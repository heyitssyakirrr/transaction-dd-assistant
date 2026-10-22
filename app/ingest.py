"""Read one account's transactions from a CSV, TSV or Parquet file.

Only the four columns in app/columns.py are read. Every row is checked, blank lines are skipped, the
rows are sorted by date then sequence number, and each gets a short label (T1, T2, ...) that the AI
uses to point at it. Reading only: nothing here judges the transactions.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from app.columns import COLUMNS

# Day first (DD/MM/YYYY), as the bank's extract writes dates; ISO dates are accepted too.
_DATE_FORMATS = (
    "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M",
    "%d-%m-%Y", "%d-%m-%Y %H:%M:%S",
)
_CENT = Decimal("0.01")


class FileError(ValueError):
    """The file cannot be reviewed as it is. The message says why, in plain words."""


@dataclass(frozen=True)
class Txn:
    tid: str            # T1, T2, ...: what the AI cites
    when: datetime      # midnight when the file has dates only
    seq: int            # order within the day
    direction: str      # 'C' money in, 'D' money out
    amount: Decimal

    @property
    def day(self) -> date:
        return self.when.date()

    @property
    def month(self) -> str:
        return self.when.strftime("%Y-%m")


@dataclass
class Account:
    """One account's transactions, in time order."""
    file_name: str
    txns: list[Txn]
    has_time: bool = False          # True when TXN_DATE carries a time of day
    blank_lines_skipped: int = 0
    by_tid: dict[str, Txn] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.by_tid = {txn.tid: txn for txn in self.txns}

    @property
    def first_day(self) -> date:
        return self.txns[0].day

    @property
    def last_day(self) -> date:
        return self.txns[-1].day

    def date_text(self, txn: Txn) -> str:
        """The date as the AI and the report show it: with the time only when the file has times."""
        return txn.when.strftime("%Y-%m-%d %H:%M:%S" if self.has_time else "%Y-%m-%d")


def read_file(path: Path | str) -> Account:
    path = Path(path)
    return read_bytes(path.read_bytes(), path.name)


def read_bytes(data: bytes, file_name: str) -> Account:
    if file_name.lower().endswith(".parquet"):
        import pyarrow.parquet as pq  # only needed for Parquet files
        try:
            records: Iterable[dict[str, Any]] = pq.read_table(io.BytesIO(data)).to_pylist()
        except Exception as exc:  # pyarrow raises several error types for a damaged file
            raise FileError(f"The Parquet file could not be read: {exc}") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
        records = csv.DictReader(io.StringIO(text), delimiter=_separator(text))
    return build_account(records, file_name)


def build_account(records: Iterable[dict[str, Any]], file_name: str) -> Account:
    rows, blank, missing = [], 0, None
    for line, record in enumerate(records, start=2):  # line 1 is the header
        row = _four_columns(record)
        if missing is None:
            missing = [COLUMNS[name] for name in COLUMNS if name not in row]
            if missing:
                raise FileError(f"The file is missing column(s): {', '.join(missing)}.")
        if all(_text(value) == "" for value in row.values()):
            blank += 1
            continue
        rows.append(_parse(line, row))
    if not rows:
        raise FileError("The file has no transactions.")
    rows.sort(key=lambda r: (r["when"], r["seq"]))
    txns = [Txn(tid=f"T{number}", **row) for number, row in enumerate(rows, start=1)]
    return Account(file_name=file_name, txns=txns, blank_lines_skipped=blank,
                   has_time=any(t.when.time() != datetime.min.time() for t in txns))


def _separator(text: str) -> str:
    header = text.split("\n", 1)[0]
    return "\t" if "\t" in header else ";" if ";" in header and "," not in header else ","


def _four_columns(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only the four columns; every other column is dropped here."""
    by_name = {str(key).strip().upper(): value for key, value in record.items() if key is not None}
    return {ours: by_name[theirs.upper()] for ours, theirs in COLUMNS.items() if theirs.upper() in by_name}


def _parse(line: int, row: dict[str, Any]) -> dict[str, Any]:
    direction = _text(row["direction"]).upper()
    if direction not in {"C", "D"}:
        raise FileError(f"Row {line}: CREDIT_DEBIT_CODE must be C or D, not '{direction}'.")
    raw_amount = _text(row["amount"]).replace(",", "").upper().removeprefix("RM").strip()
    try:
        amount = Decimal(raw_amount).quantize(_CENT)
    except InvalidOperation:
        raise FileError(f"Row {line}: AMOUNT '{_text(row['amount'])}' is not a number.") from None
    if amount < 0:
        raise FileError(f"Row {line}: AMOUNT must not be negative; CREDIT_DEBIT_CODE gives the direction.")
    seq = _text(row["seq"]).removesuffix(".0")
    if not seq.isdigit():
        raise FileError(f"Row {line}: TRANSACTION_SEQ_NO '{seq}' is not a whole number.")
    return {"when": _datetime(line, row["date"]), "seq": int(seq), "direction": direction, "amount": amount}


def _datetime(line: int, value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = _text(value).replace("T", " ")
    for pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise FileError(f"Row {line}: TXN_DATE '{text}' is not a date (DD/MM/YYYY or YYYY-MM-DD).")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="ignore")
    text = str(value).replace("\x00", "").strip()
    return "" if text.lower() in {"none", "null", "nan"} else text
