"""Tests for sailab.acquisition, matching the Test Case Register."""
from sailab.acquisition import choose_sensor, ResumableRun, RunLog


def test_TC_ACQ_06_optical_or_radar():
    """Given cloud values 8, 49, 50, 51, 100 and missing, with a 50% test limit,
    the first three choose optical, the rest choose radar (missing counts as unusable)."""
    cloud_values = [8, 49, 50, 51, 100, None]

    chosen = [choose_sensor(value, cloud_limit_percent=50) for value in cloud_values]

    assert chosen == ["optical", "optical", "optical", "radar", "radar", "radar"]


def test_TC_ACQ_04_resume_after_a_crash():
    """Given six lakes and a run stopped after lake 3 finishes, starting the run again
    handles lakes 4, 5 and 6 only: six downloads in total, no lake downloaded twice."""
    lakes = [1, 2, 3, 4, 5, 6]
    downloaded: list[int] = []

    def fake_downloader(lake_id: int) -> None:
        downloaded.append(lake_id)

    shared_log = RunLog()

    # Simulate a crash straight after lake 3: the first run only ever sees lakes 1-3.
    first_run = ResumableRun(lakes=lakes[:3], downloader=fake_downloader, log=shared_log)
    first_run.run()

    assert downloaded == [1, 2, 3]
    assert shared_log.last_completed_lake_id == 3
    assert shared_log.download_count == 3

    second_run = ResumableRun(lakes=lakes, downloader=fake_downloader, log=shared_log)
    resumed = second_run.run()

    assert resumed == [4, 5, 6], "the second run must handle only the lakes after the last completed one"
    assert downloaded == [1, 2, 3, 4, 5, 6], "no lake should be downloaded twice"
    assert shared_log.download_count == 6


def test_resume_with_a_lake_list_that_lacks_the_last_completed_lake_starts_at_its_beginning():
    # Regression (run 26): state said lake 10 finished, the resumed run was started with --lakes for lake 11 only.
    done = []
    run = ResumableRun(lakes=[11], downloader=done.append, log=RunLog(last_completed_lake_id=10, download_count=2))
    assert run.run() == [11] and done == [11]
    assert run.log.last_completed_lake_id == 11 and run.log.download_count == 3
