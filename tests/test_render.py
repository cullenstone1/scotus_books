import pytest

from scotus.render import justice_title, section_author


@pytest.mark.parametrize("title,expected", [
    ("CHIEF JUSTICE ROBERTS delivered the opinion of the Court.", "Chief Justice"),
    ("Chief Justice Roberts, dissenting.", "Chief Justice"),
    ("JUSTICE KAGAN, with whom THE CHIEF JUSTICE joins, dissenting.", "Justice"),   # the Chief joining isn't the author
    ("Justice Rehnquist, dissenting.", "Justice"),     # a later Chief, writing before becoming Chief
    ("PER CURIAM.", "Justice"),
])
def test_justice_title(title, expected):
    assert justice_title(title) == expected


@pytest.mark.parametrize("title,expected", [
    ("CHIEF JUSTICE ROBERTS delivered the opinion of the Court.", "roberts"),
    ("JUSTICE SOTOMAYOR, with whom JUSTICE KAGAN joins, dissenting.", "sotomayor"),
    ("Justice O’Connor, concurring.", "o'connor"),
    ("PER CURIAM.", None),
])
def test_section_author(title, expected):
    assert section_author(title) == expected
