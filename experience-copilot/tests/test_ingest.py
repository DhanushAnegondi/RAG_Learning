"""Source-tag labeling — pure, no key."""
import os

from copilot.ingest import _experience_label


def test_label_from_top_folder():
    cp = os.path.join("base", "corpus")
    assert _experience_label(os.path.join(cp, "Rocket", "Rocket_KB_01.md"), cp) == "Rocket"


def test_label_maps_interview_subfolder_to_employer():
    cp = os.path.join("base", "corpus")
    src = os.path.join(cp, "interview", "Rocket", "stories", "ticket.md")
    assert _experience_label(src, cp) == "Rocket"


def test_label_for_cognizant():
    cp = os.path.join("base", "corpus")
    assert _experience_label(os.path.join(cp, "Cognizant", "x.md"), cp) == "Cognizant"
