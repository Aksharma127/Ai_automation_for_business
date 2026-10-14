"""The Excel file drives the registry; an 11th workflow needs only data, not code."""
import shutil

import yaml
from openpyxl import load_workbook

from conftest import ROOT
from workflow_agent.engine import WorkflowAgent
from workflow_agent.registry import load_registry
from workflow_agent.settings import Settings

WF011_ROW = ["WF011", "Low Margin Alert", "User asks which products have a low margin",
             "Product CSV; vendor price list; minimum margin",
             "Load prices → match products by SKU → calculate margin → flag low-margin products",
             "Flag when margin is below 30%", "CSV reader; calculator",
             "List of products with margin below the minimum"]

WF011_BINDING = {
    "keywords": ["margin", "low margin", "profitability"],
    "inputs": {"min_margin": {"type": "number", "default": 30, "pattern": r"(\d+)\s*%"}},
    "steps": [
        {"tool": "load_tables", "save_as": "data",
         "args": {"sources": {"p": "data/sample/products.csv", "v": "data/sample/vendor_prices.csv"}}},
        {"tool": "join_tables", "save_as": "joined",
         "args": {"left": "$data.p", "right": "$data.v", "left_on": "sku", "right_on": "vendor_sku"}},
        {"tool": "add_columns", "save_as": "with_margin",
         "args": {"table": "$joined.matched",
                  "columns": {"margin_pct": "round((our_price - vendor_price) * 100 / our_price, 1)"}}},
        {"tool": "filter_rows", "save_as": "low",
         "args": {"table": "$with_margin", "condition": "margin_pct < min_margin",
                  "params": {"min_margin": "$inputs.min_margin"}}},
    ],
    "report": {"title": "Low margin products", "summary": "{n} product(s) below {m}% margin",
               "values": {"n": "$low|count", "m": "$inputs.min_margin"},
               "sections": [{"heading": "Products", "table": "$low", "columns": ["sku", "margin_pct"]}]},
}


def test_all_ten_workflows_load_and_validate(agent):
    reg = agent.registry
    assert [w.id for w in reg.executable()] == [f"WF{i:03d}" for i in range(1, 11)]
    assert reg.warnings == []
    for w in reg.executable():
        assert len(w.steps) == len(w.steps_text) >= 4
        assert w.examples, "Test_Questions sheet should feed the router"


def _copy_sources(tmp_path):
    xlsx = tmp_path / "wf.xlsx"
    shutil.copy(ROOT / "data" / "AI_Agent_Workflow_Assessment.xlsx", xlsx)
    bindings = yaml.safe_load((ROOT / "config" / "workflow_bindings.yaml").read_text(encoding="utf-8"))
    return xlsx, bindings


def test_eleventh_workflow_is_data_only(tmp_path):
    xlsx, bindings = _copy_sources(tmp_path)
    wb = load_workbook(xlsx)
    wb["Workflows"].append(WF011_ROW)
    wb.save(xlsx)
    bindings["WF011"] = WF011_BINDING
    yml = tmp_path / "b.yaml"
    yml.write_text(yaml.safe_dump(bindings, allow_unicode=True), encoding="utf-8")

    settings = Settings(workflow_excel=xlsx, bindings_file=yml, output_dir=tmp_path / "o",
                        database_url=f"sqlite:///{tmp_path / 'a.db'}", checkpoint_url="memory", force_offline=True)
    agent = WorkflowAgent(settings=settings, llm=None)
    assert agent.registry.get("WF011").executable
    state = agent.run("Which products have a low margin under 25%?")
    assert state["workflow_id"] == "WF011"
    assert state["status"] == "completed"
    assert [t["step"] for t in state["trace"]] == WF011_ROW[4].split(" → ")
    assert state["inputs"]["min_margin"] == 25


def test_binding_out_of_sync_with_excel_is_reported(tmp_path):
    xlsx, bindings = _copy_sources(tmp_path)
    bindings["WF001"]["steps"] = bindings["WF001"]["steps"][:-1]
    bindings["WF002"]["steps"][0]["tool"] = "no_such_tool"
    yml = tmp_path / "b.yaml"
    yml.write_text(yaml.safe_dump(bindings, allow_unicode=True), encoding="utf-8")
    reg = load_registry(xlsx, yml)
    assert not reg.get("WF001").executable and not reg.get("WF002").executable
    assert any("Excel lists 5 steps but the binding has 4" in w for w in reg.warnings)
    assert any("unknown tool 'no_such_tool'" in w for w in reg.warnings)
