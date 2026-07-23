"""
statement_profiles.py — deterministic bank-statement format registry.

Each profile describes one bank's CSV/XLSX export layout: column names,
delimiter, encoding, date format, sign convention. Once a profile is saved
the matching format is parsed with ZERO AI tokens.

Profile files live in data/statement_profiles/<name>.json (gitignored except
example.json and .gitkeep). No bank names appear in committed code or fixtures.

Profile JSON schema (all keys):
  name              str   — human label, used as filename
  delimiter         str   — CSV field separator, e.g. ";" or ","
  encoding          str   — file encoding, e.g. "utf-8" or "cp1250"
  header_row        int   — 0-based row index of the header (default 0)
  fingerprint       list  — column names that uniquely identify this format
  column_map        dict  — maps standard field → source column name (or null)
                            fields: date, amount, currency, description, time
  date_format       str   — strptime pattern, e.g. "%d.%m.%Y"
  decimal_separator str   — "," or "."
  sign_convention   str   — "negative_expense" | "positive_expense" | "always_expense"
"""

import csv
import io
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Standard output fields every parsed row provides.
_STANDARD_FIELDS = ("date", "amount", "currency", "description", "time")

# Regex patterns used by mask_sample_rows.
_AMOUNT_RE = re.compile(
    r"^-?\d{1,3}(?:[,. ]\d{3})*(?:[,.]\d{1,4})?$"
)
_ACCOUNT_RE = re.compile(r"^\d{10,}$")


# ── Fingerprint helpers ───────────────────────────────────────────────────────

def fingerprint_from_headers(headers: list[str]) -> tuple:
    """Sorted tuple of non-empty header strings — the profile lookup key."""
    return tuple(sorted(h.strip() for h in headers if h and h.strip()))


# ── Profile persistence ───────────────────────────────────────────────────────

def load_profiles(profiles_dir: str | Path) -> dict[tuple, dict]:
    """
    Load all .json files from profiles_dir.
    Returns a dict keyed by fingerprint tuple (sorted header names).
    Silently skips files that can't be parsed.
    """
    profiles_dir = Path(profiles_dir)
    result: dict[tuple, dict] = {}
    if not profiles_dir.exists():
        return result
    for path in profiles_dir.glob("*.json"):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(profile, dict):
                log.warning("statement_profiles: skipping %s — not a JSON object", path.name)
                continue
            fp = fingerprint_from_headers(profile.get("fingerprint") or [])
            if not fp:
                log.warning("statement_profiles: skipping %s — empty fingerprint", path.name)
                continue
            result[fp] = profile
        except Exception as exc:
            log.warning("statement_profiles: could not load %s: %s", path.name, exc)
    return result


def match_profile(headers: list[str], profiles: dict[tuple, dict]) -> dict | None:
    """
    Exact set-match on fingerprint.
    Returns the matching profile dict or None.
    """
    fp = fingerprint_from_headers(headers)
    return profiles.get(fp)


def save_profile(profile: dict, profiles_dir: str | Path) -> None:
    """Write profile to <profiles_dir>/<name>.json."""
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    name = str(profile.get("name") or "unnamed").strip()
    # Sanitize filename — keep only safe chars.
    safe_name = re.sub(r"[^\w\-]", "_", name)
    path = profiles_dir / f"{safe_name}.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("statement_profiles: saved profile '%s' → %s", name, path)


# ── Masking helper ────────────────────────────────────────────────────────────

def mask_sample_rows(rows: list[list], column_map_proposal: dict) -> list[list]:
    """
    Replace amount-looking and account-number-looking cell values with "***".
    column_map_proposal maps field → source_column_name; the amount column is
    always masked. Cells matching _AMOUNT_RE or _ACCOUNT_RE are also masked.
    """
    # Determine which indices look like amounts from the proposal.
    amount_col = column_map_proposal.get("amount") or ""
    masked = []
    for row in rows:
        new_row = []
        for cell in row:
            s = str(cell).strip()
            if s == amount_col or _AMOUNT_RE.match(s) or _ACCOUNT_RE.match(s):
                new_row.append("***")
            else:
                new_row.append(cell)
        masked.append(new_row)
    return masked


# ── Parsing ───────────────────────────────────────────────────────────────────

