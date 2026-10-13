"""The LLM code paths (tool-call routing, structured extraction, grounded generation),
exercised with a scripted fake chat model so the tests need no API key."""
from langchain_core.messages import AIMessage

from workflow_agent.engine import WorkflowAgent
from workflow_agent.router import SelectWorkflow


class FakeLLM:
    def __init__(self, route_to="WF004", text="A cosy jacket made from 100% polyester.", fail=False):
        self.route_to, self.text, self.fail, self.calls = route_to, text, fail, []

    def with_structured_output(self, schema):
        llm = self

        class _Bound:
            def invoke(self, messages):
                llm.calls.append(schema.__name__)
                if llm.fail:
                    raise RuntimeError("provider down")
                if schema is SelectWorkflow:
                    return SelectWorkflow(workflow_id=llm.route_to, confidence=0.9, reasoning="fake")
                return schema()  # all-None extraction / empty structures

        return _Bound()

    def invoke(self, messages):
        self.calls.append("text")
        if self.fail:
            raise RuntimeError("provider down")
        return AIMessage(content=self.text)


def test_llm_routes_with_tool_call_and_grounding_guard(settings):
    fake = FakeLLM()
    agent = WorkflowAgent(settings=settings, llm=fake)
    s = agent.run("please write copy for the jacket we discussed")
    assert s["route"]["method"] == "llm-tool-call" and s["workflow_id"] == "WF004"
    assert "SelectWorkflow" in fake.calls
    desc = next(x for x in s["result"]["sections"] if x["heading"] == "Content")["fields"]["Product description"]
    assert "polyester" not in desc.lower()  # invented material rejected, template used instead
    assert any("unsupported material" in n for n in s["notes"])


def test_llm_failure_falls_back_to_offline_rules(settings):
    agent = WorkflowAgent(settings=settings, llm=FakeLLM(fail=True))
    s = agent.run("Which products need restocking?")
    assert s["workflow_id"] == "WF001" and s["status"] == "completed"
    assert "keyword fallback" in s["route"]["reasoning"]
