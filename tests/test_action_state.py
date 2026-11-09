from comfyui_generator.core.action_state import (
    contaminated_action_categories,
    performed_action_categories,
    prompt_action_categories,
)


def test_prompt_action_categories_detects_high_salience_tags():
    cats = prompt_action_categories(
        "1girl, penis in mouth, cum in mouth, deepthroat, smile")
    assert cats == {"blowjob"}


def test_clean_shot_has_no_contamination():
    prompt = "1girl, 1boy, nude male, penis in mouth, deepthroat"
    script = "yixuan蹲下含住他的鸡巴，深喉吞吐"
    assert contaminated_action_categories(prompt, script) == set()


def test_cross_stage_tag_is_contamination():
    prompt = "1girl, 1boy, nude male, cunnilingus, cum in mouth, swallowing"
    script = "男主埋头舔yixuan的逼，她仰头浪叫"
    assert contaminated_action_categories(prompt, script) == {"blowjob"}


def test_dialogue_mention_suppresses_contamination():
    prompt = "1girl, 1boy, nude male, penis in pussy, missionary"
    script = "她哭着说想做爱，男主把鸡巴插进她阴道抽插"
    assert contaminated_action_categories(prompt, script) == set()


def test_sex_insertion_moment_is_not_contamination():
    prompt = "1girl, 1boy, nude male, penis at entrance, penis in pussy"
    script = "她引导鸡巴抵住湿漉漉的逼口，男主挺腰，龟头刚没入"
    assert contaminated_action_categories(prompt, script) == set()


def test_creampie_aftermath_is_not_contamination():
    prompt = (
        "1girl, 1boy, nude male, creampie, cum overflow, "
        "cum dripping from pussy")
    script = "精液从逼口不断溢出，小腹和胸口沾着精液斑点"
    assert contaminated_action_categories(prompt, script) == set()


def test_no_action_tags_means_no_contamination():
    assert contaminated_action_categories(
        "1girl, solo, smile, classroom", "独处寂寞") == set()


def test_half_dried_cum_on_breasts_is_residual_not_contamination():
    assert contaminated_action_categories(
        "1girl, cum on breasts, dried cum", "双乳精液半干") == set()


def test_smeared_cum_on_breasts_is_residual_not_contamination():
    assert contaminated_action_categories(
        "1girl, cum on breasts", "双乳沾着白浊") == set()


def test_cum_stains_residual_not_contamination():
    assert contaminated_action_categories(
        "1girl, cum on stomach", "小腹留有干涸精痕") == set()


def test_cum_on_bodypart_without_evidence_is_still_contamination():
    assert contaminated_action_categories(
        "1girl, cum on breasts", "独处寂寞") == {"cum_shot"}


def test_oral_residual_is_still_strictly_contamination():
    assert contaminated_action_categories(
        "1girl, cunnilingus, cum in mouth, swallowing",
        "男主埋头舔逼") == {"blowjob"}


def test_negated_action_words_are_not_performed():
    assert performed_action_categories("手指揉阴，无性交。") == set()
    assert performed_action_categories("前戏，没有口交。") == set()
    assert performed_action_categories("她继续自慰，并未射精。") == set()


def test_affirmed_actions_still_performed():
    assert "vaginal_sex" in performed_action_categories(
        "男主鸡巴"
        "插入阴道，阴茎没入。")
    assert "creampie" in performed_action_categories(
        "男主内射，精液溢出。")


def test_penis_near_body_word_without_ejaculation_is_not_cum_shot():
    text = ("女主蹲在男主面前握住阴茎，伸舌舔弄后含入龟头缓慢吞吐，"
            "男主手悬在她头顶，腿部局部入镜")
    cats = performed_action_categories(text)
    assert "blowjob" in cats
    assert "cum_shot" not in cats

