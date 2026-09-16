from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import DriveBackend
from .drive_consumption import DriveConsumptionBlocked, DriveReadyConsumption
from .drive_discovery import DriveDiscoveryBlocked, DriveRestartDiscovery
from .drive_factory import DriveTransactionFactory, DriveTransactionFactoryBlocked
from .drive_runtime import DriveRuntime, DriveRuntimeBlocked
from .protocol import ProtocolError


class DriveServiceBlocked(ProtocolError):
    """The high-level Drive polling service cannot safely make further progress."""


@dataclass(frozen=True)
class DriveServiceStatus:
    phase: str
    detail: str
    ready_clean: bool

    @property
    def quiescent(self) -> bool:
        return self.phase in {
            "IDLE",
            "WAIT_POSTCHECK",
            "COMMITTED",
            "ROLLED_BACK",
            "RECOVERY_BLOCKED",
            "ABORTED_SAFE",
        }


class DrivePollingService:
    """One restart-safe polling iteration from Hub protocol to terminal cleanup.

    This is the first layer that composes the full MVP Drive path:

    * discover/recover an already-active transaction when one exists;
    * otherwise ingest at most one Ready Change and build/resume its exact bundle;
    * run the state-derived Core transaction;
    * after COMMITTED/ROLLED_BACK, archive only the exact consumed READY marker;
    * only then archive the active locator and return to clean READY.

    WAIT_POSTCHECK, RECOVERY_BLOCKED and ABORTED_SAFE deliberately retain their
    active locator. They require later external input or explicit recovery rather
    than being silently cleaned into a state that could be mistaken for idle.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    def _runtime(self) -> DriveRuntime:
        return DriveRuntime(self.drive, self.hub_root_id)

    def _factory(self) -> DriveTransactionFactory:
        return DriveTransactionFactory(self.drive, self.hub_root_id)

    def _terminal_bundle(self, expected_phase: str):
        try:
            discovered = DriveRestartDiscovery.from_hub_root(self.drive, self.hub_root_id).discover()
        except DriveDiscoveryBlocked as exc:
            raise DriveServiceBlocked(f"cannot rediscover terminal transaction: {exc}") from exc
        if (
            discovered.state != "READY_WITH_LOCATOR"
            or discovered.bundle is None
            or discovered.runner_phase != expected_phase
        ):
            raise DriveServiceBlocked(
                f"terminal cleanup requires READY_WITH_LOCATOR/{expected_phase}, observed "
                f"{discovered.state}/{discovered.runner_phase}"
            )
        return discovered.bundle

    def _settle_terminal(self, phase: str) -> DriveServiceStatus:
        bundle = self._terminal_bundle(phase)
        try:
            layout = self._factory().resolve_layout()
            consumed = DriveReadyConsumption(self.drive, layout.changes_parent_id).consume(bundle)
            cleaned = self._runtime().cleanup_ready_locator()
        except (DriveConsumptionBlocked, DriveRuntimeBlocked, DriveTransactionFactoryBlocked) as exc:
            raise DriveServiceBlocked(str(exc)) from exc
        if cleaned.phase != "READY_CLEAN":
            raise DriveServiceBlocked(f"terminal locator cleanup ended in {cleaned.phase}")
        return DriveServiceStatus(
            phase,
            f"{phase}; Ready marker {consumed.state.lower()}; active locator archived",
            True,
        )

    def run_once(self, *, max_steps: int = 32) -> DriveServiceStatus:
        runtime = self._runtime()
        try:
            current = runtime.restart(max_steps=max_steps)
        except DriveRuntimeBlocked as exc:
            raise DriveServiceBlocked(str(exc)) from exc

        if current.phase == "READY_CLEAN":
            try:
                bundle = self._factory().build_or_resume()
            except DriveTransactionFactoryBlocked as exc:
                raise DriveServiceBlocked(str(exc)) from exc
            if bundle is None:
                return DriveServiceStatus("IDLE", "READY/SAFE with no unconsumed Ready Change", True)
            try:
                current = runtime.run_new(bundle, max_steps=max_steps)
            except DriveRuntimeBlocked as exc:
                raise DriveServiceBlocked(str(exc)) from exc

        if current.phase in {"COMMITTED", "ROLLED_BACK"}:
            return self._settle_terminal(current.phase)
        if current.phase == "WAIT_POSTCHECK":
            return DriveServiceStatus("WAIT_POSTCHECK", current.detail, False)
        if current.phase == "RECOVERY_BLOCKED":
            return DriveServiceStatus("RECOVERY_BLOCKED", current.detail, False)
        if current.phase == "ABORTED_SAFE":
            return DriveServiceStatus(
                "ABORTED_SAFE",
                "pre-UNSAFE abort retained exact locator/bundle for explicit resolution",
                False,
            )
        raise DriveServiceBlocked(f"unexpected Drive runtime phase: {current.phase}")


__all__ = ["DrivePollingService", "DriveServiceBlocked", "DriveServiceStatus"]
