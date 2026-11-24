"""Get latest: the download client (sync_client) and its use through AppService, against a
tiny local fake of the Google side (tests/fake_sync_server.py). Made-up people and jobs, no
Gemini, no internet."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from fake_sync_server import TOKEN, FakeGoogle, job_text
from jobmatch import sync_client
from jobmatch.app.service import AppError, AppService
from jobmatch.sync_client import SyncApi, Syncer, SyncError, SyncState, parse_link

PEOPLE = [("TAL-INT-ON-001", "Ann Example"), ("TAL-INT-ON-002", "Bo Example")]
DEV = {"JOBMATCH_DEV_ALLOW_LOCAL_SYNC": "1"}


@pytest.fixture
def server() -> Iterator[FakeGoogle]:
    fake = FakeGoogle()
    fake.set_people(PEOPLE)
    yield fake
    fake.close()


def syncer(fake: FakeGoogle, tmp_path: Path) -> Syncer:
    link = parse_link(fake.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=lambda s: None)
    return Syncer(api, tmp_path / "synced", SyncState(tmp_path / "sync_state.json"))


def service(app_settings, tmp_path: Path) -> AppService:  # noqa: ANN001
    return AppService(app_settings, tmp_path / "app.env", environ=dict(DEV))


def names(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


# ---- the link ----


def test_only_https_links_with_the_secret_code_are_taken() -> None:
    good = f"https://script.google.com/macros/s/ABC/exec?sync={TOKEN}"
    link = parse_link(good)
    assert link.hint == "…" + TOKEN[-4:] and TOKEN not in repr(link)
    assert parse_link(f" <{good}> ").token == TOKEN  # pasted with spaces or brackets
    for bad in (
        "",
        "https://docs.google.com/spreadsheets/d/xyz/edit",  # a Sheet, not the download link
        "https://script.google.com/macros/s/ABC/exec",  # no code
        "https://script.google.com/macros/s/ABC/exec?sync=abc123",  # code too short
        f"http://script.google.com/macros/s/ABC/exec?sync={TOKEN}",  # not https
        f"http://127.0.0.1:9/exec?sync={TOKEN}",  # plain http to this computer: dev flag only
        "two words https://x",
    ):
        with pytest.raises(SyncError) as caught:
            parse_link(bad)
        assert caught.value.kind == "bad_link"
    assert parse_link(f"http://127.0.0.1:9/exec?sync={TOKEN}", allow_local_http=True).token == TOKEN
    with pytest.raises(SyncError):  # even with the flag, only this computer
        parse_link(f"http://example.com/exec?sync={TOKEN}", allow_local_http=True)


def test_the_secret_is_masked_in_any_text() -> None:
    shown = sync_client.mask_secrets(f"failed https://x/exec?sync={TOKEN}&a=zip and {TOKEN}")
    assert TOKEN not in shown and "sync=…" in shown


# ---- downloading ----


def test_first_sync_writes_the_importers_folder_shape(server: FakeGoogle, tmp_path: Path) -> None:
    result = syncer(server, tmp_path).sync_contractors()
    assert result.status == "updated"
    folder = tmp_path / "synced" / "contractors"
    assert names(folder) == [
        "contractors.csv", "resumes/TAL-INT-ON-001.pdf", "resumes/TAL-INT-ON-002.pdf",
    ]  # fmt: skip
    assert (folder / "contractors.csv").read_bytes() == server.csv_bytes
    assert not [
        p for p in (tmp_path / "synced").iterdir() if p.name.startswith(".")
    ]  # no leftovers


def test_an_unchanged_manifest_does_nothing(server: FakeGoogle, tmp_path: Path) -> None:
    first = syncer(server, tmp_path)
    first.sync_contractors()
    folder = tmp_path / "synced" / "contractors"
    stamps = {p: p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()}
    server.log.clear()

    again = syncer(server, tmp_path).sync_contractors()
    assert again.status == "unchanged"
    assert [r["a"] for r in server.log] == ["manifest"]  # one cheap question, no download
    assert "since" in server.log[0]
    assert {p: p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()} == stamps


def test_a_changed_manifest_downloads_and_swaps_the_folder(
    server: FakeGoogle, tmp_path: Path
) -> None:
    syncer(server, tmp_path).sync_contractors()
    server.add_person("TAL-INT-ON-003", "Cy Example")
    server.log.clear()

    result = syncer(server, tmp_path).sync_contractors()
    assert result.status == "updated"
    folder = tmp_path / "synced" / "contractors"
    assert "resumes/TAL-INT-ON-003.pdf" in names(folder)
    assert b"TAL-INT-ON-003" in (folder / "contractors.csv").read_bytes()


def test_a_large_pool_uses_the_paged_route_and_reuses_what_is_local(
    server: FakeGoogle, tmp_path: Path
) -> None:
    server.zip_available = False  # over the zip limit: csv + one call per résumé
    server.chunk = 30  # tiny pieces: a résumé comes in several parts
    syncer(server, tmp_path).sync_contractors()
    folder = tmp_path / "synced" / "contractors"
    assert (folder / "resumes" / "TAL-INT-ON-001.pdf").read_bytes() == server.resumes[
        "TAL-INT-ON-001"
    ]
    server.add_person("TAL-INT-ON-003", "Cy Example")
    server.log.clear()

    syncer(server, tmp_path).sync_contractors()
    asked = [r.get("id") for r in server.log if r.get("a") == "file"]
    assert set(asked) == {"TAL-INT-ON-003"}  # the two old résumés were not downloaded again
    assert any(r.get("a") == "csv" for r in server.log)


def test_a_wrong_token_is_not_found_and_leaves_nothing(server: FakeGoogle, tmp_path: Path) -> None:
    wrong = parse_link(server.link.replace("abab", "efef", 1), allow_local_http=True)
    api = SyncApi(wrong, allow_local_http=True, sleep=lambda s: None)
    with pytest.raises(SyncError) as caught:
        Syncer(api, tmp_path / "synced", SyncState(tmp_path / "s.json")).sync_contractors()
    assert caught.value.kind == "bad_link"
    assert not (tmp_path / "synced" / "contractors").exists()


def test_a_hash_mismatch_is_rejected_and_the_old_folder_is_kept(
    server: FakeGoogle, tmp_path: Path
) -> None:
    syncer(server, tmp_path).sync_contractors()
    folder = tmp_path / "synced" / "contractors"
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    server.add_person("TAL-INT-ON-003", "Cy Example")
    server.corrupt = {"resumes/TAL-INT-ON-003.pdf"}  # arrives damaged

    with pytest.raises(SyncError) as caught:
        syncer(server, tmp_path).sync_contractors()
    assert caught.value.kind == "damaged"
    assert {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before
    assert not [p for p in (tmp_path / "synced").iterdir() if p.name.startswith(".")]


def test_a_busy_answer_is_waited_for_then_tried_again(server: FakeGoogle, tmp_path: Path) -> None:
    server.busy = 1
    waits: list[float] = []
    link = parse_link(server.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=waits.append)
    result = Syncer(api, tmp_path / "synced", SyncState(tmp_path / "s.json")).sync_contractors()
    assert result.status == "updated" and waits == [20.0]  # the server's advice: 20 seconds


def test_busy_is_asked_at_most_twice_more_then_given_up(server: FakeGoogle, tmp_path: Path) -> None:
    server.busy = 5
    waits: list[float] = []
    link = parse_link(server.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=waits.append)
    with pytest.raises(SyncError) as caught:
        Syncer(api, tmp_path / "synced", SyncState(tmp_path / "s.json")).sync_contractors()
    assert caught.value.kind == "busy" and waits == [20.0, 20.0]  # ask, wait, ask, wait, ask, stop
    assert not (tmp_path / "synced" / "contractors").exists()


def test_since_is_the_etag_and_a_time_is_refused(server: FakeGoogle, tmp_path: Path) -> None:
    link = parse_link(server.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=lambda s: None)
    with pytest.raises(SyncError) as caught:
        api.call(a="manifest", since="2026-11-23T10:00:00.000Z")
    assert caught.value.kind == "bad_since"
    same = api.call(a="manifest", since=server.etag().upper())  # capitals are accepted
    assert same["changed"] is False
    assert set(same) == {"ok", "changed", "etag", "generated", "changed_at"}  # the five keys


def test_an_etag_the_server_refuses_is_asked_again_in_full(
    server: FakeGoogle, tmp_path: Path
) -> None:
    syncer(server, tmp_path).sync_contractors()
    SyncState(tmp_path / "sync_state.json").update("contractors", etag="not an etag")
    server.log.clear()
    result = syncer(server, tmp_path).sync_contractors()
    assert result.status == "unchanged"  # the content is the same; only the etag moved
    assert [r.get("since") is not None for r in server.log] == [True, False]
    assert SyncState(tmp_path / "sync_state.json").part("contractors")["etag"] == server.etag()


def test_the_csv_bytes_hash_exactly_as_the_manifest_says(
    server: FakeGoogle, tmp_path: Path
) -> None:
    link = parse_link(server.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=lambda s: None)
    listed = {f["path"]: f for f in api.call(a="manifest")["files"]}["contractors.csv"]
    body = api.csv()
    assert sync_client.file_hash(body) == listed["hash"] and len(body) == listed["bytes"]
    assert b"\r\n" in body and not body.startswith(b"\xef\xbb\xbf")


def test_when_the_folder_moved_between_manifest_and_zip_the_zips_etag_is_kept(
    server: FakeGoogle, tmp_path: Path
) -> None:
    server.before_zip = lambda: server.add_person("TAL-INT-ON-003", "Cy Example")
    old_etag = server.etag()
    first = syncer(server, tmp_path)
    result = first.sync_contractors()
    server.before_zip = None
    folder = tmp_path / "synced" / "contractors"
    assert "resumes/TAL-INT-ON-003.pdf" in names(folder)  # the zip's own list is trusted
    assert result.etag == server.etag() != old_etag
    server.log.clear()
    assert syncer(server, tmp_path).sync_contractors().status == "unchanged"  # no second download
    assert [r["a"] for r in server.log] == ["manifest"]


def test_a_changed_answer_is_waited_for_like_busy(server: FakeGoogle, tmp_path: Path) -> None:
    server.changed_answers = 1
    waits: list[float] = []
    link = parse_link(server.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=waits.append)
    result = Syncer(api, tmp_path / "synced", SyncState(tmp_path / "s.json")).sync_contractors()
    assert result.status == "updated" and waits == [20.0]


def test_jobs_come_newest_first_and_only_the_new_ones_the_next_time(
    server: FakeGoogle, tmp_path: Path
) -> None:
    server.add_job("a.txt", job_text(1), "2026-11-20T10:00:00.000Z", day="2026-11-20")
    server.add_job("b.txt", job_text(2), "2026-11-21T10:00:00.000Z", day="2026-11-21")
    first = syncer(server, tmp_path).sync_jobs()
    assert first.status == "updated" and first.new_files == 2
    assert names(tmp_path / "synced" / "jobs") == ["a.txt", "b.txt"]  # flat: the importer's shape

    server.log.clear()
    assert syncer(server, tmp_path).sync_jobs().status == "unchanged"  # a cheap question only
    assert [r["a"] for r in server.log] == ["manifest"]

    server.add_job("c.txt", job_text(3), "2026-11-22T10:00:00.000Z", day="2026-11-22")
    server.log.clear()
    second = syncer(server, tmp_path).sync_jobs()
    assert second.new_files == 1 and names(tmp_path / "synced" / "jobs") == [
        "a.txt",
        "b.txt",
        "c.txt",
    ]
    assert any(r.get("since") == "2026-11-21T10:00:00.000Z" for r in server.log)


def test_nothing_new_in_jobs_is_one_ten_key_shape_for_manifest_and_zip(
    server: FakeGoogle, tmp_path: Path
) -> None:
    server.add_job("a.txt", job_text(1), "2026-11-20T10:00:00.000Z")
    link = parse_link(server.link, allow_local_http=True)
    api = SyncApi(link, allow_local_http=True, sleep=lambda s: None)
    for action in ("manifest", "zip"):
        answer = api.call(part="jobs", a=action, since="2026-11-20T10:00:00.000Z")
        assert answer["changed"] is False and "files" not in answer and "data" not in answer
        assert set(answer) == {
            "ok", "part", "changed", "format", "etag", "generated", "hash_method",
            "total_seen", "total_listed", "truncated",
        }  # fmt: skip
    assert api.call(part="jobs", a="zip")["changed"] is True  # a zip with files says so


def test_jobs_page_backwards_and_the_boundary_file_is_kept_once(
    server: FakeGoogle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_client, "JOB_PAGE", 2)
    for n in range(1, 6):
        server.add_job(f"j{n}.txt", job_text(n), f"2026-11-2{n}T10:00:00.000Z")
    result = syncer(server, tmp_path).sync_jobs()
    assert result.new_files == 5
    assert names(tmp_path / "synced" / "jobs") == [f"j{n}.txt" for n in range(1, 6)]
    asked = [r for r in server.log if r.get("a") == "zip"]
    assert len(asked) >= 3 and any("before" in r for r in asked)  # paged with before=


def test_two_jobs_with_the_same_time_are_not_skipped_when_paging(
    server: FakeGoogle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_client, "JOB_PAGE", 2)
    same = "2026-11-22T10:00:00.000Z"
    server.add_job("old.txt", job_text(1), "2026-11-20T10:00:00.000Z")
    server.add_job("t1.txt", job_text(2), same)
    server.add_job("t2.txt", job_text(3), same)
    syncer(server, tmp_path).sync_jobs()
    assert names(tmp_path / "synced" / "jobs") == ["old.txt", "t1.txt", "t2.txt"]


def test_jobs_with_a_bad_hash_write_nothing(server: FakeGoogle, tmp_path: Path) -> None:
    server.add_job("a.txt", job_text(1), "2026-11-20T10:00:00.000Z")
    server.corrupt = {"a.txt"}
    with pytest.raises(SyncError) as caught:
        syncer(server, tmp_path).sync_jobs()
    assert caught.value.kind == "damaged"
    assert not (tmp_path / "synced" / "jobs").exists()


def test_a_link_without_a_job_folder_is_not_an_error_for_the_check(
    server: FakeGoogle, tmp_path: Path
) -> None:
    server.jobs_enabled = False
    link = parse_link(server.link, allow_local_http=True)
    found = sync_client.check_link(SyncApi(link, allow_local_http=True, sleep=lambda s: None))
    assert (found.people, found.jobs) == (2, None)


# ---- through AppService: the existing importer, the folders it remembers ----


def test_get_latest_hands_the_downloaded_folder_to_the_existing_import(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    svc = service(app_settings, tmp_path)
    hint = svc.save_sync_link(server.link)
    assert hint == "…" + TOKEN[-4:] and svc.has_sync_link()
    server.add_job("a.txt", job_text(1), "2026-11-20T10:00:00.000Z")

    outcome = svc.get_latest(adopt=True)
    assert outcome.problem == "" and outcome.downloaded
    assert outcome.summary is not None and outcome.summary.people_added == 2
    assert outcome.summary.new_job_files == 1
    assert svc.contractor_count() == 2
    assert svc.contractors_folder() == tmp_path / "synced" / "contractors"
    assert svc.jobs_folder() == tmp_path / "synced" / "jobs"
    status = svc.latest_status()
    assert (
        status.has_link and status.contractors.from_link and status.contractors.new == 0
    )  # the baseline
    assert status.contractors.checked_at is not None

    server.log.clear()  # the next start: nothing changed, one cheap question per part
    again = svc.get_latest()
    assert again.summary is not None and again.summary.people_added == 0 and not again.downloaded
    assert {r["a"] for r in server.log} == {"manifest"}
    assert svc.latest_status().contractors.new == 0


def test_the_link_is_kept_like_the_key_and_never_shown_or_logged(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    svc = service(app_settings, tmp_path)
    svc.save_sync_link(server.link)
    svc.get_latest(adopt=True)
    assert TOKEN in (tmp_path / "app.env").read_text()  # saved in the local secrets file
    assert TOKEN not in caplog.text and TOKEN not in repr(svc.latest_status())
    assert svc.sync_link_hint() == "…" + TOKEN[-4:]
    with pytest.raises(AppError) as caught:
        svc.save_sync_link(f"https://docs.google.com/x?sync={TOKEN}")
    assert TOKEN not in str(caught.value)
    svc.forget_sync_link()
    assert not svc.has_sync_link() and svc.sync_link_hint() == ""


def test_test_link_says_what_it_found_without_saving(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    svc = service(app_settings, tmp_path)
    server.add_job("a.txt", job_text(1), "2026-11-20T10:00:00.000Z")
    found = svc.test_sync_link(server.link)
    assert (found.kind, found.people, found.jobs) == ("ok", 2, 1)
    assert not svc.has_sync_link()
    assert svc.test_sync_link("https://example.com/nope").kind == "bad_link"
    wrong = server.link.replace("abab", "efef", 1)
    assert svc.test_sync_link(wrong).kind == "bad_link"
    server.close()
    assert svc.test_sync_link(server.link).kind == "offline"


def test_offline_is_calm_and_the_last_copy_keeps_working(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    svc = service(app_settings, tmp_path)
    svc.save_sync_link(server.link)
    svc.get_latest(adopt=True)
    server.close()

    outcome = svc.get_latest()  # no exception, no half state
    assert outcome.problem == "offline" and not outcome.downloaded
    assert outcome.summary is not None and not outcome.summary.problems
    assert svc.contractor_count() == 2
    assert svc.latest_status().problem == "offline" and svc.latest_status().last_ok_at is not None


def test_a_folder_picked_by_hand_is_left_alone_by_the_quiet_check(
    app_settings,  # noqa: ANN001
    server: FakeGoogle,
    tmp_path: Path,
) -> None:
    from test_resumes import folder

    svc = service(app_settings, tmp_path)
    svc.save_sync_link(server.link)
    svc.get_latest(adopt=True)  # the link is the source
    svc.pick_contractor_folder(folder(tmp_path))  # "Change..." by hand
    server.add_person("TAL-INT-ON-003", "Cy Example")
    server.log.clear()
    svc.get_latest()  # the start-up check, not asked by the person
    assert all(r.get("part") == "jobs" for r in server.log)  # contractors were not even asked
    assert svc.contractors_folder() == tmp_path / "Contractors"
    svc.get_latest(adopt=True)  # the person clicked Get latest: the link is the source again
    assert svc.contractors_folder() == tmp_path / "synced" / "contractors"
    assert svc.contractor_count() == 5  # 3 from the link, 2 from the folder picked by hand


def test_progress_follows_the_download_and_knows_the_total_on_a_first_run(
    server: FakeGoogle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_client, "JOB_PAGE", 2)
    for n in range(1, 6):
        server.add_job(f"p{n}.txt", job_text(n), f"2026-11-2{n}T10:00:00.000Z")
    sy = syncer(server, tmp_path)
    sy.sync_contractors()
    assert (sy.progress.part, sy.progress.found) == ("contractors", len(PEOPLE))
    sy.sync_jobs()
    assert (sy.progress.part, sy.progress.found, sy.progress.total) == ("jobs", 5, 5)
    assert sy.progress.share == pytest.approx(0.95)
    # a later download does not know how many files are coming: no total, no invented one
    server.add_job("p6.txt", job_text(6), "2026-11-26T10:00:00.000Z")
    sy.sync_jobs()
    assert sy.progress.total is None and sy.progress.found == 1
