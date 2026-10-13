**User Request:** What's the status of my orders? My email is jane.doe@example.com

**Selected Workflow:** WF005 · Customer Order Status
**Routing:** keyword · confidence 0.909 · matched terms ['statu', 'order'] (evidence 14.39, runner-up 0)
**Mode:** offline (deterministic rules and templates)
**Inputs:** email=jane.doe@example.com; orders_db=data/sample/orders.json; shipments_api=data/sample/shipments.json

**Steps Executed:**
1. ✓ Validate identifier — `validate_identifier` → customer_email = jane.doe@example.com (0.1 ms)
2. ✓ search order data — `find_records` → found 2 order(s) (0.2 ms)
3. ✓ retrieve order status — `pick_fields` → 2 record(s) (0.0 ms)
4. ✓ retrieve shipment information — `shipment_lookup` → tracking fetched for 2 order(s) (50.7 ms · retried 1x)
5. ✓ summarize current status — `summarize_orders` → 2 record(s) (0.1 ms)

**Status:** Completed

**Result:**

**Order status for jane.doe@example.com**

Found 2 order(s) for jane.doe@example.com.

*Orders*

| order_id | order_date | order_status | items | carrier | tracking_number | shipment |
| --- | --- | --- | --- | --- | --- | --- |
| ORD-1001 | 2026-10-08 | shipped | 1x Running Shoes Blue Size 10, 2x Sports Water Bottle 750ml | UPS | 1Z999AA10123456784 | in transit, last seen Louisville, KY hub (2026-10-13T06:42:00Z), ETA 2026-10-15 |
| ORD-1003 | 2026-09-28 | delivered | 3x Classic Cotton T-Shirt (White) | USPS | 9400100000000000000001 | delivered, last seen Front door, Austin TX (2026-10-02T14:10:00Z) |
