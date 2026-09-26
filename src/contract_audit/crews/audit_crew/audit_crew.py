import os

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from contract_audit.llm import get_llm
from contract_audit.models import ContractTerms, InvoiceData
from contract_audit.tools.document_tools import (
    DiscrepancyCheckTool,
    PdfTextExtractTool,
)


@CrewBase
class ContractInvoiceAuditCrew:
    """Contract vs. Invoice Discrepancy Audit Crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def contract_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["contract_analyst"],  # type: ignore[index]
            tools=[PdfTextExtractTool()],
            llm=get_llm(),
        )

    @agent
    def invoice_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["invoice_analyst"],  # type: ignore[index]
            tools=[PdfTextExtractTool()],
            llm=get_llm(),
        )

    @agent
    def discrepancy_auditor(self) -> Agent:
        return Agent(
            config=self.agents_config["discrepancy_auditor"],  # type: ignore[index]
            tools=[DiscrepancyCheckTool()],
            llm=get_llm(),
        )

    @agent
    def audit_report_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["audit_report_writer"],  # type: ignore[index]
            llm=get_llm(),
        )

    @task
    def extract_contract_task(self) -> Task:
        # output_pydantic forces the extraction into the same shape the
        # comparison tool validates, so a sloppy extraction fails here rather
        # than quietly producing an empty audit.
        return Task(
            config=self.tasks_config["extract_contract_task"],  # type: ignore[index]
            output_pydantic=ContractTerms,
            output_file="output/contract_terms.json",
        )

    @task
    def extract_invoice_task(self) -> Task:
        return Task(
            config=self.tasks_config["extract_invoice_task"],  # type: ignore[index]
            output_pydantic=InvoiceData,
            output_file="output/invoice_data.json",
        )

    @task
    def audit_discrepancies_task(self) -> Task:
        return Task(
            config=self.tasks_config["audit_discrepancies_task"],  # type: ignore[index]
            context=[self.extract_contract_task(), self.extract_invoice_task()],
            output_file="output/audit_findings.md",
        )

    @task
    def write_discrepancy_report_task(self) -> Task:
        return Task(
            config=self.tasks_config["write_discrepancy_report_task"],  # type: ignore[index]
            context=[
                self.extract_contract_task(),
                self.extract_invoice_task(),
                self.audit_discrepancies_task(),
            ],
            output_file="output/discrepancy_report.md",
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Contract vs. Invoice Discrepancy Audit Crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            # Throttled for Groq's free tier: its limit is tokens per minute,
            # and these prompts carry whole documents, so spacing the calls out
            # keeps the crew under the ceiling. Raise or remove MAX_RPM on a
            # paid tier.
            max_rpm=int(os.environ.get("MAX_RPM", "2")),
        )
