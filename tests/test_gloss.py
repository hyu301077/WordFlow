from wordflow.gloss import conflicts, forbidden_norms, short_gloss


def test_short_gloss_keeps_real_segments():
    assert short_gloss("放弃；抛弃") == "放弃；抛弃"
    assert short_gloss("语言") == "语言"
    assert short_gloss("no chinese here") is None


def test_conflict_detects_same_meaning():
    blocked = forbidden_norms(["放弃；抛弃", "放任"])
    assert conflicts("放弃", blocked)
    assert conflicts("抛弃", blocked)
    assert not conflicts("接受；同意", blocked)
