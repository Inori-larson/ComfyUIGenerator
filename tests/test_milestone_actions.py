import json

from comfyui_generator.core.stages import (
    STALL_MIN_RUN,
    _action_signature,
    _action_stall_findings,
    _future_action_findings,
    _milestone_action_intro,
    _verify_outline_entry,
)

MILESTONES = [
    {"index": 1, "title": "女主独处，寂寞", "start": 1, "end": 2},
    {"index": 2, "title": "女主摸奶抠逼自慰", "start": 3, "end": 4},
    {"index": 3, "title": "女主抱住男主哭求", "start": 5, "end": 6},
    {"index": 4, "title": "女主口交含住鸡巴", "start": 7, "end": 8},
    {"index": 5, "title": "鸡巴插入阴道性交", "start": 9, "end": 10},
    {"index": 6, "title": "阴道内射，精液溢出", "start": 11, "end": 12,
     "terminal": True},
]


def test_milestone_action_intro_is_structural():
    intro = _milestone_action_intro(MILESTONES)
    assert intro["blowjob"] == 4
    assert intro["vaginal_sex"] == 5
    assert intro["creampie"] == 6


def test_early_text_with_later_action_is_flagged():
    findings = _future_action_findings(
        MILESTONES, 2, "男主抽插后内射，精液溢出")
    cats = {f["category"] for f in findings}
    assert cats == {"vaginal_sex", "creampie"}
    assert all(f["correct"] for f in findings)


def test_current_milestone_action_is_allowed():
    findings = _future_action_findings(
        MILESTONES, 5, "鸡巴插入阴道抽插")
    assert findings == []


def test_text_without_actions_is_not_flagged():
    findings = _future_action_findings(
        MILESTONES, 1, "她坐在窗边叹气，夜色很深")
    assert findings == []


def test_verify_outline_entry_rejects_premature_action():
    errors = _verify_outline_entry(
        MILESTONES, 3,
        {"milestone_index": 2,
         "outline": "男主把鸡巴插入阴道性交"})
    assert any("阴道性交" in e for e in errors)


def test_verify_outline_entry_passes_clean_early_beat():
    errors = _verify_outline_entry(
        MILESTONES, 3,
        {"milestone_index": 2,
         "outline": "她手指伸入内裤抚摸阴蒂自慰"})
    assert errors == []


def test_finger_insertion_masturbation_is_not_vaginal_sex():
    from comfyui_generator.core.action_state import performed_action_categories
    for text in (
        "女主将两根手指完全插入阴道，快速抽插",
        "她的手指深深插入穴内快速抽插，身体颤抖",
    ):
        assert "vaginal_sex" not in performed_action_categories(text)


def test_begging_for_sex_is_not_performed_sex():
    from comfyui_generator.core.action_state import performed_action_categories
    assert "vaginal_sex" not in performed_action_categories(
        "女主抱住男主，祈求男主和她做爱")


def test_male_actor_thrusting_is_vaginal_sex():
    from comfyui_generator.core.action_state import performed_action_categories
    assert "vaginal_sex" in performed_action_categories(
        "男主按住她的腰用力抽插")


def test_penis_swallowing_across_clauses_is_vaginal_sex():
    from comfyui_generator.core.action_state import performed_action_categories
    text = ("女主跨坐，一手扶住男主阴茎对准穴口，缓缓沉下腰，"
            "将阴茎整根吞入，两人呻吟")
    assert "vaginal_sex" in performed_action_categories(text)


def test_thrusting_after_penis_in_earlier_clause_is_vaginal_sex():
    from comfyui_generator.core.action_state import performed_action_categories
    text = ("男主把女主压在桌上，低头含住她左乳吸吮，"
            "腰部猛烈挺动抽插，淫水滴落")
    assert "vaginal_sex" in performed_action_categories(text)


def test_semen_bursting_after_penis_withdrawn_is_creampie():
    from comfyui_generator.core.action_state import performed_action_categories
    cats = performed_action_categories(
        "阴茎刚从穴内抽出，大量精液涌出，女主胸口溅满白浊")
    assert "creampie" in cats
    assert "vaginal_sex" not in cats


def test_oral_swallowing_penis_is_blowjob_not_vaginal_sex():
    from comfyui_generator.core.action_state import performed_action_categories
    for text in (
        "女主跪在讲台旁，将鸡巴整根吞入，鼻尖埋进男主小腹，喉咙呜咽",
        "女主低头将龟头含入嘴里，开始缓慢吞吐",
        "她将鸡巴吞到根部，鼻尖抵住小腹，深喉",
    ):
        cats = performed_action_categories(text)
        assert "blowjob" in cats
        assert "vaginal_sex" not in cats


def test_semen_gushing_from_vagina_is_creampie():
    from comfyui_generator.core.action_state import performed_action_categories
    text = "阴茎刚拔出，精液从无法闭合的阴道口汩汩涌出，沿股沟流到桌面"
    cats = performed_action_categories(text)
    assert "creampie" in cats


