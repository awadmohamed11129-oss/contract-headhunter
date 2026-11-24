"""Editing on the Talent screen (user decisions 2026-11-18):
- the Profile pop-up has Edit and Save: Save stores the fields in the app's contractor list
  (backed up first, checked like an imported row) and marks the contractor to be matched
  again when what Gemini sees changed; a later import keeps the edit until the master
  (the contractor file) changes, then takes only the fields it changed (2026-11-24);
- the note lives in the Profile pop-up (talent_notes.csv) and shows read-only on the card;
- the availability switch saves when flipped (no Save button);
- the grey Résumé button adds a PDF; the viewer's Replace résumé needs a Save to replace
  the stored file, whose old copy is kept.
Fake Gemini, no network."""

from pathlib import Path

import pytest
from nicegui import ui

from jobmatch.app.service import AppError, AppService
from jobmatch.sources.resumes import resumes_dir
from test_app_ui import run_ui
from test_resumes import pdf
from test_talent import MarkerGemini, picked, profile, talent  # noqa: F401 (fixture)

PDF = b"%PDF-1.4\n% CV\n%%EOF\n"


def overview(service: AppService) -> dict:
    return {t.talent_id: t for t in service.talent_overview()}


def stored(service: AppService, talent_id: str):  # noqa: ANN201
    return next(p for p in service._loader().contractors.list_all() if p.talent_id == talent_id)


def test_save_profile_rewrites_the_row_with_a_backup(talent) -> None:  # noqa: ANN001, F811
    service, _ = talent
    loader = service._loader()
    backups = loader.contractors.path.parent / "backups"
    before = len(list(backups.glob("*"))) if backups.is_dir() else 0
    changes = len(loader.contractor_changes.list_all())
    saved = service.save_profile(
        "TAL-1",
        {"standardized_headline": "Analyste BI principal", "core_strengths": ["Power BI", "DAX"]},
        None,
    )
    assert saved.profile_changed and saved.rescan and not saved.note_changed
    row = stored(service, "TAL-1")
    assert row.standardized_headline == "Analyste BI principal"
    assert row.core_strengths == ["Power BI", "DAX"]
    assert row.talent_name == "Person 1"  # untouched fields stay
    assert len(list(backups.glob("*"))) == before + 1
    assert len(loader.contractor_changes.list_all()) == changes + 1  # matched again
    # A change Gemini never sees (the name) is saved but needs no new matching.
    saved = service.save_profile("TAL-1", {"talent_name": "Person One"}, None)
    assert saved.profile_changed and not saved.rescan
    # talent_id cannot change: the résumé is named by it.
    service.save_profile("TAL-1", {"talent_id": "TAL-77"}, None)
    assert stored(service, "TAL-1").talent_name == "Person One"


def test_wrong_fields_save_nothing(talent) -> None:  # noqa: ANN001, F811
    service, _ = talent
    path = service._loader().contractors.path
    text = path.read_bytes()
    with pytest.raises(AppError, match="Not saved.*weekly_hours"):
        service.save_profile("TAL-2", {"weekly_hours": -5, "seniority": "Senior"}, "Note")
    with pytest.raises(AppError, match="Not saved.*talent_name"):
        service.save_profile("TAL-2", {"talent_name": None}, None)
    assert path.read_bytes() == text
    assert overview(service)["TAL-2"].note is None
    with pytest.raises(AppError, match="not in the contractor list"):
        service.save_profile("TAL-99", {}, None)


def test_notes(talent) -> None:  # noqa: ANN001, F811
    service, _ = talent
    # Before 2026-11-18 notes came with an availability change: still shown.
    service.set_talent_availability("TAL-2", False, "Sur un mandat jusqu'en mars")
    assert overview(service)["TAL-2"].note == "Sur un mandat jusqu'en mars"
    saved = service.save_profile("TAL-2", {}, "  Available again in April  ")
    assert saved.note_changed and not saved.profile_changed
    assert overview(service)["TAL-2"].note == "Available again in April"
    assert not service.save_profile("TAL-2", {}, "Available again in April").note_changed
    service.save_profile("TAL-2", {}, "")  # cleared
    assert overview(service)["TAL-2"].note is None
    # The switch no longer touches the note.
    service.save_profile("TAL-3", {}, "Prefers remote work")
    service.set_talent_availability("TAL-3", False)
    assert overview(service)["TAL-3"].note == "Prefers remote work"
    service.delete_talent("TAL-3")
    assert all(n.talent_id != "TAL-3" for n in service._loader().talent_notes.list_all())


