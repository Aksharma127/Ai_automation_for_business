**User Request:** Which workflows are failing most often?

**Selected Workflow:** WF010 · Workflow Performance Report
**Routing:** keyword · confidence 0.982 · matched terms ['workflow', 'fail', 'most', 'often'] (evidence 23.98, runner-up 0)
**Mode:** offline (deterministic rules and templates)
**Inputs:** log_file=data/sample/execution_logs.csv; max_failure_rate=0.1; max_avg_duration_sec=30

**Steps Executed:**
1. ✓ Load execution logs — `load_table` → loaded 1972 step log rows (17.3 ms)
2. ✓ calculate success/failure rate — `run_outcomes` → success/failure rates for 7 workflows (1.1 ms)
3. ✓ calculate average execution time — `run_durations` → 7 record(s) (1.3 ms)
4. ✓ identify frequent errors — `frequent_errors` → top 6 error patterns (0.2 ms)
5. ✓ identify slow steps — `slow_steps` → 5 slowest steps (1.8 ms)
6. ✓ generate recommendations — `performance_recommendations` → 5 workflow(s) flagged, 9 recommendation(s) (0.3 ms)

**Status:** Completed

**Result:**

**Workflow performance report**

Analysed 373 runs of 7 workflows. 5 workflow(s) breach the thresholds (failure rate above 10% or average run time above 30s).

*Flagged workflows*

| workflow_id | workflow_name | runs | failure_rate | avg_duration_sec | flag_reasons |
| --- | --- | --- | --- | --- | --- |
| WF003 | Vendor File Processing | 58 | 0.15 | 30.83 | failure rate 15.5% > 10%; avg time 30.83s > 30s |
| WF005 | Customer Order Status | 52 | 0.15 | 9.1 | failure rate 15.4% > 10% |
| WF008 | SEO Keyword Classification | 53 | 0.09 | 38.22 | avg time 38.22s > 30s |
| WF006 | Duplicate Product Detection | 48 | 0.06 | 58.09 | avg time 58.09s > 30s |
| WF004 | Product Description Generator | 55 | 0.02 | 57.34 | avg time 57.34s > 30s |

*All workflows (most failures first)*

| workflow_id | workflow_name | runs | failed_runs | success_rate | failure_rate | avg_duration_sec |
| --- | --- | --- | --- | --- | --- | --- |
| WF003 | Vendor File Processing | 58 | 9 | 0.84 | 0.15 | 30.83 |
| WF005 | Customer Order Status | 52 | 8 | 0.85 | 0.15 | 9.1 |
| WF008 | SEO Keyword Classification | 53 | 5 | 0.91 | 0.09 | 38.22 |
| WF006 | Duplicate Product Detection | 48 | 3 | 0.94 | 0.06 | 58.09 |
| WF002 | Product Price Validation | 52 | 2 | 0.96 | 0.04 | 6.08 |
| WF004 | Product Description Generator | 55 | 1 | 0.98 | 0.02 | 57.34 |
| WF001 | Inventory Restock Check | 55 | 1 | 0.98 | 0.02 | 4.05 |

*Most frequent errors*

| workflow_id | step | error | occurrences |
| --- | --- | --- | --- |
| WF005 | Retrieve shipment | TimeoutError: shipment API did not respond in 10s | 6 |
| WF005 | Retrieve shipment | NotFound: order id not found | 2 |
| WF008 | Classify intent | RuntimeError: unexpected failure | 2 |
| WF008 | Export | RuntimeError: unexpected failure | 2 |
| WF001 | Compare stock | RuntimeError: unexpected failure | 1 |
| WF003 | Validate fields | ParseError: unsupported encoding | 1 |

*Slowest steps*

| workflow_id | step | avg_sec | samples |
| --- | --- | --- | --- |
| WF004 | Create description | 26.63 | 55 |
| WF006 | Compare attributes | 23.97 | 47 |
| WF008 | Classify intent | 15.51 | 52 |
| WF003 | Validate fields | 12.39 | 53 |
| WF004 | Meta description | 8.1 | 54 |

*Recommendations*

- WF003 Vendor File Processing: 'ParseError: unsupported encoding' at step 'Validate fields' (1x) - detect encoding/format before parsing and support the failing format explicitly.
- WF003 Vendor File Processing: step 'Validate fields' averages 12.39s - parallelise or cache this step, or move it to a background job.
- WF004 Product Description Generator: step 'Create description' averages 26.63s - parallelise or cache this step, or move it to a background job.
- WF005 Customer Order Status: 'TimeoutError: shipment API did not respond in 10s' at step 'Retrieve shipment' (6x) - add retries with exponential backoff and a circuit breaker around the external API; cache recent responses.
- WF005 Customer Order Status: 'NotFound: order id not found' at step 'Retrieve shipment' (2x) - treat 'not found' as a user-facing outcome (ask for another identifier) rather than a failure.
- WF006 Duplicate Product Detection: step 'Compare attributes' averages 23.97s - parallelise or cache this step, or move it to a background job.
- WF008 SEO Keyword Classification: 'RuntimeError: unexpected failure' at step 'Classify intent' (2x) - investigate the root cause and add a regression test.
- WF008 SEO Keyword Classification: 'RuntimeError: unexpected failure' at step 'Export' (2x) - investigate the root cause and add a regression test.
- WF008 SEO Keyword Classification: step 'Classify intent' averages 15.51s - parallelise or cache this step, or move it to a background job.
