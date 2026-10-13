**User Request:** Find likely duplicate products in the catalog.

**Selected Workflow:** WF006 · Duplicate Product Detection
**Routing:** keyword · confidence 0.905 · matched terms ['likely', 'duplicate', 'product', 'catalog'] (evidence 22.48, runner-up 3.3)
**Mode:** offline (deterministic rules and templates)
**Inputs:** catalog_file=data/sample/catalog.csv; min_similarity=0.75

**Steps Executed:**
1. ✓ Load products — `load_table` → loaded 13 catalog rows (2.0 ms)
2. ✓ normalize names/SKUs — `normalize_fields` → normalised SKU and name for 13 rows (0.2 ms)
3. ✓ compare identifiers — `find_exact_duplicates` → 2 exact SKU match group(s) (0.1 ms)
4. ✓ compare product attributes — `similar_pairs` → 6 similar pair(s) by name + attributes (5.1 ms)
5. ✓ group likely duplicates — `group_duplicates` → 4 duplicate group(s) (0.1 ms)
6. ✓ assign confidence — `assign_confidence` → 4 record(s) (0.1 ms)

**Status:** Completed

**Result:**

**Likely duplicate products**

4 duplicate group(s) in 13 catalog rows: 2 definite (same SKU) and 2 possible (different SKU, similar name and attributes).

*Duplicate groups*

| group | confidence | score | products | matching_fields |
| --- | --- | --- | --- | --- |
| 1 | Definite duplicate | 1.0 | SKU-1006 / Running Shoes Blue Size 10 \| sku-1006 / Running Shoes - Blue (Size 10) \| SKU-3101 / Mens Running Shoe Blue 10 (possible) | identical sku; name similarity 1.00; same brand, color, size, category; name similarity 0.91; same brand, color, size, category |
| 2 | Definite duplicate | 1.0 | SKU-1008 / Canvas Tote Bag \| SKU-1008 / Canvas Tote Bag Natural | identical sku; name similarity 0.79; same brand, color, size, category |
| 3 | Possible duplicate (high) | 1.0 | SKU-1001 / Classic Cotton T-Shirt (White) \| SKU-3102 / Classic Cotton Tshirt White | name similarity 1.00; same brand, color, size, category |
| 4 | Possible duplicate (high) | 1.0 | SKU-1005 / Wool Beanie Grey \| SKU-3103 / Wool Beanie Gray | name similarity 1.00; same brand, color, size, category |
