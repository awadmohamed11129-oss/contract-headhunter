"""Delete the app's automatic backups older than storage.backup_retention_days, once at
start-up (user request 2026-11-18; the scope is the user's choice):

- data/backups/<table>.<timestamp>Z.<ext>: a CSV table's copy before it was rewritten;
- data/backups/removed-judgments/<timestamp>Z-<job>/: Gemini's results of a deleted job;
- data/contractors/backups/: the contractor list's copies before an import or an edit;
- data/eval/backups/: the evaluation file's copies.

Only names carrying the app's timestamp are considered, and the age is read from that
timestamp (a file copied or restored keeps its true age). Everything else is left alone:
exports and uploaded backups, reset-* and cleanup-* folders, résumé copies in
resumes/old/. The deletion is permanent. The log records counts only.
"""

import logging
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# "jobs.20261026T222031581326Z.csv", "blind_consensus.20261104T023736Z.csv"
_STAMPED_FILE = re.compile(r"^[^.]+\.(\d{8}T\d{6})\d*Z\.[A-Za-z0-9]+$")
# "20261111T210959Z-paste_1"
_STAMPED_DIR = re.compile(r"^(\d{8}T\d{6})\d*Z-")


def _stamp(match: re.Match[str] | None) -> datetime | None:
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _old_entries(data_dir: Path, cutoff: datetime) -> list[Path]:
    found: list[Path] = []
    for folder in (
        data_dir / "backups",
        data_dir / "contractors" / "backups",
        data_dir / "eval" / "backups",
    ):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.is_file() and not path.is_symlink():
                when = _stamp(_STAMPED_FILE.match(path.name))
                if when is not None and when < cutoff:
                    found.append(path)
    judgments = data_dir / "backups" / "removed-judgments"
    if judgments.is_dir():
        for path in judgments.iterdir():
            if path.is_dir() and not path.is_symlink():
                when = _stamp(_STAMPED_DIR.match(path.name))
                if when is not None and when < cutoff:
                    found.append(path)
    return found


def remove_old_backups(data_dir: Path, days: int, now: datetime | None = None) -> int:
    """Delete the automatic backups older than `days`. Returns how many were deleted. A file
    that cannot be deleted is skipped (logged) and never stops the app from starting."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    removed = 0
    for path in _old_entries(data_dir, cutoff):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("backup_cleanup_skipped error=%s", type(exc).__name__)
    logger.info("backup_cleanup removed=%d retention_days=%d", removed, days)
    return removed
