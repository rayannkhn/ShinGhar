"""Acquisition stage: which sensor to use (FR-05), and a run that can resume after a crash (FR-04).

ResumableRun does not touch the network itself; it is handed a "downloader"
function (any callable lake -> result) so it can be tested with a fake one and
later wired to the real Copernicus client without changing this module.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Iterable


def choose_sensor(cloud_fraction: float | None, cloud_limit_percent: float = 50.0) -> str:
    """"optical" when cloud is at or below the limit, otherwise "radar".

    A missing cloud value counts as unusable (FR-05), so it falls back to radar
    rather than guessing that the sky was probably clear.
    """
    if cloud_fraction is None:
        return "radar"
    return "optical" if cloud_fraction <= cloud_limit_percent else "radar"


@dataclass
class RunLog:
    """The persisted state a resumable run reads and writes (mirrors the RUN_LOG entity in the SRS)."""
    last_completed_lake_id: int | None = None
    download_count: int = 0


@dataclass
class ResumableRun:
    """Runs a downloader over an ordered list of lakes, skipping any already completed.

    download_count on the shared RunLog is the audit trail: restarting a run
    must not increase it beyond the number of lakes actually downloaded.
    """
    lakes: list[int]
    downloader: Callable[[int], None]
    log: RunLog = field(default_factory=RunLog)

    def run(self) -> list[int]:
        """Process every lake after the last completed one. Returns the lake ids downloaded this call."""
        downloaded_this_call: list[int] = []
        resume_from = self._index_after_last_completed()
        for lake_id in self.lakes[resume_from:]:
            self.downloader(lake_id)
            self.log.download_count += 1
            self.log.last_completed_lake_id = lake_id
            downloaded_this_call.append(lake_id)
        return downloaded_this_call

    def _index_after_last_completed(self) -> int:
        if self.log.last_completed_lake_id is None:
            return 0
        if self.log.last_completed_lake_id not in self.lakes:
            # The interrupted run had a different lake list (e.g. resumed with --lakes set to the unfinished lakes):
            # nothing of THIS list is known to be finished, so start at its beginning (each lake then continues
            # from its newest stored scene, so nothing is measured twice).
            return 0
        return self.lakes.index(self.log.last_completed_lake_id) + 1
