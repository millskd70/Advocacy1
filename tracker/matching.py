"""Topic keyword matching."""
from __future__ import annotations

import re


def _pattern(keyword: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[\s\-]+", keyword.strip()) if w]
    body = r"[\s\-]+".join(words)
    # Whole-word match that also works for keywords like "R&D" or "340B".
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


class TopicMatcher:
    def __init__(self, topics: dict[str, list[str]], exclude: list[str] | None = None):
        self.topics = {str(t): [str(k) for k in (kws or [])] for t, kws in topics.items()}
        self.patterns = {t: [(k, _pattern(k)) for k in kws] for t, kws in self.topics.items()}
        self.exclude = [_pattern(x) for x in (exclude or [])]

    def match(self, text: str) -> tuple[list[str], list[str]]:
        """Return (topics, keywords) found in text."""
        if not text:
            return [], []
        if any(p.search(text) for p in self.exclude):
            return [], []
        topics, keywords = [], []
        for topic, pats in self.patterns.items():
            hit = False
            for kw, p in pats:
                if p.search(text):
                    hit = True
                    if kw not in keywords:
                        keywords.append(kw)
            if hit:
                topics.append(topic)
        return topics, keywords

    def topics_for_keyword(self, keyword: str) -> list[str]:
        return [t for t, kws in self.topics.items() if keyword in kws]

    def all_keywords(self) -> list[str]:
        seen, out = set(), []
        for kws in self.topics.values():
            for k in kws:
                if k.lower() not in seen:
                    seen.add(k.lower())
                    out.append(k)
        return out
