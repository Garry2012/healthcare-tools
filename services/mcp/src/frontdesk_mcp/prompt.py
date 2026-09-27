"""The server instructions the LLM reads: core rules + the domain's words + the rollout's values.

The core rules hold for every domain (how to branch on outcomes, never inventing, never saying
"no one is available", passing the caller's words untranslated); a domain pack adds only what
is its own (who is booked, what an emergency is), and the rollout supplies its languages and,
optionally, the provider's name. No domain file repeats a core sentence (tests enforce it).
"""

from __future__ import annotations

from .packs import Pack

CORE_RULES = (
    "Call find_availability once per caller question with the caller's own words; branch on `outcome` "
    "and `routing.action`.",
    "Book with manage_booking(action=BOOK) using a slotId from that result.",
    "Never invent ids, dates, times or prices; never say 'confirmed' unless timingCertainty is CONFIRMED.",
    "For general questions (hours, parking, directions) call search_knowledge and speak only its approved "
    "answer.",
    "routing.action NO_SERVICE means the words were not understood or the service is not offered: ask the "
    "caller to rephrase once, otherwise transfer to the desk; never say that no one is available.",
    "COULD_NOT_CHECK or COULD_NOT_RECORD means a system problem: say so and transfer.",
)

LANGUAGES = (
    "Languages: set `language` to the language the caller is speaking ({codes}). Pass the caller's own "
    "words, untranslated, in their script, romanised, or a mix of languages; put when they want to come in "
    "when.expression exactly as said, never as a calendar date you worked out. Speak approved answers in "
    "the language they come back in; never translate or paraphrase them."
)


def instructions(pack: Pack, languages: tuple[str, ...], display_name: str = "") -> str:
    at = f" at {display_name}" if display_name else ""
    rules = (*CORE_RULES[:3], pack.instructions, *CORE_RULES[3:])
    return " ".join((f"Front-desk tools for {pack.role}{at}.", *rules, LANGUAGES.format(codes=", ".join(languages))))
