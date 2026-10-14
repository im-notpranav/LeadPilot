"""CSV import: a spreadsheet or a CRM export (HubSpot, Salesforce, Pipedrive, Zoho...) becomes lead_created events.

Columns are matched automatically by name (see fields.ALIASES) and can be overridden per column. Rows with a past
"created" date are loaded as history at that date, so they never trigger live SLA reassignment. Event ids are
derived from the file and options, so importing the same file twice adds nothing the second time.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime

from ..engine.types import iso, parse_ts
from .fields import CAPTURE_METHODS, canonical, lead_events, lead_from_fields

MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024
TARGETS = ("email", "name", "first_name", "last_name", "company", "title", "phone", "country", "website", "message",
           "form_type", "lead_source", "created_at")


class CsvImportError(ValueError):
    pass


def read_csv(text: str) -> tuple[list[str], list[dict]]:
    if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
        raise CsvImportError(f"file is larger than {MAX_BYTES // (1024 * 1024)} MB; split it and import the parts")
    text = text.lstrip("﻿")
    if not text.strip():
        raise CsvImportError("the file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        raise CsvImportError("no header row found: the first line must name the columns")
    rows = []
    for raw in reader:
        row = {(k or "").strip(): (", ".join(v) if isinstance(v, list) else v) for k, v in raw.items() if k}
        if any((v or "").strip() for v in row.values()):
            rows.append(row)
        if len(rows) > MAX_ROWS:
            raise CsvImportError(f"more than {MAX_ROWS} rows; split the file")
    return headers, rows


def column_plan(headers: list[str], column_map: dict | None = None) -> dict[str, str | None]:
    """{header: canonical field or None} as the importer will use it."""
    _, used = canonical({h: "x@y.io" if "mail" in h.lower() else "x" for h in headers}, column_map)
    return {h: used.get(h) for h in headers}


def batch_id(text: str, options: dict) -> str:
    basis = text + "|" + "|".join(f"{k}={options.get(k)}" for k in sorted(options))
    return hashlib.sha256(basis.encode("utf-8", "ignore")).hexdigest()[:10]


def map_rows(text: str, *, source: str, capture_method: str = "cold_import", column_map: dict | None = None,
             use_record_source: bool = True, now: datetime | None = None) -> dict:
    """Parse and map a whole file. Returns headers, the column plan, per-row results and the events to publish."""
    if capture_method not in CAPTURE_METHODS:
        raise CsvImportError(f"capture_method must be one of {', '.join(CAPTURE_METHODS)}")
    headers, rows = read_csv(text)
    plan = column_plan(headers, column_map)
    if "email" not in plan.values() and "phone" not in plan.values():
        raise CsvImportError("no email or phone column found: map one in the column list")
    bid = batch_id(text, {"source": source, "capture": capture_method, "map": sorted((column_map or {}).items()),
                          "rec_src": use_record_source})
    results, events = [], []
    seen: set[str] = set()
    for n, row in enumerate(rows, start=2):                     # line numbers as the spreadsheet shows them
        m = lead_from_fields(row, source=source, capture_method=capture_method, column_map=column_map,
                             form_kind="auto" if capture_method == "form_submit" else "none",
                             use_record_source=use_record_source)
        if not m["ok"]:
            results.append({"line": n, "ok": False, "error": m["error"]})
            continue
        key = (m["payload"].get("email") or m["payload"].get("phone") or "").lower()
        if key in seen:
            results.append({"line": n, "ok": False, "error": f"same person as an earlier row ({key})"})
            continue
        seen.add(key)
        history = False
        if m["ts"] and now is not None:
            if parse_ts(m["ts"]) > now:
                m["ts"] = None                                  # a future date is a typo: use the import time
            else:
                history = True
        pl = m["payload"]
        results.append({"line": n, "ok": True, "name": pl.get("name"), "email": pl.get("email"),
                        "phone": pl.get("phone"), "company": pl.get("company"), "title": pl.get("title"),
                        "country": pl.get("country"), "source": m["source"], "intent": m["intent"],
                        "created_at": m["ts"]})
        events.extend(lead_events(m, f"imp_{bid}_{n:05d}", history=history))
    ok = sum(1 for r in results if r["ok"])
    return {"batch_id": bid, "headers": headers, "columns": plan, "targets": list(TARGETS), "rows": results,
            "events": events, "counts": {"rows": len(rows), "ok": ok, "skipped": len(rows) - ok},
            "generated_at": iso(now) if now else None}
