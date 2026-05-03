from abc import ABC, abstractmethod


class BaseSkill(ABC):

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """Return Anthropic tool definitions this skill exposes."""
        ...

    @property
    def tool_names(self) -> set[str]:
        return {t["name"] for t in self.get_tools()}

    @abstractmethod
    async def handle(self, tool_name: str, inputs: dict):
        """Execute the named tool with given inputs and return a result."""
        ...

    async def cleanup(self) -> None:
        """Optional teardown (e.g. close browser). Called after each run."""
        pass
