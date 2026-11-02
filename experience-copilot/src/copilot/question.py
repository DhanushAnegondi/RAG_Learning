"""Choose answer shape without turning an unsupported premise into experience."""
import re


def intent(question: str) -> str:
    q = question.casefold()
    if re.search(r"(?:a|the) time|time when|time you|manage(?:d)? (?:a|the) team|tools.*(?:resolve|fix|debug|recover|handle)", q):
        return "experience"
    if re.search(r"tech(?:nology|nical)?\s+stack|\btools\b|\btechnologies\b|\bframeworks\b|programming languages", q):
        return "stack"
    if re.search(r"tell me about yourself|introduce yourself|your background|my background|about myself|professional background|walk me through (?:your|my) (?:resume|career)|what strengths|bring to .*role", q):
        return "introduction"
    if re.search(r"(?:a|the) time|time when|time you|experience|what (?:did|have) (?:i|you)|responsibilit|accomplish|achievement|(?:challenging|difficult) project|manage(?:d)? (?:a|the) team", q):
        return "experience"
    return "direct"


def guidance(question: str) -> str:
    mode = intent(question)
    if mode == "stack":
        return ("The user asks for a TECH STACK. Lead with a compact list of documented technology names, "
                "using 4-6 category bullets such as languages, orchestration, data platforms, cloud and development tools. "
                "Cite each group. Do not substitute a project or responsibilities narrative. Do not list a "
                "technology just because it is typical for the role. If the user explicitly asks for uses too, "
                "add brief supported uses after the list; otherwise list names only. This list format overrides paragraph/length style.")
    if mode == "introduction":
        return ("The user asks for a PROFESSIONAL INTRODUCTION. Synthesize the documented experience into a "
                "natural first-person overview: work focus, two or three relevant contributions and strengths. "
                "Do not demand precise titles, dates, role at every employer or a career goal to answer. "
                "Avoid inventing chronology, years of experience, current employment or aspirations. "
                "When the evidence spans several experience areas, summarize at least two relevant areas; "
                "do not turn the whole introduction into one employer's story unless the user asks for that. "
                "Use employer names and relationships only as documented; a folder label is not a job title. "
                "Use a concise spoken paragraph with citations.")
    if mode == "experience":
        return ("The user asks about EXPERIENCE or a BEHAVIORAL STORY. Select one relevant documented episode; "
                "explain the situation/task briefly, personal actions, and supported results. Do not force an "
                "unmeasured metric into the result. Keep ownership faithful: collaboration, coordinating work, "
                "reporting and managing direct reports are different. For a request about team management, "
                "require an actual leadership episode; do not promote a technical project into team management. "
                "Include the tools used if the question asks for them, without replacing the story with a list. "
                "If the needed episode is missing, ask one focused question for those details, not for every role.")
    return "Answer the precise question directly first, then add only useful supporting detail."


def search_question(question: str) -> str:
    if intent(question) == "stack":
        return question + " stack tools technologies languages frameworks databases cloud orchestration"
    if intent(question) == "introduction":
        return "data engineering contributions experience interview safe claims personal actions"
    return question


def names_only_stack(question: str) -> bool:
    return intent(question)=='stack' and not re.search(
        r'what.*(?:use.*for|used.*for)|how|explain|describe|\bnot\b|\bnever\b|\bshould\b|\brecommend',question,re.I)
