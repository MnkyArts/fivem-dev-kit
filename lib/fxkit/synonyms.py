"""Search synonym groups (DESIGN.md section 3, "Search behaviour").

Expansion is bidirectional and OR-ed: if any query word matches a group, all
words in that group are searched for (`term1 OR term2 OR ...`).
"""
from __future__ import annotations

GROUPS: list[tuple[str, ...]] = [
    ("vehicle", "car", "veh"),
    ("ped", "player", "character", "npc"),
    ("weapon", "gun"),
    ("coords", "position", "pos", "location"),
    ("teleport", "tp"),
    ("invincible", "godmode", "god"),
    ("health", "hp"),
    ("model", "hash"),
    ("blip", "marker"),
    ("notification", "notify"),
    ("text", "draw"),
    ("freeze", "frozen"),
    ("door", "doors"),
    ("lock", "locked"),
    ("engine", "motor"),
    ("seat",),
    ("cam", "camera"),
    ("anim", "animation"),
    ("task",),
    ("network", "net", "sync"),
    ("entity", "object", "prop"),
    ("plate", "numberplate", "licenseplate"),
    ("color", "colour"),
    ("remove", "delete"),
    ("create", "spawn"),
]

# word -> set of all words (including itself) that share a synonym group.
_INDEX: dict[str, set[str]] = {}
for _group in GROUPS:
    _members = set(_group)
    for _word in _group:
        _INDEX.setdefault(_word, set()).update(_members)


def expand(word: str) -> set[str]:
    """All synonyms for `word` (always includes `word` itself)."""
    w = word.lower()
    return set(_INDEX.get(w, {w}))


def expand_words(words: list[str]) -> list[set[str]]:
    """Per-word synonym expansion, preserving word order (1 set per input word)."""
    return [expand(w) for w in words]
