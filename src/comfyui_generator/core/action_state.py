"""Action semantics: who does what to which target.

The software never authors semantics. It only *recognizes* high-salience
actions so it can (a) verify a shot stays inside the milestone that owns
the action and (b) check that English prompt tags are backed by the script.

Recognition is data-driven. Each action is declared ONCE as a semantic
specification: the actor that performs it, the target it acts on, and the
verbs that express it. Every classifier is derived from that single table,
so there is no duplicated, hand-synced regex to drift apart.

An action counts as *performed* only when the text asserts it really
happens. Words that merely mention an action inside a negation ("无性交"),
an intention/dialogue ("祈求…做爱"), or with a non-matching target
("手指插入发丝", "阴茎插入口中") do not count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Lexical building blocks. These describe roles/targets, never story content.
# ---------------------------------------------------------------------------

# Male / penis actors vs. the female's own hand (masturbation).
_PENIS_ACTOR = r"(?:鸡巴|阴茎|肉棒|龟头|肉棍|阳具)"
_MALE_PERSON = r"(?:男主|男人|男生|男孩)"
_MALE_ACTOR = r"(?:%s|%s)" % (_PENIS_ACTOR, _MALE_PERSON)
_FINGER_ACTOR = r"(?:手指|两根手指|两指|指尖|指头|中指|无名指|指腹)"

# Targets.
_VAGINA_TARGET = r"(?:阴道口|阴道|逼|穴|肉穴|小穴|穴口|逼口|花穴|阴户|下体|私处)"
_MOUTH_TARGET = r"(?:嘴|嘴里|口中|口里|唇|口腔|喉咙|喉|口内)"
_HAIR_TARGET = r"(?:发丝|头发|发间)"
_BODY_SURFACE = r"(?:脸|面|面容|胸口|胸|乳房|乳头|双乳|乳|小腹|肚子|腹部|肚|身上|一身|大腿|腿)"

# Insertion / thrusting verbs and other action verbs.  "吞入" is NOT here
# because it is ambiguous (oral vs vaginal) and must be bound to a vaginal
# target explicitly; see vaginal_sex phrases.
_INSERT_VERB = r"(?:插[入进]|没入|进入|挺进|顶入|塞入|送入|纳入|套入)"
_THRUST_VERB = r"(?:抽插|抽送|顶弄|挺送|顶撞|律动)"
_ORAL_VERB = r"(?:吞[咽下]?|含[入住咽]?|吸吮|吮吸|吞吐)"
_LICK_VERB = r"(?:舔[了着过]?|舔弄|舔舐|口[水活])"
# Ejaculation / semen movement.
_EJAC_VERB = r"(?:射精|射[出在满到进]?|喷[出溅在到满]?|迸出|涌出|溢出|溢流|流出|灌满|射出|溅[在着到满])"
_SEMEN = r"(?:精液|白浊)"


@dataclass(frozen=True)
class ActionSpec:
    """Structural declaration of one recognizable action."""

    # Phrases that assert the action. Patterns bind actor/action/target by
    # semantics rather than a fixed word window, so flexible Chinese word
    # order is still recognized.
    phrases: tuple[str, ...]
    # Whole English Booru tags asserting the same action.
    tags: tuple[str, ...] = ()
    # Phrases that only show the *trace/residue* of an action (e.g. dried
    # semen on skin). These back the corresponding tag but do not assert the
    # action is happening now.
    residual: tuple[str, ...] = ()


# Single source of truth.
ACTION_SPECS: dict[str, ActionSpec] = {
    "blowjob": ActionSpec(
        phrases=(
            rf"深喉|口交",
            # penis ... mouth target (either order) within a clause
            rf"{_PENIS_ACTOR}[^，。；、,.\n]{{0,10}}{_MOUTH_TARGET}",
            rf"{_MOUTH_TARGET}[^，。；、,.\n]{{0,8}}{_PENIS_ACTOR}",
            rf"{_PENIS_ACTOR}[^，。；、,.\n]{{0,6}}{_ORAL_VERB}",
            rf"{_ORAL_VERB}[^，。；、,.\n]{{0,6}}{_PENIS_ACTOR}",
        ),
        tags=(
            r"^cum in mouth$", r"^swallowing cum$", r"^swallowing semen$",
            r"^fellatio$", r"^penis in mouth$", r"^deepthroat$", r"^blowjob$",
        ),
    ),
    "cum_shot": ActionSpec(
        phrases=(
            rf"颜射",
            # semen + ejaculation/splash verb + body surface; a verb is
            # required so mere co-occurrence ("阴茎…男主面前") cannot fire.
            rf"{_SEMEN}[^。\n]{{0,24}}{_EJAC_VERB}[^。\n]{{0,12}}{_BODY_SURFACE}",
            rf"{_PENIS_ACTOR}[^。\n]{{0,24}}{_EJAC_VERB}[^。\n]{{0,12}}{_BODY_SURFACE}",
            # body surface + splash/cover verb + semen (surface-first order)
            rf"{_BODY_SURFACE}[^。\n]{{0,12}}(?:{_EJAC_VERB})[^。\n]{{0,8}}{_SEMEN}",
            rf"{_BODY_SURFACE}[^。\n]{{0,12}}(?:溅[着到在上]|沾[满在着]|喷[到在上溅])[^。\n]{{0,8}}{_SEMEN}",
        ),
        tags=(
            r"^cum on face$", r"^facial$", r"^cum on breasts?$",
            r"^cum on stomach$", r"^cum on body$", r"^cum in hair$",
        ),
        residual=(
            # body surface carrying semen/white-turbid residue, allowing a
            # connector such as 沾着/沾/溅上 between surface and semen word
            rf"{_BODY_SURFACE}[^，。；、,.\n]{{0,6}}(?:沾[着了]?|溅[上到在着]?|残留|留有|有)[^，。；、,.\n]{{0,4}}(?:{_SEMEN}|精痕|精斑|精渍)",
            # body surface carrying semen/white-turbid residue, any order
            rf"{_BODY_SURFACE}[^，。；、,.\n]{{0,10}}(?:{_SEMEN}|精痕|精斑|精渍)",
            rf"(?:{_SEMEN}|精痕|精斑|精渍)[^，。；、,.\n]{{0,10}}{_BODY_SURFACE}",
            # staleness words with semen, e.g. 精液半干 / 干涸精痕
            rf"(?:{_SEMEN})[^，。；、,.\n]{{0,6}}(?:半干|干涸|已干|干透|干了)",
            rf"(?:干涸?|半干)[^，。；、,.\n]{{0,4}}(?:{_SEMEN}|精)",
        ),
    ),
    "creampie": ActionSpec(
        phrases=(
            rf"内射",
            # semen movement out of vagina; source may be named before or
            # after within the same clause
            rf"{_SEMEN}[^，。；、,.\n]{{0,12}}(?:涌出|汩汩[涌流]出|喷出|迸出|溢出|溢流|流出)",
            rf"{_VAGINA_TARGET}[^，。；、,.\n]{{0,10}}{_SEMEN}[^，。；、,.\n]{{0,8}}(?:涌出|喷出|溢出|迸出|流出)",
            rf"{_PENIS_ACTOR}[^，。；、,.\n]{{0,6}}(?:射[入满进]?|射精)[^，。；、,.\n]{{0,8}}{_VAGINA_TARGET}",
        ),
        tags=(
            r"^creampie$", r"^cum in pussy$", r"^cum in vagina$",
            r"^cum overflow$", r"^cum dripping from pussy$",
        ),
    ),
    "cunnilingus": ActionSpec(
        phrases=(
            rf"{_MALE_ACTOR}[^，。；、,.\n]{{0,8}}{_LICK_VERB}[^，。；、,.\n]{{0,6}}{_VAGINA_TARGET}",
            rf"埋[头首][^，。；、,.\n]{{0,4}}{_LICK_VERB}",
            rf"{_VAGINA_TARGET}[^，。；、,.\n]{{0,6}}{_LICK_VERB}",
        ),
        tags=(
            r"^cunnilingus$", r"^licking pussy$", r"^licking vagina$",
            r"^mouth on pussy$", r"^tongue in pussy$",
        ),
    ),
    "vaginal_sex": ActionSpec(
        phrases=(
            # penis + insertion verb with vaginal target, allowing the shot's
            # commas between them (whole-shot window, not single clause)
            rf"{_PENIS_ACTOR}[^。\n]{{0,40}}{_INSERT_VERB}[^。\n]{{0,12}}{_VAGINA_TARGET}",
            rf"{_VAGINA_TARGET}[^。\n]{{0,40}}{_PENIS_ACTOR}[^。\n]{{0,12}}{_INSERT_VERB}",
            rf"{_VAGINA_TARGET}[^。\n]{{0,20}}{_INSERT_VERB}",
            # "将阴茎整根吞入" counts as coitus only when a vaginal target was
            # named earlier in the same shot (oral 吞入 without it stays blowjob)
            rf"{_VAGINA_TARGET}[^。\n]{{0,60}}吞入",
            # penis + insertion verb even when the target is implicit, e.g.
            # "阴茎没入" (penis entering is itself the coital signal)
            rf"{_PENIS_ACTOR}[^。\n]{{0,6}}{_INSERT_VERB}",
            # penis thrusting; actor may be in a preceding clause
            rf"{_PENIS_ACTOR}[^。\n]{{0,40}}{_THRUST_VERB}",
            rf"(?:{_MALE_PERSON})[^。\n]{{0,40}}{_THRUST_VERB}",
            # bare nouns accepted only when a penis/male actor is also present
            rf"{_PENIS_ACTOR}[^。\n]{{0,16}}(?:后入|骑乘|性交)",
            rf"{_MALE_PERSON}[^。\n]{{0,16}}(?:后入|骑乘|性交)",
        ),
        tags=(
            r"^penis in pussy$", r"^penis in vagina$", r"^vaginal sex$",
            r"^missionary$", r"^cowgirl position$", r"^doggystyle$",
            r"^sex from behind$", r"^pussy penetration$", r"^intercourse$",
        ),
    ),
}



# Compile every phrase once.
_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    category: tuple(re.compile(p) for p in spec.phrases)
    for category, spec in ACTION_SPECS.items()
}
_RESIDUAL_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    category: tuple(re.compile(p) for p in spec.residual)
    for category, spec in ACTION_SPECS.items()
}


# ---------------------------------------------------------------------------
# Context masking. Before recognition, remove text where an action word does
# not assert performance: negations and intentions/dialogue.
# ---------------------------------------------------------------------------

_NEGATION_RE = re.compile(
    r"(?:无|没有|并未|并无|未|不是|并没有|还没有|尚未|毫不)"
    r"[^，。；、,.\n]{0,8}")

_INTRODUCER_RE = re.compile(
    r"(?:想|想要|希望|渴望|幻想|想象|脑补|期待|打算|计划|准备|预谋|暗自|心中|"
    r"祈求|哀求|恳求|请求|要求|求|低语|低声说|说|说道|问|叫|喊|呢喃|低吟)"
    r"[^，。；、,.\n]{0,10}")

# A span masked by one of these is replaced with neutral characters so that
# action words inside it cannot match.
def _mask_spans(text: str, regex: re.Pattern[str]) -> str:
    def blank(match: re.Match[str]) -> str:
        return "〇" * len(match.group(0))

    return regex.sub(blank, str(text or ""))


def _without_nonperforming_context(text: str) -> str:
    value = _mask_spans(text, _NEGATION_RE)
    value = _mask_spans(value, _INTRODUCER_RE)
    return value


# ---------------------------------------------------------------------------
# Presence (who is in the shot). Orthogonal to action category.
# ---------------------------------------------------------------------------

MALE_TOKENS_EN = ("1boy", "male", "boy", "man")
MALE_TOKENS_ZH = ("男主", "男人", "男生", "男孩")


def _tokens(text: str) -> set[str]:
    return {t.strip().lower() for t in re.split(r"[\s,，、]+", str(text or ""))
            if t.strip()}


def male_is_present(*, cast: str = "", present_characters=None,
                    text: str = "") -> bool:
    """Whether the male is actually present (explicit token required)."""
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


# ---------------------------------------------------------------------------
# Public classifiers.
# ---------------------------------------------------------------------------

def _prompt_tags(prompt: str) -> list[str]:
    return [tag.strip().lower() for tag in str(prompt or "").split(",")
            if tag.strip()]


def prompt_action_categories(prompt: str) -> set[str]:
    """High-salience actions asserted by English Booru tags."""
    categories: set[str] = set()
    for tag in _prompt_tags(prompt):
        for category, spec in ACTION_SPECS.items():
            if any(re.search(pattern, tag) for pattern in spec.tags):
                categories.add(category)
    return categories


def residual_action_categories(text: str) -> set[str]:
    """Actions whose residue/trace is present (e.g. dried semen on skin)."""
    cleaned = _without_nonperforming_context(text)
    categories: set[str] = set()
    for category, patterns in _RESIDUAL_COMPILED.items():
        if any(pattern.search(cleaned) for pattern in patterns):
            categories.add(category)
    return categories


def performed_action_categories(text: str) -> set[str]:
    """Actions a Chinese text asserts as really performed."""
    cleaned = _without_nonperforming_context(text)
    categories: set[str] = set()
    for category, patterns in _COMPILED.items():
        if any(pattern.search(cleaned) for pattern in patterns):
            categories.add(category)
    return categories


def contaminated_action_categories(prompt: str, script: str) -> set[str]:
    """Prompt tags whose action the script never performs, shows, or references."""
    asserted = prompt_action_categories(prompt)
    if not asserted:
        return set()
    performed = performed_action_categories(script)
    residual = residual_action_categories(script)
    # A mere mention (dialogue/noun) in the script also clears the tag.
    referenced: set[str] = set()
    for category, spec in ACTION_SPECS.items():
        if category in performed or category in residual:
            continue
        if any(re.search(p, script) for p in spec.phrases):
            referenced.add(category)
    return asserted - performed - residual - referenced
