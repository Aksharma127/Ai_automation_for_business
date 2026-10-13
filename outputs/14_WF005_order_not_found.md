**User Request:** Where is order ORD-9999?

**Selected Workflow:** WF005 · Customer Order Status
**Routing:** keyword · confidence 0.864 · matched terms ['order', 'ord'] (evidence 11.99, runner-up 0)
**Mode:** offline (deterministic rules and templates)
**Inputs:** order_id=ORD-9999; orders_db=data/sample/orders.json; shipments_api=data/sample/shipments.json

**Steps Executed:**
1. ✓ Validate identifier — `validate_identifier` → order_id = ORD-9999 (0.1 ms)
2. ? search order data — `find_records` → I couldn't find an order for ORD-9999. Could you share another identifier, such as the order ID from your confirmation email or the email address used at checkout? (0.2 ms)

**Status:** Needs more information

**Result:**

I couldn't find an order for ORD-9999. Could you share another identifier, such as the order ID from your confirmation email or the email address used at checkout?