def _normalize_amount(raw: str, decimal_separator: str) -> float:
    """
    Parse a raw amount string into a float, respecting the profile's
    decimal_separator. Handles thousands separators by stripping them.
    """
    s = str(raw or "").strip()
    negative = s.startswith("-")
    s = s.lstrip("+-").strip()
    # Determine which separator is thousands and which is decimal.
    if decimal_separator == ",":
        # e.g. "1.234,56" — strip "." as thousands, replace "," with "."
        s = s.replace(".", "").replace(",", ".")
    else:
        # decimal_separator == "." — strip "," as thousands
        s = s.replace(",", "")
    try:
        value = float(s)
    except ValueError as exc:
        raise ValueError(f"Cannot parse amount {raw!r} with decimal_sep={decimal_separator!r}") from exc
    return -value if negative else value


def _parse_row_dict(
    row: dict[str, str],
    profile: dict,
) -> dict | None:
    """
    Map one CSV/XLSX row dict (column_name → cell_value) into the standard
    output format. Returns None if the row appears to be a header or is empty.
    """
    col_map: dict[str, str | None] = profile.get("column_map") or {}
    decimal_sep: str = profile.get("decimal_separator") or "."
    date_fmt: str = profile.get("date_format") or "%Y-%m-%d"
    sign_convention: str = profile.get("sign_convention") or "negative_expense"

    # Amount
    amount_col = col_map.get("amount")
    if not amount_col or amount_col not in row:
        return None
    raw_amount = str(row.get(amount_col) or "").strip()
    if not raw_amount:
        return None
    try:
        amount = _normalize_amount(raw_amount, decimal_sep)
    except ValueError:
        log.debug("statement_profiles: skipping row — unparseable amount %r", raw_amount)
        return None

    # Date
    date_col = col_map.get("date")
    parsed_date: date | None = None
    if date_col and date_col in row:
        raw_date = str(row[date_col]).strip()
        try:
            parsed_date = datetime.strptime(raw_date, date_fmt).date()
        except (ValueError, TypeError):
            log.debug("statement_profiles: bad date %r with format %r", raw_date, date_fmt)

    # Currency
    currency_col = col_map.get("currency")
    currency = "PLN"
    if currency_col and currency_col in row:
        currency = str(row[currency_col]).strip() or "PLN"

    # Description
    desc_col = col_map.get("description")
    description = ""
    if desc_col and desc_col in row:
        description = str(row[desc_col]).strip()

    # Time (optional)
    time_col = col_map.get("time")
    time_val: str | None = None
    if time_col and time_col in row:
        raw_t = str(row[time_col]).strip()
        time_val = raw_t or None

    # Sign convention → transaction type
    if sign_convention == "negative_expense":
        txn_type = "Expense" if amount < 0 else "Income"
        amount = abs(amount)
    elif sign_convention == "positive_expense":
        txn_type = "Expense" if amount > 0 else "Income"
        amount = abs(amount)
    else:
        # "always_expense" or unknown
        txn_type = "Expense"
        amount = abs(amount)

    return {
        "date": parsed_date.isoformat() if parsed_date else "",
        "value": round(amount, 2),
        "currency": currency,
        "type": txn_type,
        "description": description,
        "time": time_val,
    }


