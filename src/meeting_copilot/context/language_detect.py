"""Binary English-vs-Portuguese detection for short, typed text (the
"Ideia opcional" footer box).

Deliberately a hand-built heuristic, not a general-purpose language-ID
library (`langdetect` etc.): those are statistical/n-gram classifiers
tuned across dozens of languages, and are known to be unreliable on
very short input (a few words) -- exactly the input this box gets. For
a binary EN-vs-PT-BR decision, a small curated stopword list plus
PT-BR-only diacritics is simpler, fully deterministic (no randomness,
no model), and easier to reason about when it's wrong than debugging a
black-box classifier's confidence score.
"""

from __future__ import annotations

import re
from typing import Literal

# Diacritics that only appear in Portuguese among the two languages this
# distinguishes -- their presence alone is a strong, cheap signal.
_PT_ONLY_CHARS = set("ãõçàâêôáéíóú")

_PT_STOPWORDS = {
    "que", "nao", "não", "voce", "você", "para", "com", "uma", "um", "isso",
    "esse", "essa", "mas", "muito", "entao", "então", "aqui", "esta", "está",
    "sao", "são", "tambem", "também", "quero", "preciso", "vamos", "ele",
    "ela", "por", "sobre", "quando", "onde", "porque", "como", "hoje",
    "amanha", "amanhã", "depois", "antes", "ja", "já", "ainda", "eu", "nos",
    "nós", "eles", "elas", "meu", "minha", "seu", "sua", "isto", "aquilo",
    "sim", "nao", "obrigado", "obrigada", "desculpa", "concordo", "acho",
    "falta", "definir",
}

_EN_STOPWORDS = {
    "the", "and", "is", "for", "this", "that", "we", "you", "not", "with",
    "have", "has", "will", "would", "should", "can", "could", "about",
    "when", "where", "because", "how", "today", "tomorrow", "after",
    "before", "already", "still", "or", "if", "i", "they", "them", "our",
    "your", "his", "her", "yes", "no", "thanks", "sorry", "agree", "think",
    "missing", "define", "let's", "let", "start", "now", "please", "need",
    "want", "good", "great", "sure", "maybe", "actually", "here", "there",
    "what", "why", "who", "which", "does", "do", "did", "was", "were",
    "are", "be", "been", "going", "gonna", "just", "really", "also",
}

_WORD_RE = re.compile(r"[a-zà-öø-ÿ']+", re.IGNORECASE)


def detect_language(text: str) -> Literal["en", "pt"]:
    """Best-effort EN-vs-PT-BR guess for `text`. Defaults to "pt" on a
    tie or on text with no recognizable words -- this app's primary
    user is a PT-BR speaker, so an ambiguous short phrase ("ok", "test")
    is more often Portuguese-context than not.
    """
    lowered = text.lower()
    if any(ch in _PT_ONLY_CHARS for ch in lowered):
        return "pt"

    words = set(_WORD_RE.findall(lowered))
    pt_score = len(words & _PT_STOPWORDS)
    en_score = len(words & _EN_STOPWORDS)
    if en_score > pt_score:
        return "en"
    return "pt"
