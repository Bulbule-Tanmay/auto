"""Cheap keyword pre-filter so only plausible posts reach the AI (saves free quota)."""
import re

from .models import Post

INTENT = re.compile(
    r"\b(looking for|need(ed)?|want(ed)? to hire|hire|hiring|recommend|recommendation|suggest|"
    r"anyone know|can anyone|does anyone|who can|help (me )?with|budget|quote|quotation|agency|"
    r"freelancer|developer|expert|consultant|specialist|outsourc|setup|set up|build(ing)? (a|my)|"
    r"chahiye|chahie|koi hai|koi batao|batao|suggest karo|karwana|banwana|banana hai|"
    r"koi acha|koi achha|dhundh|dhoondh)\b",
    re.I,
)

NEGATIVE = re.compile(
    r"(\[for hire\]|\bfor hire\b|\bhire me\b|\bi am (a |an )?(freelance|developer|designer|marketer)|"
    r"\bi'm (a |an )?(freelance|developer|designer|marketer)|\bavailable for (work|hire|projects)|"
    r"\bmy services\b|\bi offer\b|\bwe offer\b|\bdm me for\b)",
    re.I,
)

# These sources are already request-shaped, so skip the keyword check
TRUSTED_SOURCES = {"beatapi", "search"}


def plausible(p: Post) -> bool:
    blob = f"{p.title}\n{p.text[:1500]}"
    if NEGATIVE.search(p.title):
        return False
    if p.source in TRUSTED_SOURCES:
        return True
    return bool(INTENT.search(blob))
