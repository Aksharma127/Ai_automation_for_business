**User Request:** Classify these keywords and map them to pages.

**Selected Workflow:** WF008 · SEO Keyword Classification
**Routing:** keyword · confidence 0.994 · matched terms ['classify', 'keyword', 'map', 'them', 'pag'] (evidence 31.17, runner-up 0)
**Mode:** offline (deterministic rules and templates)
**Inputs:** keyword_file=data/sample/keywords.csv

**Steps Executed:**
1. ✓ Read keywords — `load_table` → read 15 keywords (1.4 ms)
2. ✓ remove duplicates — `dedupe_rows` → 14 unique, Buy Running Shoes Online duplicate(s) removed (0.1 ms)
3. ✓ classify search intent — `classify_intent` → 14 record(s) (1.6 ms)
4. ✓ map keywords to categories — `map_categories` → 14 record(s) (0.3 ms)
5. ✓ identify high-priority keywords — `rank_rows` → scored and ranked 14 keywords (0.7 ms)
6. ✓ export results — `export_table` → outputs/files/keyword_report.csv (0.4 ms)

**Status:** Completed

**Result:**

**SEO keyword report**

14 unique keywords classified (1 duplicate(s) removed); 4 are high priority. Full report: outputs/files/keyword_report.csv.

*Keywords by priority*

| rank | keyword | monthly_searches | intent | category | priority | target_page |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | puffer jacket sale | 6600 | transactional | Outerwear | High | /collections/outerwear |
| 2 | best running shoes for flat feet | 8100 | commercial | Footwear | High | /guides/best-footwear |
| 3 | buy running shoes online | 5400 | transactional | Footwear | High | /collections/footwear |
| 4 | cotton t-shirt price | 2900 | transactional | Apparel | High | /collections/apparel |
| 5 | what is merino wool | 4400 | informational | Materials | Medium | /blog/materials-guide |
| 6 | top 10 canvas tote bags | 1900 | commercial | Accessories | Medium | /guides/best-accessories |
| 7 | denim jeans vs chinos | 1600 | commercial | Apparel | Medium | /guides/best-apparel |
| 8 | water bottle 750ml cheap | 880 | transactional | Accessories | Medium | /collections/accessories |
| 9 | merino scarf discount code | 720 | transactional | Accessories | Low | /collections/accessories |
| 10 | acme apparel | 2400 | navigational | General | Low | / (homepage / account) |
| 11 | how to wash wool beanie | 1300 | informational | Accessories | Low | /blog/accessories-guide |
| 12 | leather belt sizing guide | 1000 | informational | Accessories | Low | /blog/accessories-guide |
| 13 | order corduroy overshirt | 260 | transactional | Apparel | Low | /collections/apparel |
| 14 | acme store login | 900 | navigational | General | Low | / (homepage / account) |
