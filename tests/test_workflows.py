"""End-to-end behaviour of each workflow, including its decision logic and error handling."""


def rows(state, heading):
    sec = next(s for s in state["result"]["sections"] if s["heading"].startswith(heading))
    return sec.get("table") or sec.get("items") or sec.get("fields")


def test_wf001_restock_threshold_logic(agent):
    s = agent.run("Which products need restocking?")
    assert s["status"] == "completed" and len(s["trace"]) == 5
    got = {r["sku"]: r["suggested_reorder_qty"] for r in rows(s, "Restock list")}
    assert got == {"SKU-1005": 30, "SKU-1007": 35, "SKU-1003": 42, "SKU-1001": 68, "SKU-1009": 21}
    s2 = agent.run("Which products need restocking? Flag anything below 25 units")
    assert s2["inputs"]["threshold_override"] == 25
    assert "SKU-1006" in {r["sku"] for r in rows(s2, "Restock list")}  # 22 < 25 now


def test_wf002_flags_over_tolerance(agent):
    s = agent.run("Find products where vendor price differs by more than 10%.")
    assert {r["sku"] for r in rows(s, "Exceptions")} == {"SKU-1002", "SKU-1004", "SKU-1006", "SKU-1009"}
    assert {r["sku"] for r in rows(s, "Products with no vendor price")} == {"SKU-1008", "SKU-1011", "SKU-1012", "SKU-1013"}


def test_wf003_invalid_rows_and_cleaned_file(agent, settings):
    s = agent.run("Process this vendor spreadsheet and show invalid rows.")
    invalid = rows(s, "Invalid rows")
    assert {r["errors"] for r in invalid} == {"missing sku", "missing product_name"}
    assert (settings.output_dir / "files" / "vendor_clean.csv").exists()
    clean = rows(s, "Cleaned dataset")
    assert all(r["sku"] == r["sku"].strip().upper() for r in clean)


def test_wf004_never_invents_missing_attributes(agent):
    s = agent.run("Generate SEO content for this product.")
    assert s["status"] == "completed"
    assert rows(s, "Missing information") == ["material"]
    content = " ".join(rows(s, "Content").values()).lower()
    assert "made from" not in content and "polyester" not in content
    assert len(rows(s, "Content")["SEO title"]) <= 60
    assert len(rows(s, "Content")["Meta description"]) <= 160


def test_wf004_asks_when_required_fields_missing(agent, tmp_path):
    s = agent.run("Write product content for Linen Shirt")  # name given, category unknown
    assert s["status"] == "needs_input" and "category" in s["answer"]


def test_wf005_order_found_with_retry(agent):
    s = agent.run("Where is order ORD-1001?")
    assert s["status"] == "completed"
    ship = next(t for t in s["trace"] if t["tool"] == "shipment_lookup")
    assert ship["attempts"] == 2  # simulated carrier API fails once, then succeeds


def test_wf005_missing_order_asks_for_another_identifier(agent):
    s = agent.run("Where is order ORD-9999?")
    assert s["status"] == "needs_input" and "another identifier" in s["answer"]


def test_wf005_carrier_outage_degrades_gracefully(agent):
    s = agent.run("Track my order ORD-1004")
    assert s["status"] == "completed"
    assert any(t["status"] == "degraded" for t in s["trace"])
    assert "unavailable" in rows(s, "Orders")[0]["shipment"]


def test_wf006_confidence_levels(agent):
    s = agent.run("Find likely duplicate products in the catalog.")
    groups = rows(s, "Duplicate groups")
    assert [g["confidence"] for g in groups].count("Definite duplicate") == 2
    assert any("SKU-3103" in g["products"] for g in groups if g["confidence"].startswith("Possible"))


def test_wf007_requires_goal_and_dates(agent):
    s = agent.run("Create a campaign brief for the new collection.")
    assert s["status"] == "needs_input"
    assert s["trace"][0]["status"] == "needs_input" and len(s["trace"]) == 1


def test_wf007_full_brief(agent):
    s = agent.run("Create a campaign brief for the new collection to drive online sales with 20% off, "
                  "from 2026-11-01 to 2026-11-30.")
    assert s["status"] == "completed"
    assert rows(s, "Overview")["Objective"] == "sales"
    assert len(rows(s, "Campaign checklist")) == 9


def test_wf007_rejects_reversed_dates(agent):
    s = agent.run("Create a campaign brief to drive online sales from 2026-12-01 to 2026-11-01.")
    assert s["status"] == "needs_input" and "before the start date" in s["answer"]


def test_wf008_intents_and_dedupe(agent):
    s = agent.run("Classify these keywords and map them to pages.")
    table = rows(s, "Keywords by priority")
    assert len(table) == 14
    intent = {r["keyword"]: r["intent"] for r in table}
    assert intent["buy running shoes online"] == "transactional"
    assert intent["best running shoes for flat feet"] == "commercial"
    assert intent["how to wash wool beanie"] == "informational"
    assert intent["acme store login"] == "navigational"


def test_wf009_picks_skilled_available_developer(agent):
    s = agent.run("Assign this urgent task to the best available developer.")
    assert rows(s, "Assignment")["Recommended employee"] == "Priya Nair"  # Emma matches too but is unavailable


def test_wf009_escalates_when_nobody_fits(agent):
    s = agent.run("Assign an urgent task to a developer - task: migrate the cluster to Kubernetes with Terraform")
    assert s["status"] == "escalated"


def test_wf010_flags_failure_rate_and_slowness(agent):
    s = agent.run("Which workflows are failing most often?")
    flagged = {r["workflow_id"] for r in rows(s, "Flagged workflows")}
    assert {"WF003", "WF005"} <= flagged
    ranked = rows(s, "All workflows")
    assert ranked[0]["failure_rate"] >= ranked[-1]["failure_rate"]


def test_missing_file_fails_cleanly(agent):
    s = agent.run("Which products need restocking in data/sample/nope_inventory.csv?")
    assert s["status"] == "failed" and "file not found" in s["answer"]


def test_run_log_feeds_wf010(agent, settings):
    agent.run("Which products need restocking?")
    s = agent.run(f"Which workflows are failing most often? use {settings.run_log}")
    assert s["status"] == "completed"
