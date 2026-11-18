"""Automatic backups older than storage.backup_retention_days are deleted at start-up (user
request 2026-11-18); everything else under data/ stays. No network."""

from datetime import UTC, datetime
from pathlib import Path

from jobmatch.backup_retention import remove_old_backups
from jobmatch.config import Settings

NOW = datetime(2026, 12, 20, 12, 0, tzinfo=UTC)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


def test_old_automatic_backups_go_the_rest_stays(tmp_path: Path) -> None:
    data = tmp_path / "data"
    backups = data / "backups"
    old = [
        touch(backups / "jobs.20261026T222031581326Z.csv"),
        touch(backups / "reviews.20261101T000000Z.csv"),
        touch(data / "contractors" / "backups" / "contractors.20261027T001848110168Z.csv"),
        touch(data / "eval" / "backups" / "blind_consensus.20261104T023736Z.csv"),
        touch(backups / "removed-judgments" / "20261111T210959Z-paste_1" / "abc.json").parent,
    ]
    kept = [
        touch(backups / "jobs.20261125T000000000000Z.csv"),  # 25 days old: kept
        touch(backups / "removed-judgments" / "20261201T000000Z-paste_2" / "a.json"),
        touch(backups / "llm_matches.before-detailed.20261106T221351Z.csv"),  # made by hand
        touch(backups / "notes.txt"),  # no timestamp
        touch(backups / "reset-20261021T005720Z" / "jobs.csv"),
        touch(backups / "cleanup-20261111T210959Z" / "data" / "x.csv"),
        touch(backups / "exports" / "do-good-talent-backup-20261001.zip"),
        touch(backups / "uploads" / "old.zip"),
        touch(data / "contractors" / "resumes" / "old" / "TAL-1-20261001T000000Z.pdf"),
        touch(data / "jobs.csv"),
    ]
    assert remove_old_backups(data, 30, now=NOW) == len(old)
    assert not any(p.exists() for p in old)
    assert all(p.exists() for p in kept)
    assert remove_old_backups(data, 30, now=NOW) == 0  # safe to run again


def test_missing_folders_are_fine(tmp_path: Path) -> None:
    assert remove_old_backups(tmp_path / "nothing", 30, now=NOW) == 0


def test_retention_is_configured(app_settings: Settings) -> None:
    assert app_settings.storage.backup_retention_days == 30
