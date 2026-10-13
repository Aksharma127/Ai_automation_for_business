**User Request:** Create a campaign brief for the new collection to drive online sales with 20% off outerwear, targeting young professionals, from 2026-11-01 to 2026-11-30.

**Selected Workflow:** WF007 · Marketing Campaign Brief
**Routing:** keyword · confidence 0.844 · matched terms ['create', 'campaign', 'brief', 'collection'] (evidence 25.16, runner-up 7.19)
**Mode:** offline (deterministic rules and templates)
**Inputs:** goal=drive online sales; start_date=2026-11-01; end_date=2026-11-30; target_audience=young professionals; promotion=20% off outerwear; collection=autumn-2026; product_file=data/sample/products.csv

**Steps Executed:**
1. ✓ Validate inputs — `collect_fields` → goal, start_date, end_date, target_audience, promotion provided, 0 missing (0.2 ms)
2. ✓ identify campaign objective — `classify_text` → objective = sales (0.1 ms)
3. ✓ summarize products — `query_table` → 5 product(s) in the collection (2.1 ms)
4. ✓ create messaging — `generate_content` → Headline: New in: the autumn-2026 collection – 20% off outerwear
Key message: Made for ... (0.5 ms)
5. ✓ create channel recommendations — `lookup_rules` → 4 channels recommended (0.1 ms)
6. ✓ create campaign checklist — `build_timeline` → 9 dated checklist items (0.1 ms)

**Status:** Completed

**Result:**

**Campaign brief: autumn-2026 collection**

Brief for a sales campaign running 2026-11-01 to 2026-11-30.

*Overview*

- **Goal:** drive online sales
- **Objective:** sales
- **Target audience:** young professionals
- **Promotion:** 20% off outerwear
- **Start date:** 2026-11-01
- **End date:** 2026-11-30

*Featured products*

| sku | product_name | category | our_price |
| --- | --- | --- | --- |
| SKU-1005 | Wool Beanie Grey | Accessories | 24 |
| SKU-1009 | Hooded Sweatshirt Navy | Apparel | 49 |
| SKU-1011 | Quilted Puffer Jacket Olive | Outerwear | 129 |
| SKU-1012 | Merino Wool Scarf Rust | Accessories | 39 |
| SKU-1013 | Corduroy Overshirt Camel | Apparel | 69 |

*Messaging*

Headline: New in: the autumn-2026 collection – 20% off outerwear
Key message: Made for young professionals: Wool Beanie Grey, Hooded Sweatshirt Navy, Quilted Puffer Jacket Olive, Merino Wool Scarf Rust and Corduroy Overshirt Camel. Available 2026-11-01 to 2026-11-30.
Call to action: Shop the collection and get 20% off outerwear.

*Channel recommendations*

| channel | why |
| --- | --- |
| Email | Highest-converting owned channel; segment by past purchases |
| Meta Ads (retargeting) | Re-engage site visitors who viewed the collection |
| Google Search & Shopping | Capture high-intent searches for the products |
| Onsite banner | Convert existing traffic during the promotion window |

*Campaign checklist*

| due | task | owner | done |
| --- | --- | --- | --- |
| 2026-10-11 | Finalise brief, budget and KPIs | Marketing lead | [ ] |
| 2026-10-14 | Brief creative team (photo, copy, video) | Creative | [ ] |
| 2026-10-18 | Confirm stock levels for featured products | Merchandising | [ ] |
| 2026-10-22 | Build email + landing page; set up promo codes | CRM / Web | [ ] |
| 2026-10-27 | Set up and QA paid campaigns and tracking | Performance | [ ] |
| 2026-11-01 | Launch campaign | Marketing lead | [ ] |
| 2026-11-23 | Mid-campaign performance review | Marketing lead | [ ] |
| 2026-11-30 | Campaign ends; switch off promo codes | CRM / Web | [ ] |
| 2026-12-07 | Post-campaign report | Analytics | [ ] |
