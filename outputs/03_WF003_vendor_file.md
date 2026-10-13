**User Request:** Process this vendor spreadsheet and show invalid rows.

**Selected Workflow:** WF003 · Vendor File Processing
**Routing:** keyword · confidence 0.918 · matched terms ['proces', 'vendor', 'spreadsheet', 'invalid', 'rows'] (evidence 34.15, runner-up 5.38)
**Mode:** offline (deterministic rules and templates)
**Inputs:** vendor_file=data/sample/vendor_upload.xlsx

**Steps Executed:**
1. ✓ Read file — `load_table` → read 9 rows (7.4 ms)
2. ✓ detect columns — `detect_columns` → mapped 6 columns (0 unmapped) (0.5 ms)
3. ✓ normalize column names — `rename_columns` → renamed to canonical names; 8 non-empty rows (0.2 ms)
4. ✓ validate required fields — `validate_rows` → 8 record(s) (0.1 ms)
5. ✓ identify invalid rows — `partition_rows` → 6 valid, 2 invalid (0.2 ms)
6. ✓ produce cleaned dataset — `export_tables` → wrote outputs/files/vendor_clean.csv (0.5 ms)

**Status:** Completed

**Result:**

**Vendor file processing summary**

8 data rows processed: 6 valid, 2 invalid (missing SKU or product name), 2 with value warnings. Cleaned file: outputs/files/vendor_clean.csv; invalid-row report: outputs/files/vendor_invalid_rows.csv.

*Detected column mapping*

- **Item SKU:** sku
- **Product Title:** product_name
- **Unit Cost ($):** cost
- **Qty Available:** quantity
- **Colour:** color
- **Vendor:** vendor

*Invalid rows*

| source_row | sku | product_name | errors |
| --- | --- | --- | --- |
| 4 |  | Cable Knit Gloves | missing sku |
| 5 | V-504 |  | missing product_name |

*Cleaned dataset*

| sku | product_name | cost | quantity | color | vendor | warnings |
| --- | --- | --- | --- | --- | --- | --- |
| V-501 | Merino Wool Scarf | 18.5 | 120 | Rust | KnitHouse |  |
| V-502 | Wool Beanie | 9.2 | 300 | Grey | KnitHouse |  |
| V-505 | Chunky Knit Sweater |  | 60 | Oat | KnitHouse | cost 'twenty' is not a number (cleared) |
| V-506 | Thermal Socks (3-pack) | 6.4 | 500 | Mixed | KnitHouse |  |
| V-507 | Alpaca Throw Blanket | 32 |  | Sand | KnitHouse | quantity -5 below 0 (cleared) |
| V-508 | Fleece Ear Warmer | 4.75 | 150 | Navy | KnitHouse |  |

**Notes / handled issues:**
- dropped a completely empty row
