**User Request:** Validate our product prices against the vendor price list with a 5% tolerance.

**Selected Workflow:** WF002 · Product Price Validation
**Routing:** keyword · confidence 0.877 · matched terms ['validate', 'product', 'pric', 'vendor', 'price'] (evidence 26.35, runner-up 5.92)
**Mode:** offline (deterministic rules and templates)
**Inputs:** product_file=data/sample/products.csv; vendor_file=data/sample/vendor_prices.csv; tolerance_pct=5

**Steps Executed:**
1. ✓ Load product prices — `load_tables` → loaded 13 internal and 10 vendor prices (2.6 ms)
2. ✓ match products by SKU — `join_tables` → 9 matched by SKU, 4 without vendor price, 1 unknown vendor SKUs (0.1 ms)
3. ✓ compare internal and vendor prices — `add_columns` → 9 record(s) (0.2 ms)
4. ✓ calculate percentage difference — `add_columns` → 9 record(s) (0.3 ms)
5. ✓ flag exceptions — `filter_rows` → 4 exception(s) flagged (0.2 ms)

**Status:** Completed

**Result:**

**Price validation report**

9 products matched by SKU; 4 differ from the vendor price by more than 5%.

*Exceptions (difference above tolerance)*

| sku | product_name | our_price | vendor_price | price_diff | pct_diff |
| --- | --- | --- | --- | --- | --- |
| SKU-1002 | Classic Cotton T-Shirt (Black) | 19.99 | 22.99 | 3.0 | 15.01 |
| SKU-1004 | Leather Belt Brown | 34.5 | 29.9 | -4.6 | 13.33 |
| SKU-1006 | Running Shoes Blue Size 10 | 89 | 99 | 10 | 11.24 |
| SKU-1009 | Hooded Sweatshirt Navy | 49 | 42 | -7 | 14.29 |

*All matched products*

| sku | product_name | our_price | vendor_price | price_diff | pct_diff |
| --- | --- | --- | --- | --- | --- |
| SKU-1001 | Classic Cotton T-Shirt (White) | 19.99 | 19.49 | -0.5 | 2.5 |
| SKU-1002 | Classic Cotton T-Shirt (Black) | 19.99 | 22.99 | 3.0 | 15.01 |
| SKU-1003 | Slim Fit Denim Jeans | 59 | 59 | 0 | 0.0 |
| SKU-1004 | Leather Belt Brown | 34.5 | 29.9 | -4.6 | 13.33 |
| SKU-1005 | Wool Beanie Grey | 24 | 24.5 | 0.5 | 2.08 |
| SKU-1006 | Running Shoes Blue Size 10 | 89 | 99 | 10 | 11.24 |
| SKU-1007 | Running Shoes Black Size 9 | 89 | 89.9 | 0.9 | 1.01 |
| SKU-1009 | Hooded Sweatshirt Navy | 49 | 42 | -7 | 14.29 |
| SKU-1010 | Sports Water Bottle 750ml | 15 | 15 | 0 | 0.0 |

*Products with no vendor price*

| sku | product_name |
| --- | --- |
| SKU-1008 | Canvas Tote Bag |
| SKU-1011 | Quilted Puffer Jacket Olive |
| SKU-1012 | Merino Wool Scarf Rust |
| SKU-1013 | Corduroy Overshirt Camel |

*Vendor SKUs not in our catalog*

| vendor_sku | vendor_product_name | vendor_price |
| --- | --- | --- |
| SKU-2001 | Unknown Vendor Item | 12 |
