import json

from comfyui_generator.core import story_blueprint as sb


PREMISE = (
    "角色：yixuan\n初始服装：hairclip(1.2), black blazer\n"
    "剧情：\n1.独处\n2.做爱\n3.射精收尾\n其它：夜晚")


def test_milestone_titles_parsed_in_order():
    titles = sb._milestone_titles(PREMISE)
    assert titles == ["独处", "做爱", "射精收尾"]


def test_valid_blueprint_passes():
    milestones = [
        {"index":1,"title":"独处","start":1,"end":15,"terminal":False},
        {"index":2,"title":"做爱","start":16,"end":40,"terminal":False},
        {"index":3,"title":"射精收尾","start":41,"end":50,"terminal":True},
    ]
    assert sb.blueprint_violations(milestones,50) == []


def test_terminal_early_flagged():
    milestones = [
        {"index":1,"title":"射精","start":1,"end":11,"terminal":True},
        {"index":2,"title":"more","start":12,"end":50,"terminal":False},
    ]
    issues = sb.blueprint_violations(milestones,50)
    assert any("终局" in i for i in issues)


def test_gap_and_overlap_flagged():
    milestones = [
        {"index":1,"title":"a","start":1,"end":20,"terminal":False},
        {"index":2,"title":"b","start":25,"end":50,"terminal":True},
    ]
    assert any("连续" in i for i in sb.blueprint_violations(milestones,50))


def test_plan_shot_blueprint_retries_until_valid():
    good = {"milestones":[
        {"index":1,"title":"a","start":1,"end":25,"terminal":False},
        {"index":2,"title":"end","start":26,"end":50,"terminal":True}]}
    bad = {"milestones":[
        {"index":1,"title":"end","start":1,"end":11,"terminal":True},
        {"index":2,"title":"more","start":12,"end":50,"terminal":False}]}

    class C:
        def __init__(self): self.queue=[bad,good]
        def chat_json(self,*a,**k): return self.queue.pop(0)

    out = sb.plan_shot_blueprint(C(),"m",PREMISE,50,max_tries=2)
    assert sb.blueprint_violations(out,50) == []
    assert out[-1]["end"]==50 and out[-1]["terminal"]


def test_blueprint_text_mentions_ranges_and_terminal():
    milestones=[
        {"index":1,"title":"a","start":1,"end":25,"terminal":False},
        {"index":2,"title":"end","start":26,"end":50,"terminal":True}]
    text=sb.blueprint_text(milestones)
    assert "镜01-25" in text and "终局" in text
