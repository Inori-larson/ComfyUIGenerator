"""Cross-stage action contamination detection.

The software never authors semantics. It only compares which high-salience
sexual ACTIONS the English prompt asserts against the actions the locked
script describes. A prompt tag for an action the script never performs is
cross-stage contamination (a tag from a different beat/milestone).

Both the prompt tag patterns and the script evidence patterns are language
level (English Booru tags and generic Chinese action phrases). Nothing here
is tied to a specific character, outfit, shot number, or story.
"""

from __future__ import annotations

import re

# Strict English Booru tags that explicitly assert a sexual action category.
PROMPT_ACTION_TAGS: dict[str, tuple[str, ...]] = {
    "blowjob": (
        r"^cum in mouth$", r"^swallowing cum$", r"^swallowing semen$",
        r"^fellatio$", r"^penis in mouth$", r"^deepthroat$", r"^blowjob$",
    ),
    "cum_shot": (
        r"^cum on face$", r"^facial$", r"^cum on breasts?$",
        r"^cum on stomach$", r"^cum on body$", r"^cum in hair$",
    ),
    "creampie": (
        r"^creampie$", r"^cum in pussy$", r"^cum in vagina$",
        r"^cum overflow$", r"^cum dripping from pussy$",
    ),
    "cunnilingus": (
        r"^cunnilingus$", r"^licking pussy$", r"^licking vagina$",
        r"^mouth on pussy$", r"^tongue in pussy$",
    ),
    "vaginal_sex": (
        r"^penis in pussy$", r"^penis in vagina$", r"^vaginal sex$",
        r"^missionary$", r"^cowgirl position$", r"^doggystyle$",
        r"^sex from behind$", r"^pussy penetration$", r"^intercourse$",
    ),
}

# Explicit performed-action phrases in a Chinese script (strong evidence).
SCRIPT_STRONG_PATTERNS: dict[str, tuple[str, ...]] = {
    "blowjob": (
        r"含[住入]?[他的]?鸡巴", r"鸡巴含[入在]?", r"舔[他的]?龟头",
        r"深喉", r"吞吐[鸡巴]?", r"口交", r"吞[入咽下][了]?精",
        r"鸡巴整根吞", r"嘴[里中]含",
    ),
    "cum_shot": (
        r"颜射", r"射[在满][了]?[她]?.{0,6}(脸|面|胸|肚子|身)",
        r"喷[了满][她]?.{0,3}(脸|身|胸口)", r"精液[沾溅射][在满]",
        r"精液.{0,4}(半干|干涸|已干|干透|干了|干)",
        r"(沾着|沾|挂着|挂|残留|留着|留有|带).{0,4}(精液|白浊)",
        r"(精痕|精斑|精渍|干涸精)",
    ),
    "creampie": (
        r"内射", r"射[满进][了]?.{0,4}(逼|阴道|穴)",
        r"精液.{0,8}(溢出|溢流|涌出|喷出|迸出)",
        r"(大量)?精液.{0,3}(涌出|喷出|迸出)",
        r"射在逼里",
        r"逼口.{0,4}精", r"从逼口.{0,3}精",
    ),
    "cunnilingus": (
        r"舔[^，。；、,.]{0,4}逼",
        r"舔[她的]?阴", r"舔.{0,3}(阴唇|阴蒂|阴部|花穴)",
        r"埋[头首].{0,3}舔", r"口[水活].{0,3}舔",
    ),
    "vaginal_sex": (
        r"鸡巴.{0,2}插[入进]",
        r"阴茎.{0,3}(插[入进]|没入|进入|挺进|顶)",
        r"龟头[刚]?没入",
        r"(鸡巴|阴茎|肉棒).{0,6}(抽插|抽送|顶弄|挺送)",
        r"鸡巴.{0,3}抵.{0,3}逼口",
        r"阴茎.{0,4}(逼口|阴道口|穴口)",
        r"性交", r"后入", r"骑乘", r"疯狂顶[弄撞]",
        r"挺[腰身].{0,3}(插|顶|送)",
    ),
}

# Clauses where an insertion/thrusting verb is present. Vaginal intercourse
# requires the male/penis as the actor and a vaginal/coital action; finger
# verbs are masturbation and oral "swallow" must not count as penetration.
_PENETRATION_VERB_RE = re.compile(
    r"(插[入进]|抽插|抽送|顶弄|挺送|没入|进入|"
    r"纳入|套入|坐沉|沉腰|沉入)")
