from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from support_insights.tools.custom_tool import (
    SupportTicketFetchTool,
    SupportTicketStatsTool,
)


@CrewBase
class SupportCrew:
    """Customer Support Insights Crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def data_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["data_analyst"],  # type: ignore[index]
            tools=[SupportTicketFetchTool(), SupportTicketStatsTool()],
        )

    @agent
    def problem_pattern_finder(self) -> Agent:
        return Agent(
            config=self.agents_config["problem_pattern_finder"],  # type: ignore[index]
        )

    @agent
    def recommendations_strategist(self) -> Agent:
        return Agent(
            config=self.agents_config["recommendations_strategist"],  # type: ignore[index]
        )

    @agent
    def coo_report_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["coo_report_writer"],  # type: ignore[index]
        )

    @task
    def fetch_and_analyze_task(self) -> Task:
        return Task(
            config=self.tasks_config["fetch_and_analyze_task"],  # type: ignore[index]
        )

    @task
    def identify_patterns_task(self) -> Task:
        return Task(
            config=self.tasks_config["identify_patterns_task"],  # type: ignore[index]
            context=[self.fetch_and_analyze_task()],
        )

    @task
    def recommend_actions_task(self) -> Task:
        return Task(
            config=self.tasks_config["recommend_actions_task"],  # type: ignore[index]
            context=[self.fetch_and_analyze_task(), self.identify_patterns_task()],
        )

    @task
    def compile_coo_report_task(self) -> Task:
        return Task(
            config=self.tasks_config["compile_coo_report_task"],  # type: ignore[index]
            context=[
                self.fetch_and_analyze_task(),
                self.identify_patterns_task(),
                self.recommend_actions_task(),
            ],
            output_file="output/coo_report.md",
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Customer Support Insights Crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
