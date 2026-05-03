"""
Orchestrator — Claude tool-use loop.

Claude receives a goal, reasons about it, calls skills as tools,
and loops until done. Maintains conversation history for chat mode.
"""
import json
import logging
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from skills.base import BaseSkill

logger = logging.getLogger(__name__)

CRITERIA_FILE = Path(__file__).parent.parent / "criteria.json"


def _build_system_prompt() -> str:
    try:
        with open(CRITERIA_FILE) as f:
            criteria = json.load(f)
        job_titles = criteria.get("job_titles", [])
        titles_str = ", ".join(f'"{t}"' for t in job_titles)
    except Exception:
        titles_str = "(could not load criteria.json)"

    return f"""You are a LinkedIn outreach agent that manages connection campaigns.

## Target roles
These are the roles we're looking for (loaded from criteria.json): {titles_str}

Use these as your guide for deciding if someone is a match. Match by intent and function,
not exact wording — e.g. "VP of Sales" and "Vice President, Sales" both match "VP Sales".
If someone's role is clearly in a different function (engineering, marketing, finance, etc.),
they are not a match.

## Search keywords
When the user specifies an exact keyword, use it as-is.
When the user is vague (e.g. "search sales at X"), pick the most relevant specific title(s)
from the target roles list — this gives LinkedIn a better filter and more precise results.

## When no match is found
Proactively suggest next steps based on the target roles above:
- Alternative title variations worth trying
- Whether the company seems too small for this role
- Whether to mark the company as exhausted

## Tools available
- Check connection status and daily limits
- Load criteria (companies, job titles, daily limit)
- search_people — returns all scraped profiles, YOU decide who matches
- connect_with_person — connect with one specific person
- connect_with_people — bulk search+connect for automated pipeline
- get/mark exhausted companies
- Manage the run schedule
- Export and email reports

## Daily pipeline (when asked to run automatically)
1. get_connection_status — if remaining is 0, stop
2. load_criteria — get companies, job titles, daily limit
3. get_exhausted_companies — skip those
4. For each company × title: connect_with_people(company, title, limit=remaining)
   - If company yields 0 connections across all titles → mark_company_exhausted
   - Stop when remaining reaches 0
5. If any connections were made → export_and_email_report

## Interactive / chat mode
- Use search_people to preview results
- Evaluate titles yourself using the matching rules above
- Use connect_with_person for specific people

Be concise. Report matches clearly, briefly explain non-matches."""


MAX_HISTORY_TURNS = 10  # keep last N user/assistant pairs to avoid context bloat


class Orchestrator:
    def __init__(self, skills: list[BaseSkill], keep_history: bool = False):
        self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        self._skills = skills
        self._keep_history = keep_history
        self._history: list[dict] = []
        self._system_prompt: str | None = None  # cached, rebuilt when criteria.json changes
        # Map tool name → skill
        self._tool_map: dict[str, BaseSkill] = {}
        for skill in skills:
            for name in skill.tool_names:
                self._tool_map[name] = skill

    @property
    def tools(self) -> list[dict]:
        return [tool for skill in self._skills for tool in skill.get_tools()]

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _build_system_prompt()
        return self._system_prompt

    def _trim_history(self, messages: list[dict]) -> list[dict]:
        """Keep only the last MAX_HISTORY_TURNS user/assistant pairs."""
        # Each turn = one user message + one assistant message (may include tool calls)
        # Trim from the front, always keep complete pairs
        if len(messages) <= MAX_HISTORY_TURNS * 2:
            return messages
        return messages[-(MAX_HISTORY_TURNS * 2):]

    async def run(self, goal: str) -> str:
        messages = self._trim_history(self._history) + [{"role": "user", "content": goal}]

        while True:
            response = await self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=self._get_system_prompt(),
                tools=self.tools,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text = "\n".join(
                    b.text for b in response.content if hasattr(b, "text")
                )
                if self._keep_history:
                    self._history = messages
                return text

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                logger.info(f"Tool: {block.name}  args={json.dumps(block.input)[:120]}")
                try:
                    skill = self._tool_map.get(block.name)
                    if not skill:
                        raise ValueError(f"No skill registered for tool '{block.name}'")
                    result = await skill.handle(block.name, block.input)
                    content = json.dumps(result) if not isinstance(result, str) else result
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    })
                except Exception as exc:
                    logger.error(f"Tool '{block.name}' failed: {exc}", exc_info=True)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

        return "Done."

    async def cleanup(self) -> None:
        for skill in self._skills:
            await skill.cleanup()

    def reset_history(self) -> None:
        self._history = []

    def invalidate_prompt_cache(self) -> None:
        """Call this after editing criteria.json to pick up new titles."""
        self._system_prompt = None
