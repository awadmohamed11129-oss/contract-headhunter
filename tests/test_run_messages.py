"""The Find matches progress box speaks plain language (user request 2026-11-18): one
sentence per line, "Gemini timed out, high traffic, please try again." when high traffic
left jobs unchecked, and a bold "Successful: 3 matched, 1 no matches." at the end. The
technical lines still go to `echo` (CLI, app log). Fake Gemini, no network."""

import re
from collections.abc import Callable
from pathlib import Path

from jobmatch.app.service import AppService
from jobmatch.app.ui import result_line, run_job
from jobmatch.config import Settings
from jobmatch.llm.judge import JudgeRunReport
from jobmatch.llm.provider import LlmRequest, LlmResponse, LlmTimeoutError
from jobmatch.pipeline import HIGH_TRAFFIC, RunOnceReport, _say_judged
from jobmatch.schemas import Job
from jobmatch.storage.csv_store import CsvJobRepository, CsvStore
from test_app_ui import run_ui
from test_talent import MarkerGemini, picked, profile


class BusyGemini(MarkerGemini):
    """Never answers in time, like Gemini under heavy traffic."""

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        raise LlmTimeoutError("no answer within 120 s", attempts=1)


def one_sentence(line: str) -> bool:
    """Ends with a full stop and holds no second sentence."""
    return line.endswith(".") and not re.search(r"[.!?] [A-Z]", line[:-1])


def setup(
    gemini: MarkerGemini,
    app_settings: Settings,
    store: CsvStore,
    make_job: Callable[..., Job],
    tmp_path: Path,
) -> AppService:
    service = AppService(
        app_settings, tmp_path / "app.env", provider_factory=lambda: gemini, environ={}
    )
    CsvJobRepository(store).add_new([
        make_job(job_id="paste:1", source_id="1", title_norm="Data Analyst (contract)",
                 company_raw="City of Ottawa", location_raw="Ottawa, ON",
                 responsibilities=["Build Power BI dashboards"]),
        make_job(job_id="paste:2", source_id="2", title_norm="Analyste de données (contrat)",
                 company_raw="Ville de Québec", location_raw="Québec, QC",
                 responsibilities=["Tableaux de bord Power BI"], language="fr"),
    ])  # fmt: skip
    path = picked(tmp_path, [profile(n) for n in (1, 2, 3)] + [profile(5, contract=False)])
    service.pick_contractor_file(path.name, path=path)
    return service


def test_plain_lines_one_sentence_each(app_settings, store, make_job, tmp_path) -> None:  # noqa: ANN001
    service = setup(MarkerGemini(), app_settings, store, make_job, tmp_path)
    said: list[str] = []
    technical: list[str] = []
    report = service.run(echo=technical.append, confirm=lambda c: True, say=said.append)
    assert all(one_sentence(line) for line in said), said
    assert said[0] == "Loading the contractor list."
    assert "Contractors: 4 new, 0 updated, 0 unchanged." in said
    assert "1 contractor is not looking for contract work, so they are not checked." in said
    assert "Checking 2 jobs with Gemini." in said
    # No model names, budgets or token counts in the box; they stay in the technical lines.
    assert not any("token" in line or "fake" in line for line in said)
    assert any("tokens" in line for line in technical)
    assert result_line(report) == "Successful: 2 matched, 0 no matches."


def test_nothing_new_to_check(app_settings, store, make_job, tmp_path) -> None:  # noqa: ANN001
    service = setup(MarkerGemini(), app_settings, store, make_job, tmp_path)
    service.run(echo=lambda s: None, confirm=lambda c: True)
    said: list[str] = []
    service.run(echo=lambda s: None, confirm=lambda c: True, say=said.append)
    assert said == [
        "1 contractor is not looking for contract work, so they are not checked.",
        "Nothing new to check, so nothing was sent to Gemini.",
    ]


def test_timeout_says_high_traffic(app_settings, store, make_job, tmp_path) -> None:  # noqa: ANN001
    service = setup(BusyGemini(), app_settings, store, make_job, tmp_path)
    said: list[str] = []
    report = service.run(echo=lambda s: None, confirm=lambda c: True, say=said.append)
    assert HIGH_TRAFFIC == "Gemini timed out, high traffic, please try again."
    assert said.count(HIGH_TRAFFIC) == 1
    assert report.judge is not None and report.judge.busy >= 1
    assert result_line(report) == "Successful: 0 matched, 0 no matches, 2 not checked yet."


def test_judged_messages() -> None:
    def say(report: JudgeRunReport) -> list[str]:
        said: list[str] = []
        _say_judged(report, said.append)
        return said

    base = {"planned": 2, "cached": 0, "sent": 2, "ok": 1}
    assert say(JudgeRunReport(**base, failed=0, busy=1)) == []  # the next model answered
    assert say(JudgeRunReport(**base, failed=1, busy=1)) == [HIGH_TRAFFIC]
    assert say(JudgeRunReport(**base, failed=1)) == [
        "1 job got no usable answer from Gemini; the next run tries again."
    ]
    quota = JudgeRunReport(**base, failed=0, exhausted=["m"], stopped="limit")
    assert say(quota) == ["Today's Gemini limit is reached: please run again tomorrow."]


def test_result_line_stopped_early() -> None:
    report = RunOnceReport(run_id="r", jobs_matched=3, jobs_no_match=1, stopped="limit")
    assert result_line(report) == "Stopped early: 3 matched, 1 no matches."


def test_box_shows_bold_result(app_settings, store, make_job, tmp_path) -> None:  # noqa: ANN001
    service = setup(MarkerGemini(), app_settings, store, make_job, tmp_path)

    async def scenario(user) -> None:  # noqa: ANN001
        await user.open("/")
        user.find(marker="find-matches").click()
        await user.should_see("Successful: 2 matched, 0 no matches.", retries=80)
        await user.should_see("Checking 2 jobs with Gemini.")
        await user.should_not_see("tokens in")

    run_ui(service, scenario)
    lines = run_job(service).lines
    assert lines[-1] == ("Successful: 2 matched, 0 no matches.", True)
    assert not any(bold for _, bold in lines[:-1])
