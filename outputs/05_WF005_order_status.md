**User Request:** Where is order ORD-1001?

**Selected Workflow:** WF005 · Customer Order Status
**Routing:** keyword · confidence 0.939 · matched terms ['order', 'ord', '1001'] (evidence 16.79, runner-up 0)
**Mode:** offline (deterministic rules and templates)
**Inputs:** order_id=ORD-1001

**Steps Executed:**
1. ✓ Validate identifier — `validate_identifier` → order_id = ORD-1001 (0.6 ms)
2. ✓ search order data — `lookup_orders` → found 1 order(s) (0.6 ms)
3. ✓ retrieve order status — `pick_fields` → 1 record(s) (0.3 ms)
4. ✓ retrieve shipment information — `shipment_lookup` → tracking fetched for 1 order(s) (51.1 ms · retried 1x)
5. ✓ summarize current status — `summarize_orders` → 1 record(s) (0.3 ms)

**Status:** Completed

**Result:**

**Order status for ORD-1001**

Found 1 order(s) for ORD-1001.

*Orders*

| order_id | order_date | order_status | items | carrier | tracking_number | shipment |
| --- | --- | --- | --- | --- | --- | --- |
| ORD-1001 | 2026-10-08 | shipped | 1x Running Shoes Blue Size 10, 2x Sports Water Bottle 750ml | UPS | 1Z999AA10123456784 | in transit, last seen Louisville, KY hub (2026-10-13T06:42:00Z), ETA 2026-10-15 |