def test_edit_kept_until_master_changes(talent, tmp_path: Path) -> None:  # noqa: ANN001, F811
    """User decisions 2026-11-24: the contractor file is the master. An edit made in the app
    stays while the master row is unchanged; when the master changes, only the fields it
    changed are taken, and the master wins on a field edited in both."""
    service, _ = talent
    service.save_profile(
        "TAL-4", {"seniority": "Principal", "standardized_headline": "Analyste BI"}, None
    )

    def load(row):  # noqa: ANN001, ANN202
        path = picked(tmp_path, [row])
        service.pick_contractor_file(path.name, path=path)
        return service.run(echo=lambda s: None, confirm=lambda c: True).contractors

    report = load(profile(4))  # the source file still has the old values: not a change
    assert report.kept_edits == ["TAL-4"] and report.updated == []
    row = stored(service, "TAL-4")
    assert (row.seniority, row.standardized_headline) == ("Principal", "Analyste BI")

    report = load(profile(4).model_copy(update={"rate_expectation": "95"}))
    assert report.updated == ["TAL-4"]
    row = stored(service, "TAL-4")
    assert (row.rate_expectation, row.seniority, row.standardized_headline) == (
        "95", "Principal", "Analyste BI",
    )  # fmt: skip

    load(profile(4).model_copy(update={"rate_expectation": "95", "seniority": "Senior"}))
    row = stored(service, "TAL-4")
    assert (row.seniority, row.standardized_headline) == ("Senior", "Analyste BI")


def test_save_resume(talent) -> None:  # noqa: ANN001, F811
    service, _ = talent
    folder = resumes_dir(service.data_dir)
    assert service.save_resume("TAL-1", PDF) == "added"
    assert (folder / "TAL-1.pdf").read_bytes() == PDF
    assert service.resume_path("TAL-1") == folder / "TAL-1.pdf"
    assert service.save_resume("TAL-1", PDF) == "unchanged"
    newer = PDF.replace(b"CV", b"CV 2026")
    assert service.save_resume("TAL-1", newer) == "replaced"
    assert (folder / "TAL-1.pdf").read_bytes() == newer
    [old] = (folder / "old").glob("TAL-1-*.pdf")
    assert old.read_bytes() == PDF  # never deleted
    with pytest.raises(AppError, match="not a PDF"):
        service.save_resume("TAL-2", b"Jane Doe CV")
    with pytest.raises(AppError, match="not in the contractor list"):
        service.save_resume("TAL-99", PDF)
    assert sorted(p.name for p in folder.glob("*.pdf")) == ["TAL-1.pdf"]


def test_talent_screen_edit_flow(talent) -> None:  # noqa: ANN001, F811
    service, _ = talent
    pdf(resumes_dir(service.data_dir) / "TAL-1.pdf")

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/talent")
        await user.should_not_see(marker="save-available:TAL-1")  # no Save button any more
        [box] = user.find(marker="note:TAL-1").elements
        assert isinstance(box, ui.label)  # read-only
        user.find(marker="profile:TAL-1").click()
        await user.should_see("Profile: Person 1")
        await user.should_not_see(marker="profile-field:standardized_headline")
        user.find(marker="profile-edit").click()
        await user.should_see(marker="profile-field:standardized_headline")
        user.find(marker="profile-field:standardized_headline").clear().type("Analyste BI")
        user.find(marker="profile-note").type("Rappeler lundi")
        user.find(marker="profile-save").click()
        await user.should_see("Saved. They will be matched again on the next Find matches run.")
        await user.should_see("Rappeler lundi", marker="note:TAL-1")
        await user.should_see("Analyste BI")
        # The résumé on file: Replace résumé is there, Save only after a new pick.
        user.find(marker="resume:TAL-1").click()
        await user.should_see(marker="resume-frame")
        await user.should_see(marker="resume-replace")
        await user.should_not_see(marker="resume-save")

    run_ui(service, scenario)
    assert stored(service, "TAL-1").standardized_headline == "Analyste BI"
    assert overview(service)["TAL-1"].note == "Rappeler lundi"
