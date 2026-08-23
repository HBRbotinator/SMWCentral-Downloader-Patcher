"""ROM-title normalization and conservative catalogue matching."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROM_EXTENSIONS = frozenset({".smc", ".sfc"})
_DIFFICULTY_NAMES = frozenset(
    {
        "newcomer",
        "casual",
        "intermediate",
        "advanced",
        "expert",
        "master",
        "grandmaster",
        "easy",
        "normal",
        "hard",
        "very hard",
        "beginner",
        "tool-assisted",
        "pit",
    }
)
_EDITION_SUFFIXES = (
    "remastered",
    "deluxe edition",
    "deluxe",
    "definitive edition",
    "special edition",
    "updated edition",
    "updated",
    "final mix",
)
_VARIANT_SUFFIXES = (
    "content id safe",
    "contentid safe",
    "contentidsafe",
    "original music",
    "originalmusic",
    "censored",
    "uncensored",
    "fixed",
    "patched",
    "headered",
    "unheadered",
    "final",
)
_LEADING_ARTICLES = frozenset({"a", "an", "the"})
_GENERIC_TITLE_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "of",
        "the",
        "to",
        "for",
        "in",
        "super",
        "mario",
        "world",
        "kaizo",
        "new",
    }
)
_PROVISIONAL_TITLE_MARKERS = frozenset(
    {"demo", "beta", "alpha", "prototype", "preview", "sample"}
)
_BASE_ROM_TITLES = frozenset(
    {
        "super mario world",
        "super mario world usa",
        "super mario world japan",
        "super mario world europe",
        "smw clean",
        "clean super mario world",
    }
)
_STOPWORDS = frozenset(
    {"a", "an", "and", "of", "the", "to", "for", "in", "super", "mario", "world", "kaizo"}
)

# Only explicit labels are treated as embedded SMWC IDs. Bare numeric brackets
# are intentionally not identity evidence: [2020], [2], etc. can be legitimate
# title/version text in user-owned libraries.
_SMWC_ID_MARKER = re.compile(
    r"(?ix)(?:\[|\()\s*SMWC\s*-?\s*(?:ID\s*-?\s*)?(\d+)\s*(?:\]|\))"
)


@dataclass(frozen=True)
class CatalogueEntry:
    """Lightweight provider-neutral catalogue row used for local matching."""

    smwc_submission_id: int
    title: str
    difficulty: str = ""
    hack_type: str = ""
    exits: int | None = None
    authors: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CatalogueEntry":
        raw_id = value.get("smwc_submission_id", value.get("id"))
        if isinstance(raw_id, bool):
            raise ValueError("Catalogue SMWC submission ID must be a positive integer.")
        try:
            smwc_id = int(raw_id)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Catalogue SMWC submission ID must be a positive integer."
            ) from error
        if smwc_id <= 0:
            raise ValueError("Catalogue SMWC submission ID must be a positive integer.")

        title = str(value.get("title") or value.get("name") or "").strip()
        if not title:
            raise ValueError("Catalogue title must be non-empty.")

        raw_authors = value.get("authors") or ()
        if isinstance(raw_authors, str):
            author_values: Iterable[Any] = re.split(r"[,;]", raw_authors)
        elif isinstance(raw_authors, Mapping):
            author_values = (raw_authors,)
        else:
            author_values = raw_authors if isinstance(raw_authors, Iterable) else ()
        authors = []
        for raw_author in author_values:
            if isinstance(raw_author, Mapping):
                raw_author = (
                    raw_author.get("name")
                    or raw_author.get("username")
                    or raw_author.get("display_name")
                    or ""
                )
            author = str(raw_author).strip()
            if author:
                authors.append(author)

        exits = value.get("exits")
        if exits is not None:
            if isinstance(exits, bool):
                exits = None
            else:
                try:
                    exits = int(exits)
                except (TypeError, ValueError):
                    exits = None

        return cls(
            smwc_submission_id=smwc_id,
            title=title,
            difficulty=str(
                value.get("current_difficulty")
                or value.get("difficulty")
                or ""
            ).strip(),
            hack_type=str(value.get("hack_type") or value.get("type") or "").strip(),
            exits=exits,
            authors=tuple(authors),
        )


@dataclass(frozen=True)
class RankedCatalogueMatch:
    """One scored catalogue candidate."""

    entry: CatalogueEntry
    score: float
    exact: bool
    core_exact: bool
    articleless_exact: bool
    abbreviation_match: bool
    phrase_match: bool
    number_conflict: bool
    short_guard: bool
    qualifier_conflict: bool
    matched_distinctive_tokens: tuple[str, ...]


@dataclass(frozen=True)
class CatalogueMatchResult:
    """Conservative classification of one title against the catalogue."""

    selected: CatalogueEntry | None
    suggestion: CatalogueEntry | None
    confidence: float
    classification: str
    margin: float
    auto_selected: bool
    ranked: tuple[RankedCatalogueMatch, ...]


def extract_explicit_smwc_submission_ids(value: str) -> tuple[int, ...]:
    """Return distinct explicit ``SMWC[-ID]-<id>`` markers in encounter order."""

    result = []
    seen = set()
    for match in _SMWC_ID_MARKER.finditer(str(value)):
        identifier = int(match.group(1))
        if identifier <= 0 or identifier in seen:
            continue
        seen.add(identifier)
        result.append(identifier)
    return tuple(result)


def strip_explicit_smwc_submission_ids(value: str) -> str:
    """Remove explicit SMWC-ID filename metadata before title matching."""

    return _SMWC_ID_MARKER.sub(" ", str(value))


def _strip_version_suffix(text: str) -> tuple[str, str]:
    """Remove likely patch versions while retaining sequel/title numbers."""

    original = text
    version = ""
    patterns = (
        r"(?ix)(?:[\s._-]*)(?:v(?:er(?:sion)?)?|rev(?:ision)?|beta|alpha)"
        r"\s*[-_. ]*([0-9]+(?:[\s._-]+[0-9]+){0,3})\s*(?:final)?$",
        r"(?ix)[\s_-]+([0-9]+(?:[._-][0-9]+){1,3})\s*(?:final)?$",
        r"(?ix)([0-9]+(?:\.[0-9]+){1,3})\s*(?:final)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = text[: match.start()].rstrip(" ._-()").strip()
            if candidate and re.search(r"[A-Za-z]", candidate):
                version = re.sub(r"[\s_-]+", ".", match.group(1)).strip(".")
                text = candidate
                break
    text = re.sub(
        r"(?i)[\s._-]+(?:final|patched|headered|unheadered)$",
        "",
        text,
    ).strip()
    return (text or original).strip(), version


def _strip_comparison_metadata(normal: str) -> str:
    value = normal.strip()
    changed = True
    while changed:
        changed = False
        for suffix in _VARIANT_SUFFIXES:
            updated = re.sub(
                rf"(?:\s+|^){re.escape(suffix)}$",
                "",
                value,
            ).strip()
            if updated != value:
                value = updated
                changed = True
    value = re.sub(r"\s+rev\s+[a-z0-9]+$", "", value).strip()
    value = re.sub(
        r"\s+(?:v|ver|version|rev|beta|alpha)\s+\d+"
        r"(?:\s+\d+){0,3}$",
        "",
        value,
    ).strip()

    tokens = value.split()
    trailing = 0
    for token in reversed(tokens):
        if token.isdigit():
            trailing += 1
        else:
            break
    if trailing >= 2:
        keep = 1 if trailing >= 3 else 0
        value = " ".join(tokens[: len(tokens) - trailing + keep]).strip()
    return value


def _without_leading_article(value: str) -> str:
    tokens = value.split()
    if len(tokens) > 1 and tokens[0] in _LEADING_ARTICLES:
        return " ".join(tokens[1:])
    return value


def clean_title_for_match(value: str) -> str:
    """Normalize a local filename/title without destroying sequel numbers."""

    text = strip_explicit_smwc_submission_ids(str(value)).strip()
    while Path(text).suffix.casefold() in ROM_EXTENSIONS:
        text = text[: -len(Path(text).suffix)]
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("&", " and ")
    text = re.sub(
        r"(?i)\[[^\]]*(?:rev|version|ver\.?|v\s*\d|patched|headered|"
        r"unheadered|usa|japan|europe|eu)[^\]]*\]",
        " ",
        text,
    )
    text = re.sub(
        r"(?i)\([^)]*(?:rev|version|ver\.?|v\s*\d|patched|headered|"
        r"unheadered|usa|japan|europe|eu)[^)]*\)",
        " ",
        text,
    )
    text = re.sub(
        r"(?i)\s*\(\s*\d+(?:[._-]\d+){1,3}\s*\)\s*$",
        "",
        text,
    )
    text, _version = _strip_version_suffix(text)
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", text)
    text = re.sub(r"(?<=[0-9])(?=[A-Za-z])", " ", text)
    text = re.sub(
        r"(?i)\b(?:patched|headered|unheadered|romhack|rom hack)\b",
        " ",
        text,
    )
    text = re.sub(r"[^A-Za-z0-9']+", " ", text)
    return " ".join(text.split()).strip()


def normalise_title(value: str) -> str:
    return clean_title_for_match(value).casefold()


def compact_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalise_title(value))


def is_probable_base_rom(value: str) -> bool:
    normal = normalise_title(value)
    return normal in _BASE_ROM_TITLES or (
        normal.startswith("super mario world")
        and any(token in normal for token in (" usa", " japan", " europe", " clean"))
    )


def infer_difficulty_hint(
    path: str | os.PathLike[str],
    known_difficulties: Iterable[str] = (),
) -> str:
    """Infer a weak difficulty hint from ancestor directory labels."""

    known = {
        str(item).casefold(): str(item)
        for item in known_difficulties
        if str(item).strip()
    }
    for parent in Path(path).parents:
        label = re.sub(r"^[.\s_-]*\d+[.\s_-]*", "", parent.name).strip()
        key = label.casefold()
        if key in known:
            return known[key]
        if key in _DIFFICULTY_NAMES:
            return label
    return ""


def _core_title(normal: str) -> str:
    value = _strip_comparison_metadata(normal.strip())
    for suffix in _EDITION_SUFFIXES:
        if value == suffix:
            continue
        value = re.sub(rf"\s+{re.escape(suffix)}$", "", value).strip()
    return value


def _title_acronym(tokens: Sequence[str]) -> str:
    meaningful = [
        token
        for token in tokens
        if token not in {"a", "an", "and", "of", "the", "to", "for", "in"}
    ]
    return "".join(
        token if token.isdigit() else token[0]
        for token in meaningful
        if token
    )


def _title_profile(value: str) -> dict[str, Any]:
    normal = normalise_title(value)
    core = _core_title(normal)
    articleless = _without_leading_article(normal)
    articleless_core = _without_leading_article(core)
    compact = re.sub(r"[^a-z0-9]", "", normal)
    core_compact = re.sub(r"[^a-z0-9]", "", core)
    articleless_compact = re.sub(r"[^a-z0-9]", "", articleless)
    articleless_core_compact = re.sub(r"[^a-z0-9]", "", articleless_core)
    tokens = tuple(normal.split())
    core_tokens = tuple(core.split())
    return {
        "normal": normal,
        "core": core,
        "articleless": articleless,
        "articleless_core": articleless_core,
        "compact": compact,
        "core_compact": core_compact,
        "articleless_compact": articleless_compact,
        "articleless_core_compact": articleless_core_compact,
        "tokens": tokens,
        "core_tokens": core_tokens,
        "token_set": frozenset(tokens),
        "numbers": tuple(re.findall(r"\b\d+\b", core)),
        "acronym": _title_acronym(core_tokens),
    }


def _match_details(
    left_profile: Mapping[str, Any],
    right_profile: Mapping[str, Any],
    *,
    difficulty_hint: str = "",
    candidate_difficulty: str = "",
    token_frequencies: Mapping[str, int] | None = None,
    catalogue_size: int = 0,
) -> dict[str, Any]:
    a = str(left_profile.get("normal") or "")
    b = str(right_profile.get("normal") or "")
    ac = str(left_profile.get("compact") or "")
    bc = str(right_profile.get("compact") or "")
    if not a or not b:
        return {
            "score": 0.0,
            "exact": False,
            "core_exact": False,
            "articleless_exact": False,
            "abbreviation_match": False,
            "phrase_match": False,
            "number_conflict": False,
            "short_guard": False,
            "qualifier_conflict": False,
            "matched_distinctive_tokens": (),
        }

    left_core = str(left_profile.get("core") or a)
    right_core = str(right_profile.get("core") or b)
    left_core_compact = str(left_profile.get("core_compact") or ac)
    right_core_compact = str(right_profile.get("core_compact") or bc)
    exact = a == b or bool(ac and ac == bc)
    core_exact = left_core == right_core or bool(
        left_core_compact and left_core_compact == right_core_compact
    )
    left_articleless = str(left_profile.get("articleless_core") or left_core)
    right_articleless = str(right_profile.get("articleless_core") or right_core)
    left_articleless_compact = str(
        left_profile.get("articleless_core_compact") or left_core_compact
    )
    right_articleless_compact = str(
        right_profile.get("articleless_core_compact") or right_core_compact
    )
    articleless_exact = bool(
        not exact
        and not core_exact
        and (
            left_articleless == right_articleless
            or (
                left_articleless_compact
                and left_articleless_compact == right_articleless_compact
            )
        )
    )
    abbreviation_match = bool(
        left_core_compact
        and right_profile.get("acronym")
        and left_core_compact == right_profile.get("acronym")
    )

    a_tokens = tuple(left_profile.get("tokens") or ())
    b_tokens = tuple(right_profile.get("tokens") or ())
    a_set = set(left_profile.get("token_set") or a_tokens)
    b_set = set(right_profile.get("token_set") or b_tokens)
    intersection = len(a_set & b_set)
    token_f1 = (
        2 * intersection / (len(a_set) + len(b_set))
        if (a_set or b_set)
        else 0.0
    )
    sequence = SequenceMatcher(None, a, b).ratio()
    compact_sequence = SequenceMatcher(None, ac, bc).ratio() if ac and bc else 0.0
    sorted_sequence = SequenceMatcher(
        None,
        " ".join(sorted(a_tokens)),
        " ".join(sorted(b_tokens)),
    ).ratio()
    weighted_sequence = 0.48 * sequence + 0.32 * compact_sequence + 0.20 * token_f1
    weighted_sorted = 0.70 * sorted_sequence + 0.30 * token_f1

    if exact:
        score = 1.0
    elif core_exact:
        score = 0.97
    elif articleless_exact:
        score = 0.96
    elif abbreviation_match:
        score = 0.92
    else:
        score = max(weighted_sequence, weighted_sorted)

    frequencies = dict(token_frequencies or {})
    query_distinctive = {
        token
        for token in a_set
        if token not in _GENERIC_TITLE_TOKENS
        and len(token) > 1
        and not token.isdigit()
    }
    candidate_distinctive = {
        token
        for token in b_set
        if token not in _GENERIC_TITLE_TOKENS
        and len(token) > 1
        and not token.isdigit()
    }
    matched_distinctive = query_distinctive & candidate_distinctive
    near_distinctive_pairs: list[tuple[str, str, float]] = []
    for query_token in sorted(query_distinctive - matched_distinctive):
        best_pair = None
        for candidate_token in candidate_distinctive - matched_distinctive:
            if min(len(query_token), len(candidate_token)) < 5:
                continue
            prefix = os.path.commonprefix((query_token, candidate_token))
            similarity = SequenceMatcher(None, query_token, candidate_token).ratio()
            if len(prefix) >= 4 and similarity >= 0.62:
                pair = (query_token, candidate_token, similarity)
                if best_pair is None or pair[2] > best_pair[2]:
                    best_pair = pair
        if best_pair:
            near_distinctive_pairs.append(best_pair)

    if query_distinctive and not abbreviation_match:
        effective_matches = len(matched_distinctive) + len(near_distinctive_pairs)
        coverage = min(1.0, effective_matches / len(query_distinctive))
        if matched_distinctive or near_distinctive_pairs:
            rarity = 0.0
            if matched_distinctive:
                rarity = max(
                    0.0,
                    min(
                        1.0,
                        max(
                            1.0
                            - (
                                float(
                                    frequencies.get(
                                        token,
                                        catalogue_size or 1,
                                    )
                                )
                                / max(1.0, float(catalogue_size or 1))
                            )
                            ** 0.25
                            for token in matched_distinctive
                        ),
                    ),
                )
            exact_coverage = len(matched_distinctive) / len(query_distinctive)
            score = min(1.0, score + 0.10 * rarity * exact_coverage)
            score = min(
                1.0,
                score + 0.06 * (len(near_distinctive_pairs) / len(query_distinctive)),
            )
            if (
                matched_distinctive
                and coverage == 1.0
                and not near_distinctive_pairs
                and max(
                    frequencies.get(token, catalogue_size or 1)
                    for token in matched_distinctive
                )
                <= 3
            ):
                score = max(score, 0.88)
            elif coverage == 1.0 and near_distinctive_pairs:
                score = max(score, 0.72)
            if coverage < 1.0:
                score = max(0.0, score - 0.08 * (1.0 - coverage))
        else:
            score = max(0.0, score - 0.12)

    phrase_match = False
    if not exact and not core_exact and left_core:
        phrase_pattern = rf"(?:^|\s){re.escape(left_core)}(?:$|\s)"
        phrase_match = bool(re.search(phrase_pattern, right_core))
        if phrase_match:
            phrase_floor = 0.86 if len(left_core.split()) >= 2 else 0.68
            score = max(score, phrase_floor)

    left_numbers = tuple(left_profile.get("numbers") or ())
    right_numbers = tuple(right_profile.get("numbers") or ())
    number_conflict = left_numbers != right_numbers and bool(
        left_numbers or right_numbers
    )
    if number_conflict and not exact and not core_exact:
        if left_numbers and right_numbers:
            cap = 0.76
        elif left_numbers and not right_numbers:
            cap = 0.79
        else:
            cap = 0.78
        score = min(score, cap)

    query_markers = a_set & _PROVISIONAL_TITLE_MARKERS
    candidate_markers = b_set & _PROVISIONAL_TITLE_MARKERS
    qualifier_conflict = bool(candidate_markers - query_markers)

    short_guard = min(len(ac), len(bc)) <= 5 or min(
        len(a_tokens), len(b_tokens)
    ) <= 1
    if short_guard and not exact and not abbreviation_match:
        score = min(score, 0.78)

    if score >= 0.70 and difficulty_hint and candidate_difficulty:
        if normalise_title(difficulty_hint) == normalise_title(candidate_difficulty):
            score = min(1.0, score + 0.01)

    return {
        "score": round(float(score), 6),
        "exact": exact,
        "core_exact": core_exact,
        "articleless_exact": articleless_exact,
        "abbreviation_match": abbreviation_match,
        "phrase_match": phrase_match,
        "number_conflict": number_conflict,
        "short_guard": short_guard,
        "qualifier_conflict": qualifier_conflict,
        "matched_distinctive_tokens": tuple(sorted(matched_distinctive)),
    }


class CatalogueMatcher:
    """Prepared matcher for the lightweight KaizOFF/SMWC catalogue index."""

    def __init__(self, candidates: Sequence[CatalogueEntry | Mapping[str, Any]]):
        self.entries = tuple(
            item if isinstance(item, CatalogueEntry) else CatalogueEntry.from_mapping(item)
            for item in candidates
        )
        self._prepared: list[tuple[CatalogueEntry, dict[str, Any]]] = []
        self.by_id: dict[int, CatalogueEntry] = {}
        self._by_exact_key: dict[str, list[int]] = {}
        self._token_frequencies: dict[str, int] = {}

        for index, entry in enumerate(self.entries):
            if entry.smwc_submission_id in self.by_id:
                raise ValueError(
                    "Catalogue contains duplicate SMWC submission ID: "
                    f"{entry.smwc_submission_id}"
                )
            self.by_id[entry.smwc_submission_id] = entry
            profile = _title_profile(entry.title)
            self._prepared.append((entry, profile))
            for key in (
                profile["normal"],
                profile["compact"],
                profile["core"],
                profile["core_compact"],
                profile["articleless_core"],
                profile["articleless_core_compact"],
            ):
                if key:
                    self._by_exact_key.setdefault(str(key), []).append(index)
            for token in profile["token_set"]:
                self._token_frequencies[token] = (
                    self._token_frequencies.get(token, 0) + 1
                )

    def get(self, smwc_submission_id: int) -> CatalogueEntry | None:
        return self.by_id.get(int(smwc_submission_id))

    def score_entry(
        self,
        title: str,
        smwc_submission_id: int,
        *,
        difficulty_hint: str = "",
    ) -> RankedCatalogueMatch | None:
        """Score a known catalogue ID against a local title hint."""

        identifier = int(smwc_submission_id)
        for prepared in self._prepared:
            if prepared[0].smwc_submission_id == identifier:
                return self._score(
                    _title_profile(title),
                    prepared,
                    difficulty_hint,
                )
        return None

    def _score(
        self,
        query_profile: Mapping[str, Any],
        prepared: tuple[CatalogueEntry, Mapping[str, Any]],
        difficulty_hint: str,
    ) -> RankedCatalogueMatch:
        entry, profile = prepared
        details = _match_details(
            query_profile,
            profile,
            difficulty_hint=difficulty_hint,
            candidate_difficulty=entry.difficulty,
            token_frequencies=self._token_frequencies,
            catalogue_size=len(self.entries),
        )
        return RankedCatalogueMatch(
            entry=entry,
            score=float(details["score"]),
            exact=bool(details["exact"]),
            core_exact=bool(details["core_exact"]),
            articleless_exact=bool(details["articleless_exact"]),
            abbreviation_match=bool(details["abbreviation_match"]),
            phrase_match=bool(details["phrase_match"]),
            number_conflict=bool(details["number_conflict"]),
            short_guard=bool(details["short_guard"]),
            qualifier_conflict=bool(details["qualifier_conflict"]),
            matched_distinctive_tokens=tuple(
                details["matched_distinctive_tokens"]
            ),
        )

    def rank(
        self,
        title: str,
        *,
        difficulty_hint: str = "",
        limit: int = 20,
    ) -> tuple[RankedCatalogueMatch, ...]:
        query = _title_profile(title)
        if not query["normal"]:
            return ()

        exact_indexes = set()
        for key in (
            query["normal"],
            query["compact"],
            query["core"],
            query["core_compact"],
            query["articleless_core"],
            query["articleless_core_compact"],
        ):
            exact_indexes.update(self._by_exact_key.get(str(key), ()))

        if exact_indexes:
            pool = [self._prepared[index] for index in sorted(exact_indexes)]
        else:
            meaningful = {
                token
                for token in query["token_set"]
                if token not in _STOPWORDS and len(token) > 1
            }
            priority = []
            seen = set()
            for index, prepared in enumerate(self._prepared):
                profile = prepared[1]
                if (
                    query["core_compact"]
                    and profile["acronym"] == query["core_compact"]
                ) or (meaningful & set(profile["token_set"])):
                    priority.append(prepared)
                    seen.add(index)

            quick = []
            qcompact = str(query["compact"])
            qlen = max(1, len(qcompact))
            if len(priority) < 15:
                for index, prepared in enumerate(self._prepared):
                    if index in seen:
                        continue
                    ccompact = str(prepared[1]["compact"])
                    if not ccompact:
                        continue
                    ratio = len(ccompact) / qlen
                    if ratio < 0.45 or ratio > 2.2:
                        continue
                    quick_score = SequenceMatcher(None, qcompact, ccompact).ratio()
                    if quick_score >= 0.48:
                        quick.append((quick_score, prepared))
                quick.sort(key=lambda pair: pair[0], reverse=True)
            pool = priority + [prepared for _score, prepared in quick[:120]]

        ranked = [
            self._score(query, prepared, difficulty_hint)
            for prepared in pool
        ]
        ranked.sort(
            key=lambda item: (-item.score, item.entry.title.casefold())
        )
        return tuple(ranked[: max(1, int(limit))])

    def find(
        self,
        title: str,
        *,
        difficulty_hint: str = "",
    ) -> CatalogueMatchResult:
        return classify_ranked_matches(
            self.rank(title, difficulty_hint=difficulty_hint)
        )


def classify_ranked_matches(
    ranked: Sequence[RankedCatalogueMatch],
) -> CatalogueMatchResult:
    if not ranked:
        return CatalogueMatchResult(
            selected=None,
            suggestion=None,
            confidence=0.0,
            classification="Unmatched",
            margin=0.0,
            auto_selected=False,
            ranked=(),
        )

    best = ranked[0]
    runner = ranked[1].score if len(ranked) > 1 else 0.0
    margin = best.score - runner
    unsafe = bool(
        best.number_conflict
        or best.short_guard
        or best.abbreviation_match
        or best.phrase_match
        or best.qualifier_conflict
    ) and not best.exact
    safe_distinctive_fuzzy = bool(
        not best.phrase_match
        and not unsafe
        and best.matched_distinctive_tokens
        and best.score >= 0.88
        and margin >= 0.12
    )
    safe_unique_phrase = bool(
        best.phrase_match
        and not best.short_guard
        and not best.number_conflict
        and not best.abbreviation_match
        and not best.qualifier_conflict
        and best.matched_distinctive_tokens
        and best.score >= 0.88
        and margin >= 0.12
    )

    if best.exact and runner >= 0.999:
        classification = "Ambiguous"
        approved = False
    elif best.exact:
        classification = "Exact"
        approved = True
    elif best.core_exact and runner < 0.94:
        classification = "Strong"
        approved = True
    elif best.articleless_exact and not best.short_guard and runner < 0.94:
        classification = "Strong"
        approved = True
    elif safe_unique_phrase or safe_distinctive_fuzzy:
        classification = "Strong"
        approved = True
    elif best.score >= 0.90 and margin >= 0.045 and not unsafe:
        classification = "Strong"
        approved = True
    elif best.score >= 0.72 and margin < 0.045:
        classification = "Ambiguous"
        approved = False
    elif best.abbreviation_match:
        classification = "Abbreviation - review"
        approved = False
    elif best.phrase_match:
        classification = "Partial title - review"
        approved = False
    elif best.score >= 0.68:
        classification = "Review"
        approved = False
    else:
        classification = "Unmatched"
        approved = False

    return CatalogueMatchResult(
        selected=best.entry if approved else None,
        suggestion=best.entry,
        confidence=best.score,
        classification=classification,
        margin=round(margin, 6),
        auto_selected=approved,
        ranked=tuple(ranked[:10]),
    )


__all__ = [
    "CatalogueEntry",
    "CatalogueMatchResult",
    "CatalogueMatcher",
    "ROM_EXTENSIONS",
    "RankedCatalogueMatch",
    "classify_ranked_matches",
    "clean_title_for_match",
    "compact_title",
    "extract_explicit_smwc_submission_ids",
    "infer_difficulty_hint",
    "is_probable_base_rom",
    "normalise_title",
    "strip_explicit_smwc_submission_ids",
]
