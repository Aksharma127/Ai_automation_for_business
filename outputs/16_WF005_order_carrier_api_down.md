**User Request:** Track my order ORD-1004 please

**Selected Workflow:** WF005 · Customer Order Status
**Routing:** keyword · confidence 0.959 · matched terms ['track', 'order', 'ord'] (evidence 19.18, runner-up 0)
**Mode:** offline (deterministic rules and templates)
**Inputs:** order_id=ORD-1004

**Steps Executed:**
1. ✓ Validate identifier — `validate_identifier` → order_id = ORD-1004 (0.3 ms)
2. ✓ search order data — `lookup_orders` → found 1 order(s) (0.4 ms)
3. ✓ retrieve order status — `pick_fields` → 1 record(s) (0.2 ms)
4. ⚠ retrieve shipment information — `shipment_lookup → shipment_lookup_degraded` → tracking fetched for 1 order(s) (152.7 ms · retried 3x)
5. ✓ summarize current status — `summarize_orders` → 1 record(s) (0.3 ms)

**Status:** Completed

**Result:**

**Order status for ORD-1004**

Found 1 order(s) for ORD-1004.

*Orders*

| order_id | order_date | order_status | items | carrier | tracking_number | shipment |
| --- | --- | --- | --- | --- | --- | --- |
| ORD-1004 | 2026-10-10 | shipped | 1x Leather Belt Brown | DHL | DHL-OUTAGE-0001 | carrier tracking temporarily unavailable |

**Notes / handled issues:**
- ORD-1004: live tracking unavailable (DHL tracking API timed out); showing order-system status only
