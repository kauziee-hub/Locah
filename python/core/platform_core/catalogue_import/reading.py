"""Read an uploaded catalogue sheet (CSV or XLSX) into a plain table.

Pure functions, no database. XLSX is read with the standard library (it is a
zip of XML parts): the first worksheet, shared and inline strings, numbers and
booleans. Formulas give their cached value. Limits keep a hostile or broken
file from costing more than a normal one: size, rows, columns, and the
uncompressed size of the zip parts actually read.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from xml.etree import ElementTree

MAX_BYTES = 2_000_000
MAX_ROWS = 2_000
MAX_COLUMNS = 40
MAX_CELL = 2_000
_MAX_UNZIPPED = 30_000_000

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class ReadProblem(ValueError):
    """The file cannot be read as a catalogue sheet; the message says why, in owner words."""


@dataclass
class Table:
    source: str  # csv | xlsx
    headers: list[str]
    rows: list[list[str]]
    file_hash: str
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# A menu or price list that is not a sheet — a PDF or a photo — is read by the
# AI document reader instead (services/catalogue_import.py), when one is set up.
MAX_DOCUMENT_BYTES = 8_000_000
_DOCUMENT_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "application/pdf"), (b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))


def document_type(filename: str, data: bytes) -> str | None:
    """The MIME type when the file is a PDF or photo (by its bytes, not its name)."""
    for magic, mime in _DOCUMENT_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_table(filename: str, data: bytes) -> Table:
    if not data:
        raise ReadProblem("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ReadProblem("The file is larger than 2 MB. Split it into smaller sheets and import each one.")
    name = (filename or "").lower()
    if name.endswith(".xlsx") or data[:2] == b"PK":
        if name.endswith(".xls") and not name.endswith(".xlsx"):
            raise ReadProblem("Old .xls files can't be read. Save the sheet as .xlsx or .csv and try again.")
        source, raw = "xlsx", _xlsx_rows(data)
    elif name.endswith((".csv", ".txt", ".tsv")) or not name:
        source, raw = "csv", _csv_rows(data)
    else:
        raise ReadProblem("Upload a .csv or .xlsx file.")
    return _to_table(source, raw, file_hash(data))


def _to_table(source: str, raw: list[list[str]], digest: str) -> Table:
    rows = [[_clean(c) for c in r[:MAX_COLUMNS]] for r in raw]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        raise ReadProblem("No rows were found in the file.")
    headers = rows[0]
    width = max(len(r) for r in rows)
    headers = headers + [""] * (width - len(headers))
    headers = [h or f"Column {i + 1}" for i, h in enumerate(headers)]
    body = [r + [""] * (width - len(r)) for r in rows[1:]]
    if not body:
        raise ReadProblem("Only a header row was found — add one item per row below it.")
    truncated = len(body) > MAX_ROWS
    table = Table(source, headers, body[:MAX_ROWS], digest, truncated)
    if truncated:
        table.notes.append(f"Only the first {MAX_ROWS} rows are read. Import the rest as a second file.")
    return table


def _clean(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace(" ", " ").strip()
    return text[:MAX_CELL]


# ---------------------------------------------------------------- CSV

def _csv_rows(data: bytes) -> list[list[str]]:
    text = None
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
            if encoding == "utf-16" and "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ReadProblem("The file's text could not be read. Save it as CSV (UTF-8) and try again.")
    sample = text[:20_000]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    out: list[list[str]] = []
    try:
        for row in reader:
            out.append(row)
            if len(out) > MAX_ROWS + 50:
                break
    except csv.Error as exc:
        raise ReadProblem(f"The CSV could not be read ({exc}).") from exc
    return out


# ---------------------------------------------------------------- XLSX

def _xlsx_rows(data: bytes) -> list[list[str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ReadProblem("This doesn't look like an Excel (.xlsx) file.") from exc
    budget = [_MAX_UNZIPPED]

    def part(name: str) -> bytes | None:
        try:
            info = archive.getinfo(name)
        except KeyError:
            return None
        if info.file_size > budget[0]:
            raise ReadProblem("The spreadsheet is too large to read. Save a smaller sheet as .xlsx or .csv.")
        budget[0] -= info.file_size
        return archive.read(name)

    sheet_path = _first_sheet_path(part)
    if sheet_path is None:
        raise ReadProblem("No worksheet was found in the file.")
    shared = _shared_strings(part("xl/sharedStrings.xml"))
    sheet = part(sheet_path)
    if sheet is None:
        raise ReadProblem("No worksheet was found in the file.")
    try:
        root = ElementTree.fromstring(sheet)
    except ElementTree.ParseError as exc:
        raise ReadProblem("The worksheet could not be read.") from exc
    rows: list[list[str]] = []
    for row in root.iterfind(".//m:sheetData/m:row", _NS):
        cells: dict[int, str] = {}
        for c in row.iterfind("m:c", _NS):
            col = _column_index(c.get("r") or "")
            if col is None or col >= MAX_COLUMNS:
                continue
            cells[col] = _cell_value(c, shared)
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        else:
            rows.append([])
        if len(rows) > MAX_ROWS + 50:
            break
    return rows


def _first_sheet_path(read: Callable[[str], bytes | None]) -> str | None:
    workbook = read("xl/workbook.xml")
    rels = read("xl/_rels/workbook.xml.rels")
    if workbook is None:
        return "xl/worksheets/sheet1.xml"
    first = ElementTree.fromstring(workbook).find(".//m:sheets/m:sheet", _NS)
    if first is None:
        return None
    rid = first.get(f"{{{_NS['r']}}}id")
    if rels is not None and rid:
        for rel in ElementTree.fromstring(rels).iterfind("rel:Relationship", _NS):
            if rel.get("Id") == rid:
                target = (rel.get("Target") or "").lstrip("/")
                return target if target.startswith("xl/") else f"xl/{target}"
    return "xl/worksheets/sheet1.xml"


def _shared_strings(raw: bytes | None) -> list[str]:
    if raw is None:
        return []
    root = ElementTree.fromstring(raw)
    out = []
    for si in root.iterfind("m:si", _NS):
        out.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    return out


_COL = re.compile(r"^([A-Z]+)\d*$")


def _column_index(ref: str) -> int | None:
    m = _COL.match(ref.upper())
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _cell_value(c: ElementTree.Element, shared: list[str]) -> str:
    kind = c.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
    v = c.find("m:v", _NS)
    raw = v.text if v is not None and v.text is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if kind in ("str", "e"):
        return raw
    try:  # a number: 120.0 -> "120", keep decimals that matter
        number = float(raw)
    except ValueError:
        return raw
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")
