"""The media/content skill terms added on 2026-10-26. Lines are from real postings or written
in their style."""

import pytest

from conftest import CONFIG_DIR
from jobmatch.config import load_skills_taxonomy
from jobmatch.normalize.skills import SkillExtractor

SKILLS = SkillExtractor(load_skills_taxonomy(CONFIG_DIR))


@pytest.mark.parametrize(
    ("text", "skills"),
    [
        (
            "Creates and maintains short, medium and long-term editorial schedules",
            ["editorial planning"],
        ),
        ("Gère le calendrier éditorial et la planification éditoriale", ["editorial planning"]),
        ("Copy editing and proofreading of all web content", ["copy editing"]),
        ("In-depth knowledge of lifestyle journalism", ["journalism"]),
        ("Journaliste avec expérience en salle de nouvelles", ["journalism"]),
        ("Integrated Producer", ["digital production"]),
        (
            "Productrice numérique, campagnes intégrées",
            ["digital production", "integrated marketing"],
        ),
        (
            "Video editing in Premiere; motion graphics in After Effects",
            ["video production", "motion graphics"],
        ),
        ("Montage vidéo et graphisme animé", ["video production", "motion graphics"]),
        (
            "Must be comfortable publishing in content management systems",
            ["content management systems"],
        ),
        ("Monitors traffic in Google Analytics", ["web analytics"]),
        ("Sr. Art Director/Designer", ["art direction"]),
        ("Directrice de création", ["creative direction"]),
        ("Senior Content Strategist", ["content strategy"]),
        (
            "Project Coordinator, Media Planner & Analytics Specialist",
            ["project management", "media planning"],
        ),
    ],
)
def test_new_media_skills(text: str, skills: list[str]) -> None:
    assert SKILLS.extract(text) == skills


@pytest.mark.parametrize(
    "text",
    [
        "Under the direction of the Managing Editor",  # "editor" alone is a role, not a skill
        "Senior Producer, CBC Life",  # bare "producer" is left to title similarity
        "Excellent analytical and numeracy skills",
        "Tracks spending against budget with the Production Manager",
    ],
)
def test_ambiguous_words_stay_out(text: str) -> None:
    assert not {
        "copy editing",
        "digital production",
        "web analytics",
        "content production",
    } & set(SKILLS.extract(text))
