"""Pronunciation overrides. Loads the voice model; skipped where models/ isn't set up."""
import pytest

from scotus import MODELS

pytestmark = pytest.mark.skipif(not (MODELS / "voices-v1.0.bin").exists(), reason="voice models not downloaded")


@pytest.fixture(scope="module")
def synth():
    from scotus.tts import Synth
    return Synth()


@pytest.mark.parametrize("text,expected", [
    ("Justice Kagan", "kˈeɪɡən"),
    ("Justice Kagan’s dissent", "kˈeɪɡənz"),
    ("Justice Sotomayor", "sˌoʊtoʊmaɪˈɔːɹ"),
    ("JUSTICE SOTOMAYOR's view", "sˌoʊtoʊmaɪˈɔːɹz"),
    ("We granted certiorari.", "sˌɜːʃioʊɹˈɑːɹi"),
    ("The syllabus", "sˈɪləbəs"),
    ("rehearing en banc", "ɑːn bˈɑːŋk"),
    ("The court, sitting En Banc, reversed.", "ɑːn bˈɑːŋk"),
])
def test_lexicon(synth, text, expected):
    assert expected in synth.phonemes(text)


def test_initialisms_have_no_pauses(synth):
    assert "." not in synth.phonemes("His {IQ} scores")
