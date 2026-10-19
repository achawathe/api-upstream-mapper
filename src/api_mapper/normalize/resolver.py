"""Reads unknown spellings as known words: `blnc` -> balance, `entrs` -> entry, `accou` -> account.

A token the vocabulary lacks is replaced only when exactly one known word fits, either
by consonant skeleton (first letter plus the remaining consonants, doubles collapsed,
singular or plural form) or as a prefix of at least four letters. Otherwise the token is
left as it is. Abbreviations count as the word they abbreviate, so `acnt` and `account`
are one candidate, not two.
"""

from collections.abc import Iterable, Mapping

from api_mapper.normalize.tokenizer import singularize

VOWELS = frozenset("aeiou")
MIN_SKELETON = 3
MIN_PREFIX = 4


def skeleton(word: str) -> str:
    letters = word[:1] + "".join(c for c in word[1:] if c not in VOWELS)
    collapsed = []
    for char in letters:
        if not collapsed or collapsed[-1] != char:
            collapsed.append(char)
    return "".join(collapsed)


def plural(word: str) -> str:
    if word.endswith("y") and len(word) > 2 and word[-2] not in VOWELS:
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    return word + "s"


class TokenResolver:
    def __init__(self, vocabulary: Iterable[str], abbreviations: Mapping[str, tuple[str, ...]] = {}):
        self.vocabulary = frozenset(w for w in vocabulary if w.isalpha() and len(w) > 2)
        self._canonical = {}
        for word in self.vocabulary:
            singular = singularize(word)
            expansion = abbreviations.get(singular, abbreviations.get(word, ()))
            self._canonical[word] = expansion[0] if len(expansion) == 1 else singular
        self._by_skeleton: dict[str, set[str]] = {}
        self._forms: list[tuple[str, str]] = []
        for word in self.vocabulary:
            for form in {word, plural(word)}:
                self._by_skeleton.setdefault(skeleton(form), set()).add(word)
                self._forms.append((form, word))
        self._cache: dict[str, str] = {}

    def is_known(self, token: str) -> bool:
        return token in self.vocabulary or singularize(token) in self.vocabulary

    def resolve(self, token: str) -> str:
        if token not in self._cache:
            self._cache[token] = self._resolve(token)
        return self._cache[token]

    def resolve_all(self, tokens: Iterable[str]) -> tuple[str, ...]:
        return tuple(self.resolve(t) for t in tokens)

    def _resolve(self, token: str) -> str:
        if token in self.vocabulary or singularize(token) in self.vocabulary:
            return token
        if not token.isalpha() or len(token) < MIN_SKELETON:
            return token
        token_skeleton = skeleton(token)
        if len(token_skeleton) >= MIN_SKELETON:
            match = self._unique(self._by_skeleton.get(token_skeleton, set()))
            if match:
                return match
        if len(token) >= MIN_PREFIX:
            match = self._unique({word for form, word in self._forms if form.startswith(token) and len(form) > len(token)})
            if match:
                return match
        return token

    def _unique(self, words: set[str]) -> str | None:
        canonical = {self._canonical[w] for w in words}
        return next(iter(canonical)) if len(canonical) == 1 else None