_ORAL_SWALLOW_RE = re.compile(r"(吞[入咽]|含[入住]?)")
_VAGINAL_CONTEXT_RE = re.compile(r"(阴道|逼|穴|阴户|下体|腰|胯|交合|骑)")
_PENIS_ACTOR_RE = re.compile(r"(鸡巴|阴茎|肉棒|龟头|男主)")
_FINGER_ACTOR_RE = re.compile(r"(手指|两指|两根手指|指尖|指头)")
_CLAUSE_SPLIT_RE = re.compile(r"[，。；、,.\n]")

# Broader, still action-specific phrases (any topic reference at all,
# including dialogue or nouns). Presence suppresses the contamination flag.
SCRIPT_WEAK_PATTERNS: dict[str, tuple[str, ...]] = {
    "blowjob": (
        r"口交", r"含.{0,3}鸡巴", r"鸡巴.{0,3}(嘴|口|唇|喉)",
        r"(嘴|唇|口).{0,4}鸡巴", r"舔.{0,3}龟头", r"深喉", r"吞吐",
        r"吞[入咽].{0,3}精",
    ),
    "cum_shot": (
        r"颜射", r"射.{0,6}(脸|面)", r"喷.{0,4}(脸|面|一身)",
        r"精液.{0,4}(脸|面|胸)",
        r"精液.{0,4}(半干|干涸|已干|干透|干了|干)",
        r"(沾着|沾|挂着|挂|残留|留着|留有).{0,4}(精液|白浊)",
        r"(精痕|精斑|精渍|干涸精)",
    ),
    "creampie": (
        r"内射", r"射.{0,3}(逼|阴道|穴)", r"精液.{0,8}(溢出|溢流)",
        r"逼里", r"逼口.{0,4}精",
    ),
    "cunnilingus": (
        r"舔.{0,3}(逼|阴|阴唇|阴蒂|阴部|花穴)", r"舔[舐弄]",
        r"(嘴|舌|唇).{0,3}(逼|阴|阴部)", r"口[水活]",
    ),
    "vaginal_sex": (
        r"做[爱]", r"性交", r"抽插", r"鸡巴.{0,3}插", r"插入.{0,3}(阴道|逼|穴)",
        r"阴茎.{0,2}插", r"(顶|挺).{0,3}(插|弄|送)", r"骑乘", r"跨坐.{0,3}插",
        r"龟头.{0,3}没入", r"(抵|插).{0,3}逼口",
    ),
}


# ---------------------------------------------------------------------------
# Presence (who is in the shot). This is orthogonal to action category and is
# the master gate: a later action cannot happen before its character exists.
# ---------------------------------------------------------------------------

FEMALE_TOKENS = (
    "1girl", "女主", "女孩", "少女", "她",
)
MALE_TOKENS_EN = (
    "1boy", "male", "boy", "man",
)
MALE_TOKENS_ZH = (
    "男主", "男人", "男生", "男孩",
)
# Body parts / nouns that, without a male token, are only references and must
# not by themselves prove the male is present.
_MENTION_ONLY_RE = re.compile(
    r"(他的|鸡巴|阴茎|肉棒|龟头|男主|男人|男生|男孩)")


def _tokens(text: str) -> set[str]:
    return {t.strip().lower() for t in re.split(r"[\s,，、]+", str(text or ""))
            if t.strip()}


def male_is_present(*, cast: str = "", present_characters: Any = None,
                    text: str = "") -> bool:
    """Whether the male is actually present in a shot.

    Requires an explicit male token in the cast/present_characters, or an
    explicit male actor in the text. A bare body-part mention inside a
    female-only clause is not enough.
    """
    cast_tokens = _tokens(cast)
    if any(tok in cast_tokens for tok in MALE_TOKENS_EN):
        return True
    for item in (present_characters or []):
        low = str(item).strip().lower()
        if low in MALE_TOKENS_EN or any(t in low for t in MALE_TOKENS_ZH):
            return True
    for token in MALE_TOKENS_ZH:
        if token in str(text):
            return True
    if re.search(r"\b(1boy|male|boy|man)\b", str(text).lower()):
        return True
    return False


def female_is_present(*, cast: str = "", text: str = "") -> bool:
    tokens = _tokens(cast)
    if any(tok in tokens for tok in ("1girl", "girl")):
        return True
    return any(tok in str(text) for tok in ("女主", "女孩", "少女", "她"))


def _prompt_tags(prompt: str) -> list[str]:
    return [tag.strip().lower() for tag in str(prompt or "").split(",")
            if tag.strip()]