def _read_headers_and_rows_csv(
    content: str,
    delimiter: str,
    header_row: int,
) -> tuple[list[str], list[dict[str, str]]]:
    """Read CSV content; return (headers, list of row dicts)."""
    lines = content.splitlines()
    # Skip lines before the header row.
    relevant = lines[header_row:]
    if not relevant:
        return [], []
    reader = csv.DictReader(io.StringIO("\n".join(relevant)), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    rows = [dict(r) for r in reader]
    return headers, rows


def _read_headers_and_rows_xlsx(
    file_bytes: bytes,
    header_row: int,
) -> tuple[list[str], list[dict[str, str]]]:
    """Read XLSX bytes using openpyxl; return (headers, list of row dicts)."""
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("openpyxl is required for XLSX support") from exc
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(all_rows) <= header_row:
        return [], []
    header_cells = all_rows[header_row]
    headers = [str(c or "").strip() for c in header_cells]
    result_rows: list[dict[str, str]] = []
    for raw_row in all_rows[header_row + 1 :]:
        row_dict: dict[str, str] = {}
        for col_name, cell in zip(headers, raw_row):
            row_dict[col_name] = str(cell) if cell is not None else ""
        result_rows.append(row_dict)
    return headers, result_rows


def parse_statement(
    file_bytes: bytes,
    filename: str,
    profile: dict,
) -> list[dict]:
    """
    Parse a CSV or XLSX file using the given profile.

    Returns a list of dicts with keys:
      date (str ISO), value (float), currency (str), type (str),
      description (str), time (str|None)

    Rows that cannot be parsed (bad amount, empty) are silently skipped.
    """
    ext = Path(filename).suffix.lower()
    encoding: str = profile.get("encoding") or "utf-8"
    delimiter: str = profile.get("delimiter") or ","
    header_row: int = int(profile.get("header_row") or 0)

    if ext in {".xlsx", ".xls"}:
        headers, rows = _read_headers_and_rows_xlsx(file_bytes, header_row)
    else:
        # .csv, .txt, or anything else → treat as delimited text
        try:
            content = file_bytes.decode(encoding, errors="replace")
        except LookupError:
            content = file_bytes.decode("utf-8", errors="replace")
        headers, rows = _read_headers_and_rows_csv(content, delimiter, header_row)

    if not headers:
        log.warning("statement_profiles: parse_statement found no headers in %s", filename)
        return []

    result = []
    for row in rows:
        parsed = _parse_row_dict(row, profile)
        if parsed:
            result.append(parsed)

    log.info(
        "statement_profiles: parsed %d rows from %s using profile '%s'",
        len(result), filename, profile.get("name"),
    )
    return result


# ── .txt delimiter sniffing ───────────────────────────────────────────────────

def sniff_txt_delimiter(content: str, candidates: tuple[str, ...] = (";", ",", "\t")) -> str | None:
    """
    Try each candidate delimiter on the content lines; pick the one that gives
    the most CONSISTENT column count across lines (≥2 columns, ≥2 data rows
    consistent). Returns the winning delimiter or None if no delimiter wins.
    """
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    def score(delim: str) -> tuple[int, int]:
        counts = [len(line.split(delim)) for line in lines]
        mode_count = max(set(counts), key=counts.count)
        if mode_count < 2:
            return 0, 0
        consistent = sum(1 for c in counts if c == mode_count)
        return consistent, mode_count

    best_delim = None
    best_consistent = 0
    for delim in candidates:
        consistent, col_count = score(delim)
        if col_count >= 2 and consistent > best_consistent:
            best_consistent = consistent
            best_delim = delim

    # Require at least 80% of lines to be consistent.
    if best_delim and best_consistent / len(lines) >= 0.8:
        return best_delim
    return None


# ── AI-assisted mapping ───────────────────────────────────────────────────────

_MAPPING_SYSTEM_PROMPT = (
    "You map bank statement columns to standard fields. Respond ONLY with valid JSON. "
    "Do not add any explanation or markdown fences."
)

_REQUIRED_FIELDS = ("date", "amount", "currency", "description", "time")
_SIGN_CONVENTIONS = ("negative_expense", "positive_expense", "always_expense")


def _build_mapping_prompt(headers: list[str], sample_rows: list[list]) -> str:
    rows_text = "\n".join(
        "  [" + ", ".join(repr(str(cell)) for cell in row) + "]"
        for row in sample_rows
    )
    return (
        f"Headers: {headers}\n\n"
        f"Sample rows (sensitive values masked):\n{rows_text}\n\n"
        f"Map each header to one of these standard fields: {list(_REQUIRED_FIELDS)}.\n"
        f"A header may map to null if it is not needed.\n\n"
        f"Return JSON with exactly these keys:\n"
        f"  column_map: {{date: str|null, amount: str|null, currency: str|null, "
        f"description: str|null, time: str|null}}\n"
        f"  date_format: str  (strptime pattern, e.g. \"%d.%m.%Y\")\n"
        f"  decimal_separator: \",\" or \".\"\n"
        f"  sign_convention: one of {list(_SIGN_CONVENTIONS)}\n\n"
        f"column_map values must be header strings from the provided list, or null."
    )


def propose_mapping(
    headers: list[str],
    sample_rows: list[list],
    ai_client,
) -> dict:
    """
    Ask the AI to propose a column mapping for an unknown statement format.
    Makes ONE chat completion call; returns the parsed dict on success or {}
    on failure. The caller handles fallback.

    ai_client must implement the AIProvider.chat(messages) → str interface.
    Pass the provider instance from ai_parser.get_provider().
    """
    masked = mask_sample_rows(sample_rows, {})
    prompt = _build_mapping_prompt(headers, masked[: min(3, len(masked))])
    try:
        messages = [
            {"role": "system", "content": _MAPPING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        raw = ai_client.chat(messages)
        # Strip markdown fences if the model added them.
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[^\n]*\n?", "", raw)
            raw = raw.rstrip("`").strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("AI returned non-object JSON")
        # Validate minimal structure.
        col_map = parsed.get("column_map")
        if not isinstance(col_map, dict):
            raise ValueError("AI response missing column_map")
        return parsed
    except Exception as exc:
        log.warning("statement_profiles.propose_mapping failed: %s", exc)
        return {}
