"""Original reading guidance selected from declared language, never guessed from script."""

from __future__ import annotations


_ALIASES = {
    "ja": "ja", "jp": "ja", "jpn": "ja", "japan": "ja", "japanese": "ja",
    "ko": "ko", "kor": "ko", "korean": "ko",
    "zh": "zh", "zho": "zh", "chi": "zh", "ch": "zh", "cmn": "zh",
    "chinese": "zh", "simplified chinese": "zh", "traditional chinese": "zh",
    "chinese (simplified)": "zh", "chinese (traditional)": "zh",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "français": "fr",
    "es": "es", "spa": "es", "spanish": "es", "español": "es",
    "en": "en", "eng": "en", "english": "en",
}

_COMMON = (
    "Translate the supplied source directly into Persian; do not require an English pivot.",
    "Read full words, declared language and page evidence together. A shared script alone "
    "does not identify a language; keep uncertain readings open for review.",
    "Resolve speakers, addressees and register from the actual exchange and known cast, "
    "not stereotypes. Retain uncertainty when a participant or relationship is unknown.",
    "Interpret connected balloons with the page and relevant nearby context while keeping "
    "each translation under its original region ID. Preserve contrastive pronouns, "
    "negation, modality, idioms, profanity, hesitation and emphasis.",
    "Use natural Persian appropriate to the dialogue, narration or document. Preserve "
    "full meaning; try layout before proposing a shorter version for review.",
)

_SOURCE_RULES = {
    "ja": (
        "Check vertical columns, furigana/ruby, small kana and voicing marks. Base text "
        "and ruby can carry different information; retain approved name readings.",
        "Resolve omitted participants from scene evidence. Honorifics and role speech "
        "inform relationships without proving identity or gender; distinguish permission, "
        "lack of obligation and prohibition.",
    ),
    "ko": (
        "Keep meaningful spacing, particles, sentence endings and Hangul jamo in effects. "
        "Do not apply Japanese whitespace removal or read Hanja names as Chinese by default.",
        "Read politeness and kinship terms in their scene: a familiar address need not "
        "prove a family relationship. Distinguish permission not to act from prohibition.",
    ),
    "zh": (
        "Read Simplified/Traditional characters and horizontal/vertical order as shown. "
        "Do not silently convert source script or invent an ambiguous name's pronunciation.",
        "Check word segmentation, omitted subjects, aspect and negation scope. Distinguish "
        "lack of necessity from prohibition; retain contrastive pronouns, courtesy and "
        "the glossary's established names and genre titles.",
    ),
    "fr": (
        "Resolve tu/vous and on from the scene; vous may address one person or several. "
        "Keep contrast and politeness without mechanically adding Persian pronouns.",
        "Check colloquial negation even when ne is omitted, modality, idioms and slang. "
        "Preserve differences between spoken dialogue, narration and formal documents.",
    ),
    "es": (
        "Read tú, usted, ustedes, vosotros and vos with the scene and established regional voice. "
        "Resolve omitted subjects; grammatical gender alone does not identify the speaker.",
        "Check negative scope, obligation and permission before rephrasing idioms or slang. "
        "Preserve names and address choices already settled for this cast.",
    ),
    "en": (
        "Distinguish don't have to or need not from must not. Read contractions, phrasal "
        "verbs, irony and negation in context instead of translating word by word.",
        "You does not by itself decide singular/plural or تو/شما. Keep contrastive "
        "pronouns and choose address from the exchange and established cast decisions.",
    ),
}


def guidance(source_language: str | None) -> dict[str, str | list[str]]:
    """Return bounded advisory text; unknown languages retain the general Persian route."""
    tag = source_language.strip().casefold().replace("_", "-") if isinstance(source_language, str) else ""
    profile = _ALIASES.get(tag, _ALIASES.get(tag.split("-", 1)[0], "generic"))
    return {
        "profile": profile,
        "target_language": "fa",
        "priority": "Existing title policy, locked glossary and known cast decisions "
                    "win over these defaults.",
        "rules": [*_COMMON, *_SOURCE_RULES.get(profile, ())],
    }
