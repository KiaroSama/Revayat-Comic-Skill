use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Guidance {
    pub profile: String,
    pub target_language: String,
    pub priority: String,
    pub rules: Vec<String>,
}
fn canonical(tag: &str) -> Option<&'static str> {
    Some(match tag {
        "ja" | "jp" | "jpn" | "japan" | "japanese" => "ja",
        "ko" | "kor" | "korean" => "ko",
        "zh"
        | "zho"
        | "chi"
        | "ch"
        | "cmn"
        | "chinese"
        | "simplified chinese"
        | "traditional chinese"
        | "chinese (simplified)"
        | "chinese (traditional)" => "zh",
        "fr" | "fra" | "fre" | "french" | "français" => "fr",
        "es" | "spa" | "spanish" | "español" => "es",
        "en" | "eng" | "english" => "en",
        _ => return None,
    })
}
const COMMON: [&str; 5] = [
    "Translate the supplied source directly into Persian; do not require an English pivot.",
    "Read full words, declared language and page evidence together. A shared script alone does not identify a language; keep uncertain readings open for review.",
    "Resolve speakers, addressees and register from the actual exchange and known cast, not stereotypes. Retain uncertainty when a participant or relationship is unknown.",
    "Interpret connected balloons with the page and relevant nearby context while keeping each translation under its original region ID. Preserve contrastive pronouns, negation, modality, idioms, profanity, hesitation and emphasis.",
    "Use natural Persian appropriate to the dialogue, narration or document. Preserve full meaning; try layout before proposing a shorter version for review.",
];
pub fn guidance(language: Option<&str>) -> Guidance {
    let tag = language
        .unwrap_or_default()
        .trim()
        .to_lowercase()
        .replace('_', "-");
    let profile = canonical(&tag)
        .or_else(|| tag.split_once('-').and_then(|(head, _)| canonical(head)))
        .unwrap_or("generic");
    let extra: &[&str] = match profile {
        "ja" => &[
            "Check vertical columns, furigana/ruby, small kana and voicing marks. Base text and ruby can carry different information; retain approved name readings.",
            "Resolve omitted participants from scene evidence. Honorifics and role speech inform relationships without proving identity or gender; distinguish permission, lack of obligation and prohibition.",
        ],
        "ko" => &[
            "Keep meaningful spacing, particles, sentence endings and Hangul jamo in effects. Do not apply Japanese whitespace removal or read Hanja names as Chinese by default.",
            "Read politeness and kinship terms in their scene: a familiar address need not prove a family relationship. Distinguish permission not to act from prohibition.",
        ],
        "zh" => &[
            "Read Simplified/Traditional characters and horizontal/vertical order as shown. Do not silently convert source script or invent an ambiguous name's pronunciation.",
            "Check word segmentation, omitted subjects, aspect and negation scope. Distinguish lack of necessity from prohibition; retain contrastive pronouns, courtesy and the glossary's established names and genre titles.",
        ],
        "fr" => &[
            "Resolve tu/vous and on from the scene; vous may address one person or several. Keep contrast and politeness without mechanically adding Persian pronouns.",
            "Check colloquial negation even when ne is omitted, modality, idioms and slang. Preserve differences between spoken dialogue, narration and formal documents.",
        ],
        "es" => &[
            "Read tú, usted, ustedes, vosotros and vos with the scene and established regional voice. Resolve omitted subjects; grammatical gender alone does not identify the speaker.",
            "Check negative scope, obligation and permission before rephrasing idioms or slang. Preserve names and address choices already settled for this cast.",
        ],
        "en" => &[
            "Distinguish don't have to or need not from must not. Read contractions, phrasal verbs, irony and negation in context instead of translating word by word.",
            "You does not by itself decide singular/plural or تو/شما. Keep contrastive pronouns and choose address from the exchange and established cast decisions.",
        ],
        _ => &[],
    };
    Guidance{profile:profile.into(),target_language:"fa".into(),priority:"Existing title policy, locked glossary and known cast decisions win over these defaults.".into(),rules:COMMON.into_iter().chain(extra.iter().copied()).map(str::to_owned).collect()}
}
