"""The town library: memory that lives in the world, sorted by topic.

A ``LibraryArchive`` persists across towns (episodes) of one universe. Its entries are

  * consolidated laws, written from a learned ``TownSeedMemory`` after each town
    (each carries the hypothesis it states, so its correctness can be scored), and
  * free-text notes an agent chooses to write (``write_note``).

Inside a town the archive appears as shelves in the ``library`` location, one per topic
(categorized mode) or a single unsorted pile (flat mode). Reading a shelf is an action and
takes a tick of game time, so finding the right memory has a cost: this is what lets us
compare categorized against uncategorized memory, and later trusted against untrusted
memory written by other agents.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CATEGORIES = ["farming", "gifting", "schedule", "shop", "general"]
FLAT_PAGE = 4  # entries shown per read of the unsorted pile


def category_of_space(space: str) -> str:
    if space.startswith(("soil.", "season.")):
        return "farming"
    if space.startswith("likes.") or space == "gift_attr":
        return "gifting"
    if space == "midday_place":
        return "schedule"
    return "general"


@dataclass
class Entry:
    category: str
    text: str
    source: str = "consolidated"  # consolidated | note
    author: str = "agent"
    episode: int = -1
    claims: list[tuple[str, str]] = field(default_factory=list)  # (hypothesis space, value) it asserts

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claims"] = [list(c) for c in self.claims]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        d = dict(d)
        d["claims"] = [tuple(c) for c in d.get("claims", [])]
        return cls(**d)


@dataclass
class LibraryArchive:
    entries: list[Entry] = field(default_factory=list)
    mode: str = "categorized"  # categorized | flat
    reads: int = 0

    # ------------------------------------------------------------ writing
    def update_from_seed(self, seed, episode: int, author: str = "agent") -> None:
        """Rewrite this author's consolidated entries from a learned seed (one entry per law)."""
        self.entries = [e for e in self.entries if not (e.source == "consolidated" and e.author == author)]
        for sp in seed.SPACES:
            val = seed.confident(sp)
            if val is None:
                continue
            self.entries.append(Entry(category_of_space(sp), describe_claim(sp, val), "consolidated", author,
                                      episode, [(sp, val)]))

    def write_notes(self, seed, episode: int, authors: dict[str, float]) -> int:
        """Several authors each write what ``seed`` is confident of; author ``a`` gets each law wrong
        with probability ``authors[a]`` (consistently: the same author is always wrong about the same
        law). Replaces those authors' earlier notes. Returns the number of wrong claims written."""
        from .sources import describe, maybe_corrupt

        self.entries = [e for e in self.entries if e.author not in authors]
        wrong = 0
        for sp in seed.SPACES:
            val = seed.confident(sp)
            if val is None:
                continue
            for a, rate in authors.items():
                v, bad = maybe_corrupt(sp, val, rate, "note", a)
                wrong += bad
                self.entries.append(Entry(category_of_space(sp), describe_claim(sp, v), "note", a, episode,
                                          [(sp, v)]))
        return wrong

    def add_note(self, category: str, text: str, author: str = "agent", episode: int = -1) -> Entry:
        cat = category if category in CATEGORIES else "general"
        e = Entry(cat, text.strip()[:240], "note", author, episode)
        self.entries.append(e)
        return e

    # ------------------------------------------------------------ reading
    def shelf(self, category: str) -> list[Entry]:
        return [e for e in self.entries if e.category == category]

    def page(self, k: int) -> list[Entry]:
        """k-th page of the unsorted pile (entries interleaved across topics, oldest first)."""
        return self.entries[k * FLAT_PAGE:(k + 1) * FLAT_PAGE]

    def pages(self) -> int:
        return max(1, -(-len(self.entries) // FLAT_PAGE))

    # ------------------------------------------------------------ scoring
    def accuracy(self, truth: dict[str, str]) -> tuple[int, int]:
        """(correct, scored) over consolidated claims."""
        scored = [(sp, v) for e in self.entries for sp, v in e.claims if sp in truth]
        return sum(1 for sp, v in scored if truth[sp] == v), len(scored)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, d: dict) -> "LibraryArchive":
        return cls([Entry.from_dict(e) for e in d.get("entries", [])], d.get("mode", "categorized"))


def describe_claim(space: str, value: str) -> str:
    if space.startswith("soil."):
        return f"{space[5:].capitalize()} only survives in {value} soil."
    if space.startswith("season."):
        return f"{space[7:].capitalize()} only grows in {value}."
    if space == "gift_attr":
        return ("Villagers love gifts whose colour matches their shirt." if value == "color"
                else "Villagers love gifts of the category their job prefers.")
    if space.startswith("likes."):
        return f"A {space[6:]} loves {value} gifts."
    if space == "midday_place":
        return {"home": "At midday villagers stay at home.", "work": "At midday villagers are at their workplace."
                }.get(value, f"At midday villagers gather at the {value}.")
    return f"{space} = {value}"


def entry_line(e: Entry) -> str:
    who = "consolidated" if e.source == "consolidated" and e.author in ("agent", "librarian") else f"note by {e.author}"
    when = f", town {e.episode}" if e.episode >= 0 else ""
    return f"- {e.text} ({who}{when})"
