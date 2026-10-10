"""Regression tests for citation removal. Each case is (input, expected cleaned text).

When the review report turns up a new mistake, add the offending paragraph here
with the output it should produce, then fix clean.py until everything passes.
"""
import pytest

from scotus.clean import clean_text
from scotus.extract import _join

CASES = [
    # full citation after a quote is its own sentence
    ("Phones are “an important feature of human anatomy.” Riley v. California, 573 U. S. 373, 385 (2014). Since then, ownership grew.",
     "Phones are “an important feature of human anatomy.” Since then, ownership grew."),
    # signal sentence with explanatory parenthetical and id.
    ("It grew. See, e.g., Carpenter v. United States, 585 U. S. 296, 304 (2018) (holding that CSLI is protected); id., at 310. It is so.",
     "It grew. It is so."),
    # case name used in the sentence is kept
    ("As we held in Carpenter, 585 U. S., at 310, the data is private.",
     "As we held in Carpenter, the data is private."),
    ("In Carpenter v. United States, 585 U. S. 296 (2018), the Court held that accessing CSLI is a search.",
     "In Carpenter v. United States, the Court held that accessing CSLI is a search."),
    # mid-sentence id. cite set off by commas after a quote
    ("“by governmental officials,” id., at 303, and it was designed",
     "“by governmental officials,” and it was designed"),
    # case name eyecite misses, after a quote ending with a period
    ("It was designed “to place obstacles in the way of police surveillance.” United States v. Di Re, 332 U. S. 581, 595 (1948); Carpenter, 585 U. S., at 305. Whatever the form.",
     "It was designed “to place obstacles in the way of police surveillance.” Whatever the form."),
    # record cites, supra, statutes as whole sentences
    ("It works. See Brief for Orin S. Kerr as Amicus Curiae 14 (Kerr Brief). See supra, at 610–611. Two years later, it grew.",
     "It works. Two years later, it grew."),
    ("The law specifies sex. §§18–2–25d(a)(4), (b)(1). The legislature found it necessary. See §§18–2–25d(a)(1), (3), (5).",
     "The law specifies sex. The legislature found it necessary."),
    # statutes used in prose are kept
    ("Section 2 of the Voting Rights Act, 52 U. S. C. §10301, prohibits it.",
     "Section 2 of the Voting Rights Act, 52 U. S. C. §10301, prohibits it."),
    # subsequent history glued onto a cite
    ("A court upheld it. Backus v. South Carolina, 857 F. Supp. 2d 553, 560 (SC), summarily aff’d, 568 U. S. 801 (2012). It follows.",
     "A court upheld it. It follows."),
    # blank page numbers in recent cites, ellipses kept
    ("It is “the outcome of . . . party control of Congress.” ___ F. 4th, at ___. Done.",
     "It is “the outcome of … party control of Congress.” Done."),
    ("Mootness justifies it. See also Chapman v. Doe, 598 U. S. –––, –––. Our system rests on it.",
     "Mootness justifies it. Our system rests on it."),
    # appendix and record cites ending in page letters
    ("It does better. J. S. A. Supp. 417a–418a, 420a. It found “dilution.” Supp. App. to Juris. Statement 174a. A remedy is plausible.",
     "It does better. It found “dilution.” A remedy is plausible."),
    # non-case sources: Constitution, treatises, legislative history
    ("They are “creatures of statute,” U. S. Const., Art. I, cl. 9, and they “depriv[e]” people of “life.” U. S. Const., Amdt. 5. It is so.",
     "They are “creatures of statute,” and they “depriv[e]” people of “life.” It is so."),
    ("It was the “exhaustive opinion,” Cong. Globe, 39th Cong., 1st Sess., 1116 (Rep. Wilson), and as the court held, it was law.",
     "It was the “exhaustive opinion,” and as the court held, it was law."),
    ("It was “the common law,” 1 H. Tucker, Commentaries on the Laws of Virginia 57–58. The court said so.",
     "It was “the common law.” The court said so."),
    ("Users said so. See W. Bishop, Pew Research Center, Mobile Fact Sheet (Nov. 20, 2025) (91%). That means they are addicted.",
     "Users said so. That means they are addicted."),
    # prose parentheticals are kept; citation parentheticals go
    ("They looked (such as a U. S. passport) too. (JUSTICE ALITO does the same—albeit for a different result.)",
     "They looked (such as a U. S. passport) too. (JUSTICE ALITO does the same—albeit for a different result.)"),
    ("And so (2014) it was (Diaz, C. J., concurring).",
     "And so it was."),
    ("The Attorney General disagreed. Secretary of State Hamilton Fish agreed. Id., at 4.",
     "The Attorney General disagreed. Secretary of State Hamilton Fish agreed."),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_clean(text, expected):
    assert clean_text(text) == expected


@pytest.mark.parametrize("a,b,expected", [
    ("track­", "and-field", "track-and-field"),
    ("va-", "catur", "vacatur"),
    ("racial-gerrymander-", "ing", "racial-gerrymandering"),
    ("cross-", "country", "cross-country"),
    ("so-", "called", "so-called"),
    ("every-", "one", "everyone"),
    ("367–", "374", "367–374"),
])
def test_dehyphenate(a, b, expected):
    assert _join(a, b) == expected
