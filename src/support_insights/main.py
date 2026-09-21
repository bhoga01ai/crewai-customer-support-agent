#!/usr/bin/env python
from pathlib import Path

from pydantic import BaseModel

from crewai.flow import Flow, listen, start

from support_insights.crews.support_crew.support_crew import SupportCrew


class SupportInsightsState(BaseModel):
    focus_area: str = ""
    report: str = ""


class SupportInsightsFlow(Flow[SupportInsightsState]):

    @start()
    def set_focus_area(self, crewai_trigger_payload: dict = None):
        print("Setting focus area for the support insights analysis")

        if crewai_trigger_payload:
            self.state.focus_area = crewai_trigger_payload.get("focus_area", "all tickets")
            print(f"Using trigger payload: {crewai_trigger_payload}")
        else:
            self.state.focus_area = self.state.focus_area or "all tickets"

        print(f"Focus area: {self.state.focus_area}")

    @listen(set_focus_area)
    def generate_insights(self):
        print(f"Running support insights crew for focus area: {self.state.focus_area}")
        result = (
            SupportCrew()
            .crew()
            .kickoff(inputs={"focus_area": self.state.focus_area})
        )

        print("Report generated")
        self.state.report = result.raw

    @listen(generate_insights)
    def save_report(self):
        print("Saving report")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        with open(output_dir / "coo_report.md", "w") as f:
            f.write(self.state.report)
        print("Report saved to output/coo_report.md")


def kickoff():
    """
    Run the flow. Reads an optional focus area from the FOCUS_AREA env var
    (or falls back to interactive input), so the user can steer the report —
    e.g. FOCUS_AREA="billing" crewai run — toward a specific ticket category
    or keyword such as billing, technical, account, shipping, refunds, login.
    """
    import os

    focus_area = os.environ.get("FOCUS_AREA", "").strip()
    if not focus_area:
        try:
            focus_area = input(
                "What should the report focus on? "
                "(e.g. 'billing', 'technical', 'all tickets') [all tickets]: "
            ).strip()
        except EOFError:
            focus_area = ""

    flow = SupportInsightsFlow()
    flow.state.focus_area = focus_area or "all tickets"
    flow.kickoff()


def plot():
    support_insights_flow = SupportInsightsFlow()
    support_insights_flow.plot()


def run_with_trigger():
    """
    Run the flow with trigger payload, e.g.:
    uv run run_with_trigger '{"focus_area": "billing"}'
    """
    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    support_insights_flow = SupportInsightsFlow()

    try:
        result = support_insights_flow.kickoff({"crewai_trigger_payload": trigger_payload})
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the flow with trigger: {e}")


if __name__ == "__main__":
    kickoff()
