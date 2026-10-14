"""Regenerates the two binary/generated sample files (vendor XLSX, execution logs).

The other sample files in data/sample are small hand-written CSV/JSON files.
Run:  python scripts/make_sample_data.py
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


def vendor_upload() -> None:
    # Deliberately messy headers and rows: the WF003 agent must detect and normalise them.
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendor Feed"
    ws.append(["Item SKU", " Product Title ", "Unit Cost ($)", "Qty Available", "Colour", "Vendor"])
    rows = [
        ["V-501", "Merino Wool Scarf", 18.5, 120, "Rust", "KnitHouse"],
        ["V-502", "Wool Beanie", 9.2, 300, "Grey", "KnitHouse"],
        [None, "Cable Knit Gloves", 11.0, 80, "Cream", "KnitHouse"],
        ["V-504", None, 7.5, 45, "Black", "KnitHouse"],
        ["V-505", "Chunky Knit Sweater", "twenty", 60, "Oat", "KnitHouse"],
        ["  v-506 ", "Thermal Socks (3-pack)", 6.4, 500, "Mixed", "KnitHouse"],
        ["V-507", "Alpaca Throw Blanket", 32.0, -5, "Sand", "KnitHouse"],
        [None, None, None, None, None, None],
        ["V-508", "Fleece Ear Warmer", 4.75, 150, "Navy", "KnitHouse"],
    ]
    for r in rows:
        ws.append(r)
    wb.save(SAMPLE / "vendor_upload.xlsx")


def execution_logs() -> None:
    rng = random.Random(42)
    workflows = {
        "WF001": ("Inventory Restock Check", ["Load inventory", "Compare stock", "Identify products", "Calculate reorder", "Generate list"], 0.03, 4),
        "WF002": ("Product Price Validation", ["Load prices", "Match SKU", "Compare prices", "Calculate % diff", "Flag exceptions"], 0.05, 6),
        "WF003": ("Vendor File Processing", ["Read file", "Detect columns", "Normalize columns", "Validate fields", "Identify invalid rows", "Produce dataset"], 0.18, 22),
        "WF004": ("Product Description Generator", ["Validate attributes", "Create description", "Short description", "SEO title", "Meta description"], 0.08, 38),
        "WF005": ("Customer Order Status", ["Validate identifier", "Search order", "Retrieve status", "Retrieve shipment", "Summarize"], 0.22, 9),
        "WF006": ("Duplicate Product Detection", ["Load products", "Normalize", "Compare identifiers", "Compare attributes", "Group duplicates", "Assign confidence"], 0.04, 41),
        "WF008": ("SEO Keyword Classification", ["Read keywords", "Dedupe", "Classify intent", "Map categories", "Prioritise", "Export"], 0.06, 27),
    }
    errors = {
        "WF003": ["ValidationError: missing required column 'sku'", "ParseError: unsupported encoding"],
        "WF005": ["TimeoutError: shipment API did not respond in 10s", "TimeoutError: shipment API did not respond in 10s", "NotFound: order id not found"],
        "WF004": ["RateLimitError: LLM provider returned 429"],
        "WF002": ["KeyError: vendor price list missing SKU column"],
    }
    slow_step = {"WF004": "Create description", "WF006": "Compare attributes", "WF003": "Validate fields", "WF008": "Classify intent"}
    start = datetime(2026, 10, 1, 8, 0, 0)
    out = SAMPLE / "execution_logs.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "timestamp", "workflow_id", "workflow_name", "step", "status", "duration_sec", "error_message"])
        run = 0
        for day in range(12):
            for wf_id, (name, steps, fail_p, base) in workflows.items():
                for _ in range(rng.randint(3, 6)):
                    run += 1
                    ts = start + timedelta(days=day, minutes=rng.randint(0, 600))
                    failed_at = rng.randrange(len(steps)) if rng.random() < fail_p else None
                    if wf_id == "WF005" and failed_at is not None:
                        failed_at = 3  # shipment lookup is the fragile step
                    for i, step in enumerate(steps):
                        dur = max(0.1, rng.gauss(base / len(steps), base / len(steps) / 4))
                        if slow_step.get(wf_id) == step:
                            dur *= 3.5
                        status, err = "success", ""
                        if failed_at == i:
                            status = "failed"
                            err = rng.choice(errors.get(wf_id, ["RuntimeError: unexpected failure"]))
                        w.writerow([f"RUN-{run:05d}", ts.isoformat(), wf_id, name, step, status, round(dur, 2), err])
                        ts += timedelta(seconds=dur)
                        if status == "failed":
                            break


if __name__ == "__main__":
    vendor_upload()
    execution_logs()
    print("sample data regenerated in", SAMPLE)
