from mp3sanitizer.core.diff import Seg, diff_segments


def _join(segs):
    return "".join(t for t, _ in segs)


def test_segments_reconstruct_both_strings():
    old, new = "queen - innuendo.mp3", "Queen - Innuendo (1991).mp3"
    o, n = diff_segments(old, new)
    assert _join(o) == old
    assert _join(n) == new


def test_marks_changed_parts():
    o, n = diff_segments("U.s.a", "U.S.A.")
    assert (Seg.REMOVED in {k for _, k in o}) and (Seg.ADDED in {k for _, k in n})
    assert [t for t, k in n if k is Seg.ADDED] == ["S", "A."]


def test_identical_and_empty():
    assert diff_segments("abc", "abc") == ([("abc", Seg.SAME)], [("abc", Seg.SAME)])
    assert diff_segments("", "x") == ([], [("x", Seg.ADDED)])
    assert diff_segments("", "") == ([], [])


def test_adjacent_segments_merged():
    o, n = diff_segments("ab", "xy")
    assert o == [("ab", Seg.REMOVED)]
    assert n == [("xy", Seg.ADDED)]


def test_word_level_marks_whole_words():
    o, n = diff_segments("a-ha - take on me", "a-ha - Take On Me")
    assert [t for t, k in o if k is Seg.REMOVED] == [
        "take",
        "on",
        "me",
    ]  # spaties ertussen zijn ongewijzigd
    assert [t for t, k in n if k is Seg.ADDED] == ["Take", "On", "Me"]
