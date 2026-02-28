import re
from collections.abc import Callable
from pathlib import Path

from claude_code_sdk import (
    query,
    ClaudeCodeOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


async def run_research_agent(
    topic: str,
    additional_instructions: str = "",
    max_turns: int = 50,
    on_progress: Callable[[str, str], None] | None = None,
) -> str:
    """Run the research agent and return the final Markdown report.

    Args:
        topic: The research topic.
        additional_instructions: Extra user instructions appended to the prompt.
        max_turns: Max agent iterations.
        on_progress: Optional callback(message, type) for live progress updates.
            type is one of: "search", "fetch", "phase", "status"
    """
    system_prompt = _load_prompt("system_prompt.txt")
    task_template = _load_prompt("task_template.txt")

    # Build task prompt
    extra = ""
    if additional_instructions.strip():
        extra = f"**Additional Instructions:** {additional_instructions.strip()}"
    task_prompt = task_template.replace("{topic}", topic).replace(
        "{additional_instructions}", extra
    )

    options = ClaudeCodeOptions(
        system_prompt=system_prompt,
        allowed_tools=["WebSearch", "WebFetch"],
        permission_mode="acceptEdits",
        max_turns=max_turns,
    )

    def _emit(message: str, msg_type: str = "status") -> None:
        if on_progress:
            on_progress(message, msg_type)

    _emit("Agent initialized, starting research...", "phase")

    # Collect text per-message so we can reconstruct the report properly.
    # The agent sends multiple AssistantMessages:
    #   - During research: short text + ToolUseBlocks
    #   - Writing phase: one or more messages with the full report text
    # We group TextBlocks by message to preserve report continuity.
    message_texts: list[str] = []  # concatenated text per AssistantMessage
    result_text: str = ""
    search_count = 0
    fetch_count = 0

    async for message in query(prompt=task_prompt, options=options):
        if isinstance(message, AssistantMessage):
            msg_text_parts: list[str] = []
            for block in message.content:
                if isinstance(block, TextBlock):
                    msg_text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_name = block.name
                    tool_input = block.input or {}
                    if tool_name == "WebSearch":
                        search_count += 1
                        q = tool_input.get("query", "")
                        _emit(f"[{search_count}] Searching: {q}", "search")
                    elif tool_name == "WebFetch":
                        fetch_count += 1
                        url = tool_input.get("url", "")
                        _emit(f"[{fetch_count}] Reading: {url}", "fetch")
            # Join all text blocks from this single message
            if msg_text_parts:
                message_texts.append("\n".join(msg_text_parts))

        elif isinstance(message, ResultMessage):
            if hasattr(message, "result") and message.result:
                result_text = message.result

    _emit(f"Research done — {search_count} searches, {fetch_count} pages fetched", "phase")

    # Diagnostic: show sizes of collected data
    total_chars = sum(len(t) for t in message_texts)
    result_chars = len(result_text)
    _emit(
        f"Collected {len(message_texts)} message(s), "
        f"{total_chars:,} chars in messages, {result_chars:,} chars in result",
        "phase",
    )
    # Show per-message sizes for debugging (top 5 largest)
    if message_texts:
        sizes = sorted(
            [(i, len(t)) for i, t in enumerate(message_texts)],
            key=lambda x: x[1],
            reverse=True,
        )
        top = sizes[:5]
        size_info = ", ".join(f"msg[{i}]={sz:,}ch" for i, sz in top)
        _emit(f"Largest messages: {size_info}", "phase")

    report = _extract_report(result_text, message_texts)

    if not report.strip():
        raise RuntimeError(
            "Agent returned no report content. "
            f"Completed {search_count} searches and {fetch_count} fetches. "
            "Try increasing max turns or simplifying the topic."
        )

    _emit(f"Extracted report: {len(report):,} chars, generating PDF...", "phase")
    return report


def _is_report_text(text: str, min_length: int = 1000) -> bool:
    """Check if a text looks like the actual Markdown report (not intermediate reasoning)."""
    # Must have a top-level heading (# Something)
    has_h1 = bool(re.search(r"^# .+", text, re.MULTILINE))
    # Must have at least one ## subheading
    has_h2 = bool(re.search(r"^## .+", text, re.MULTILINE))
    # Must be substantial
    is_long = len(text) > min_length
    return has_h1 and has_h2 and is_long


def _has_report_heading(text: str) -> bool:
    """Check if a text starts with or contains a report-style H1 heading."""
    return bool(re.search(
        r"^# .+(?:Market|Research|Brief|Report|Analysis|Overview|Executive)",
        text,
        re.MULTILINE | re.IGNORECASE,
    ))


def _extract_report(result_text: str, message_texts: list[str]) -> str:
    """Extract the final Markdown report from agent output.

    The agent sends many messages: short intermediate reasoning during research,
    then writes the full report (possibly split across a few messages at the end).
    We need to find and reconstruct the complete report.
    """
    # Strategy 1: Check if ResultMessage IS the report
    if result_text and _is_report_text(result_text):
        return result_text.strip()

    # Strategy 2: Look through per-message texts for the report.
    # The report should be in the last few messages. Check from the end.
    # A single message might contain the entire report.
    for msg_text in reversed(message_texts):
        if _is_report_text(msg_text):
            return msg_text.strip()

    # Strategy 3: The report might span multiple consecutive messages at the end.
    # Concatenate the last N messages and check if that forms a report.
    # (e.g., the agent wrote the first half in one message and continued in the next)
    for n in range(2, min(8, len(message_texts) + 1)):
        combined = "\n\n".join(message_texts[-n:])
        if _is_report_text(combined):
            return combined.strip()

    # Strategy 4: Concatenate ALL message texts and extract from the first # heading.
    # This handles the case where report content is mixed with reasoning.
    full_text = "\n\n".join(message_texts)
    if result_text:
        full_text += "\n\n" + result_text

    # Find where the report starts — look for a report-style heading first
    match = re.search(
        r"^(# .+(?:Market|Research|Brief|Report|Analysis|Overview|Executive))",
        full_text,
        re.MULTILINE | re.IGNORECASE,
    )
    if not match:
        # Fallback to any H1 heading
        match = re.search(r"^(# .+)", full_text, re.MULTILINE)

    if match:
        report_portion = full_text[match.start():].strip()
        if len(report_portion) > 300:
            return report_portion

    # Strategy 5: ResultMessage + last few messages combined — the result
    # might be a partial report that can be combined with earlier messages.
    if result_text and len(result_text) > 200:
        for n in range(1, min(5, len(message_texts) + 1)):
            combined = "\n\n".join(message_texts[-n:]) + "\n\n" + result_text
            if _is_report_text(combined, min_length=500):
                return combined.strip()

    # Strategy 6: Lower the bar — accept shorter content with report structure.
    # The agent may have been cut off mid-report.
    for msg_text in reversed(message_texts):
        if _is_report_text(msg_text, min_length=500):
            return msg_text.strip()

    for n in range(2, min(8, len(message_texts) + 1)):
        combined = "\n\n".join(message_texts[-n:])
        if _is_report_text(combined, min_length=500):
            return combined.strip()

    # Strategy 7: Last resort — return everything we got.
    # Better a messy report than no report.
    if full_text.strip():
        return full_text.strip()

    return result_text