def test_semen_splashed_on_face_and_chest_is_cum_shot():
    from comfyui_generator.core.action_state import performed_action_categories
    cats = performed_action_categories("女主胸口和脸颊上溅着精液")
    assert cats == {"cum_shot"}


def test_squirting_is_not_semen_creampie():
    from comfyui_generator.core.action_state import performed_action_categories
    cats = performed_action_categories(
        "一股淫水从阴道口喷出，溅到男主脸上")
    assert "creampie" not in cats
    assert "cum_shot" not in cats


# ---------------------------------------------------------------------------
# Unified blueprint validation (presence + action), the root-cause fix.
# ---------------------------------------------------------------------------

FULL_MILESTONES = [
    {"index": 1, "title": "女主独处，寂寞", "start": 1, "end": 3},
    {"index": 2, "title": "女主看片自慰", "start": 4, "end": 8},
    {"index": 3, "title": "女主摸奶抠逼", "start": 9, "end": 14},
    {"index": 4, "title": "男主路过，撞见女主", "start": 15, "end": 19},
    {"index": 5, "title": "女主抱住男主祈求", "start": 20, "end": 23},
    {"index": 6, "title": "女主口交含鸡巴", "start": 24, "end": 28},
    {"index": 7, "title": "男主吃奶扣逼", "start": 29, "end": 33},
    {"index": 8, "title": "男主舔女主的逼，潮吹", "start": 34, "end": 38},
    {"index": 9, "title": "鸡巴插进阴道各种姿势", "start": 39, "end": 44},
    {"index": 10, "title": "疯狂抽插内射，精液溢出喷一身",
     "start": 45, "end": 50, "terminal": True},
]


def test_early_male_character_is_rejected():
    from comfyui_generator.core.stages import _shot_blueprint_findings
    findings = _shot_blueprint_findings(
        FULL_MILESTONES, 2,
        text="男主把女主按在桌上动手", cast="1girl 1boy")
    kinds = {f["kind"] for f in findings}
    assert "future_character" in kinds


def test_early_action_is_rejected_even_with_male_token():
    from comfyui_generator.core.stages import _shot_blueprint_findings
    findings = _shot_blueprint_findings(
        FULL_MILESTONES, 3,
        text="女主跨坐，阴茎没入，上下起伏", cast="1girl 1boy")
    cats = {f.get("category") for f in findings if f["kind"] == "future_action"}
    assert "vaginal_sex" in cats


def test_correct_actions_at_each_milestone_pass():
    from comfyui_generator.core.stages import _shot_blueprint_findings
    cases = {
        1: ("女主独自叹气", "1girl"),
        2: ("女主手指插入阴道抽插自慰", "1girl"),
        3: ("女主两指抠逼揉奶", "1girl"),
        4: ("男主站在门口", "1girl 1boy"),
        6: ("女主将鸡巴含入嘴里深喉", "1girl 1boy"),
        8: ("男主舔女主的逼，淫水喷到男主脸", "1girl 1boy"),
        9: ("男主鸡巴插进阴道，阴茎没入", "1girl 1boy"),
        10: ("男主内射，精液喷到女主胸口", "1girl 1boy"),
    }
    for mi, (text, cast) in cases.items():
        assert _shot_blueprint_findings(
            FULL_MILESTONES, mi, text=text, cast=cast) == []


def test_male_present_detection_requires_explicit_token():
    from comfyui_generator.core.action_state import male_is_present
    assert male_is_present(cast="1girl 1boy")
    assert male_is_present(text="男主伸手")
    assert not male_is_present(cast="1girl", text="她摸着他的鸡巴")


def test_semen_splashing_on_stomach_across_clauses_is_supported():
    from comfyui_generator.core.action_state import contaminated_action_categories
    script = ("肉棒深深顶入，精液猛烈射入阴道，过多精液从交合处溢出，"
              "喷溅在女主和大腿上")
    prompt = "1girl, creampie, cum overflow, cum on stomach, cum on thigh"
    assert contaminated_action_categories(prompt, script) == set()


def _stall_shots(n):
    return [{"id": "%02d" % i,
             "prompt": "pussy, wet pussy, penis in pussy, blush, detail%d" % i}
            for i in range(1, n + 1)]


def test_action_signature_extracts_core_actions():
    assert _action_signature("1girl, penis in pussy, smile") == frozenset(
        ["penis in pussy"])


def test_action_stall_detected_at_threshold():
    assert _action_stall_findings(_stall_shots(STALL_MIN_RUN))
    assert not _action_stall_findings(_stall_shots(STALL_MIN_RUN - 1))


def test_action_stall_breaks_when_action_changes():
    shots = _stall_shots(STALL_MIN_RUN)
    shots[-1]["prompt"] = "fellatio, penis in mouth"
    assert not _action_stall_findings(shots)


def test_action_stall_ignored_without_explicit_actions():
    shots = [{"id": "%02d" % i, "prompt": "1girl, smile, standing"}
             for i in range(STALL_MIN_RUN + 2)]
    assert not _action_stall_findings(shots)

