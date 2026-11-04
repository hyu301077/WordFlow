from wordflow.lemma import heuristic_lemma


def has(words):
    return lambda candidate: candidate in words


def test_running_maps_to_run_only_when_unique():
    assert heuristic_lemma("running", has({"run"})) == "run"


def test_studies_and_making_and_stopped():
    known = {"study", "make", "stop", "apple"}
    assert heuristic_lemma("studies", has(known)) == "study"
    assert heuristic_lemma("studied", has(known)) == "study"
    assert heuristic_lemma("making", has(known)) == "make"
    assert heuristic_lemma("stopped", has(known)) == "stop"
    assert heuristic_lemma("apples", has(known)) == "apple"


def test_ambiguous_or_unknown_stay_separate():
    known = {"leaf", "leave", "the", "run"}
    assert heuristic_lemma("leaves", has(known)) == "leaves"
    assert heuristic_lemma("thing", has(known)) == "thing"
    assert heuristic_lemma("xyzzy", has(known)) == "xyzzy"


def test_irregular_only_if_target_exists():
    assert heuristic_lemma("went", has({"go"})) == "go"
    assert heuristic_lemma("went", has(set())) == "went"
