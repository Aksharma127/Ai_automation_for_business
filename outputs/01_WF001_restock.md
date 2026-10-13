**User Request:** Which products need restocking?

**Selected Workflow:** WF001 · Inventory Restock Check
**Routing:** keyword · confidence 0.801 · matched terms ['product', 'need', 'restock'] (evidence 14.19, runner-up 3.3)
**Mode:** offline (deterministic rules and templates)
**Inputs:** inventory_file=data/sample/inventory.csv; reorder_multiplier=2

**Steps Executed:**
1. ✓ Load inventory — `load_table` → loaded 10 products (3.4 ms)
2. ✓ compare current stock with minimum threshold — `add_columns` → compared stock with threshold for 10 products (0.3 ms)
3. ✓ identify low-stock products — `filter_rows` → 5 product(s) below threshold (0.1 ms)
4. ✓ calculate reorder quantity — `add_columns` → calculated reorder quantity for 5 product(s) (0.3 ms)
5. ✓ generate restock list — `sort_rows` → restock list with 5 product(s), lowest stock first (0.1 ms)

**Status:** Completed

**Result:**

**Products requiring restock**

5 of 10 products are below their minimum stock threshold. Estimated reorder cost: $2222.15.

*Restock list*

| sku | product_name | current_stock | threshold | suggested_reorder_qty | estimated_cost | supplier |
| --- | --- | --- | --- | --- | --- | --- |
| SKU-1005 | Wool Beanie Grey | 0 | 15 | 30 | 93.0 | KnitHouse |
| SKU-1007 | Running Shoes Black Size 9 | 5 | 20 | 35 | 980 | StrideMax |
| SKU-1003 | Slim Fit Denim Jeans | 8 | 25 | 42 | 596.4 | DenimCo |
| SKU-1001 | Classic Cotton T-Shirt (White) | 12 | 40 | 68 | 306.0 | ThreadWorks |
| SKU-1009 | Hooded Sweatshirt Navy | 19 | 20 | 21 | 246.75 | ThreadWorks |
