import pytest

from scotus.speak import heading, speakable


@pytest.mark.parametrize("text,expected", [
    ("KAVANAUGH, J., delivered the opinion of the Court, in which ROBERTS, C. J., and THOMAS, ALITO, GORSUCH, and BARRETT, JJ., joined.",
     "Justice Kavanaugh delivered the opinion of the Court, in which Chief Justice Roberts and Justices Thomas, Alito, Gorsuch, and Barrett joined."),
    ("Thomas, J., joined as to all but Part III–C.", "Justice Thomas joined as to all but Part Three C."),
    ("Under Title IX and Article III, pages 367–374, a 6-to-1 delegation.",
     "Under Title Nine and Article Three, pages 367 to 374, a 6 to 1 delegation."),
    # initialisms become {LETTERS} for tts.py to spell, without pauses from periods
    ("His I.Q. scores were low. The U. S. Court agreed.", "His {IQ} scores were low. The {US} Court agreed."),
    ("Smith went to the U. S.", "Smith went to the {US}."),
    ("The NCAA and the NAACP.", "The {NCAA} and the NAACP."),
    ("B. P. J. v. West Virginia", "{BPJ} versus West Virginia"),
    ("sections §§18–2–25d stay", "sections sections 18–2–25d stay"),
    ("“[t]he right”", "“the right”"),
])
def test_speakable(text, expected):
    assert speakable(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("I", "Part One"), ("III–C", "Part Three C"), ("B", "Section B"), ("* * *", ""), ("*", ""),
])
def test_heading(text, expected):
    assert heading(text) == expected