def prompt_action_categories(prompt: str) -> set[str]:
    """High-salience action categories asserted by the English prompt tags."""
    categories: set[str] = set()
    for tag in _prompt_tags(prompt):
        for category, patterns in PROMPT_ACTION_TAGS.items():
            if any(re.search(pattern, tag) for pattern in patterns):
                categories.add(category)
    return categories


def _script_categories(script: str,
                       table: dict[str, tuple[str, ...]]) -> set[str]:
    text = str(script or "")
    return {category for category, patterns in table.items()
            if any(re.search(pattern, text) for pattern in patterns)}


# Semen landing on a body surface (face/chest/stomach) is strong evidence
# an external cumshot already happened.
_BODY_SURFACE_RE = re.compile(
    r"(脸|面|胸口|胸|小腹|肚子|腹部|肚|身[上体]|大腿|腿)")
_SEMEN_LANDING_RE = re.compile(r"(精液|白浊)")
_SEMEN_LANDING_VERB_RE = re.compile(
    r"(喷溅|喷[在到满溅]|溅[在着到满]|射[在满到]|"
    r"沾满?|沾[在满]|溅到|喷到)")


def _has_external_cumshot(text: str) -> bool:
    semen_seen = False
    for clause in _CLAUSE_SPLIT_RE.split(str(text or "")):
        if _SEMEN_LANDING_RE.search(clause):
            semen_seen = True
        landing = _SEMEN_LANDING_VERB_RE.search(clause)
        surface = _BODY_SURFACE_RE.search(clause)
        oral = _ORAL_CONTEXT_RE.search(clause)
        if landing and surface and (semen_seen or _SEMEN_LANDING_RE.search(clause)):
            if oral and not re.search(
                    r"(脸|胸口|胸|小腹|肚子|腹部|身|大腿|腿)", clause):
                continue
            return True
    return False


# Semen flowing/ejaculated from the vagina is strong evidence ejaculation
# already happened internally. Detection is source-aware (must reference a
# vaginal source), so oral semen or residual touch is not mistaken for it.
_VAGINAL_SOURCE_RE = re.compile(r"(阴道口|阴道|逼口|穴口|穴内|体内|阴部|阴户)")
_SEMEN_FLOW_RE = re.compile(r"(精液|白浊)")
_SEMEN_DIRECTION_RE = re.compile(
    r"(涌出|汩汩涌出|喷出|迸出|溢出|溢流|流出|往外流|灌满|射出|喷溅)")
_ORAL_CONTEXT_RE = re.compile(r"(嘴[角里]|口[腔内]|喉咙|下巴)")


def _has_internal_ejaculation(text: str) -> bool:
    source = _VAGINAL_SOURCE_RE.search(str(text or ""))
    if not source:
        return False
    after = str(text or "")[source.start():]
    before = str(text or "")[:source.start()]
    if _SEMEN_DIRECTION_RE.search(after) and _SEMEN_FLOW_RE.search(after):
        return True
    if _SEMEN_FLOW_RE.search(before) and _SEMEN_DIRECTION_RE.search(after):
        return True
    return False


def _has_penile_penetration(text: str) -> bool:
    penis_seen = False
    for clause in _CLAUSE_SPLIT_RE.split(str(text or "")):
        has_verb = bool(_PENETRATION_VERB_RE.search(clause))
        has_penis = bool(_PENIS_ACTOR_RE.search(clause))
        has_finger = bool(_FINGER_ACTOR_RE.search(clause))
        is_oral = bool(_ORAL_SWALLOW_RE.search(clause)) and not bool(
            _VAGINAL_CONTEXT_RE.search(clause))
        if has_penis and not is_oral:
            penis_seen = True
        if has_verb and not is_oral:
            if has_penis or (penis_seen and not has_finger):
                return True
            if has_finger and not has_penis:
                penis_seen = False
    return False


def performed_action_categories(text: str) -> set[str]:
    """High-salience actions asserted as performed by a Chinese text."""
    categories = _script_categories(text, SCRIPT_STRONG_PATTERNS)
    if _has_penile_penetration(text):
        categories.add("vaginal_sex")
    if _has_internal_ejaculation(text):
        categories.add("creampie")
    if _has_external_cumshot(text):
        categories.add("cum_shot")
    return categories


def contaminated_action_categories(prompt: str, script: str) -> set[str]:
    """Prompt-asserted actions that the script never performs or references."""
    asserted = prompt_action_categories(prompt)
    if not asserted:
        return set()
    performed = performed_action_categories(script)
    weak = _script_categories(script, SCRIPT_WEAK_PATTERNS)
    return asserted - performed - weak
