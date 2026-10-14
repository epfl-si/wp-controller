import asyncio
import os
import re
import sys

import pytest

# core.controller instantiates a module-level singleton at import time
# (see its bottom - one real controller for the whole process), which reads
# WATCH_NAMESPACE immediately: must be set before the import, not inside a
# fixture, or collection fails with KeyError before any test runs.
os.environ.setdefault("WATCH_NAMESPACE", "wordpress-test")

from core.controller import WordPressNginxController  # noqa: E402


class FakeSync:
    """Stand-in for WordPressNginxController.sync(): takes measurable time
    to "run" and, like the real sync(), always reads whatever the *current*
    desired state is when it actually executes rather than acting on
    whatever it was when it got scheduled. Records concurrency so tests can
    assert sync() calls never overlap."""

    def __init__(self, read_state, duration: float):
        self.read_state = read_state
        self.duration = duration
        self.concurrent = 0
        self.max_concurrent = 0
        self.observed_states = []

    async def __call__(self):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            await asyncio.sleep(self.duration)
            self.observed_states.append(self.read_state())
        finally:
            self.concurrent -= 1


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setenv("WATCH_NAMESPACE", "wordpress-test")
    ctrl = WordPressNginxController()
    # Fast, deterministic timings instead of the multi-second production
    # defaults, so the burst below plays out in a fraction of a second.
    ctrl.debounce_seconds = 0.02
    ctrl.max_wait_seconds = 1.0
    return ctrl


class TestSyncSingleFlightUnderBursts:
    """Covers the race fixed by acquiring self._sync_lock *inside* the
    shielded coroutine (_locked_sync) instead of around it: a trailing
    event used to cancel _debounced_sync while a previous sync() was
    already mid-flight, orphaning it (still running, but untracked) while
    a fresh sync started on top - two sync() calls genuinely concurrent,
    racing over the same candidate/scratch config files."""

    @pytest.mark.asyncio
    async def test_sync_never_overlaps_when_events_arrive_mid_sync(self, controller):
        state = {"version": 0}
        tracker = FakeSync(read_state=lambda: state["version"], duration=0.05)
        controller.sync = tracker

        # Each gap (0.03s) is longer than debounce_seconds (0.02s) but
        # shorter than a sync's duration (0.05s), so every new event fires
        # while the previous debounced task is already inside its sync() -
        # exactly the scenario that used to let them overlap.
        for version in range(1, 11):
            state["version"] = version
            await controller.request_sync()
            await asyncio.sleep(0.03)

        await asyncio.sleep(1.0)  # let anything still queued behind the lock finish

        assert tracker.max_concurrent == 1, "sync() calls overlapped - single-flight guarantee broken"
        assert tracker.observed_states, "no sync() call ever ran"
        assert tracker.observed_states[-1] == 10, "the final sync must reflect the latest state"

    @pytest.mark.asyncio
    async def test_final_config_is_correct_after_a_burst_of_events(self, controller):
        """Many WordpressSite events arriving faster than the debounce
        window can separate them (e.g. the flood of `resume` events on
        startup) must still converge on the single latest state, and must
        do so without ever running two syncs at once."""
        state = {"version": 0}
        tracker = FakeSync(read_state=lambda: state["version"], duration=0.05)
        controller.sync = tracker

        for version in range(1, 51):
            state["version"] = version
            await controller.request_sync()  # no gap: fire as fast as possible

        await asyncio.sleep(1.0)

        assert tracker.max_concurrent == 1
        assert tracker.observed_states, "no sync() call ever ran"
        assert tracker.observed_states[-1] == 50, "must end up with the latest config, not a stale intermediate one"
        # The whole point of debouncing: far fewer sync() calls than events.
        assert len(tracker.observed_states) < 50


class TestKeepRejectedConfig:
    @pytest.fixture(autouse=True)
    def rejected_dir(self, monkeypatch, tmp_path):
        # `core.controller` as an attribute path is the singleton instance
        # (see core/__init__.py), not the module - go through sys.modules.
        module = sys.modules["core.controller"]
        monkeypatch.setattr(module, "REJECTED_CONFIG_DIR", str(tmp_path / "rejected"))
        monkeypatch.setattr(module, "REJECTED_CONFIG_KEEP", 2)
        return tmp_path / "rejected"

    def test_rejected_config_goes_to_a_timestamped_file_not_the_logs(self, controller, rejected_dir, caplog):
        from models import NginxConfigError

        content = 'fastcgi_param WP_DB_PASSWORD "s3cret";'
        rejected = controller._keep_rejected_config(content, NginxConfigError("boom", verbose_output="debug output"))

        assert re.fullmatch(r".*/\d{8}T\d{6}Z\.rejected", rejected)
        assert open(rejected).read() == content
        assert open(f"{rejected}.log").read() == "debug output"
        assert oct(os.stat(rejected).st_mode & 0o777) == "0o600"
        assert "s3cret" not in caplog.text

    def test_only_the_most_recent_are_kept(self, controller, rejected_dir):
        from models import NginxConfigError

        for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
            for suffix in ("", ".log"):
                rejected_dir.mkdir(exist_ok=True)
                (rejected_dir / f"{stamp}.rejected{suffix}").write_text("old")

        controller._keep_rejected_config("new", NginxConfigError("boom"))

        names = sorted(p.name for p in rejected_dir.iterdir() if p.name.endswith(".rejected"))
        assert len(names) == 2
        assert names[0] == "20260103T000000Z.rejected"
        assert not (rejected_dir / "20260101T000000Z.rejected.log").exists()

    def test_failure_to_save_never_raises(self, controller, tmp_path, monkeypatch):
        from models import NginxConfigError

        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setattr(sys.modules["core.controller"], "REJECTED_CONFIG_DIR", str(blocker / "sub"))

        assert controller._keep_rejected_config("x", NginxConfigError("boom")) is None


class TestReadinessLatch:
    """/healthz gates the pod's readiness on the *initial* load only: once no
    site is waiting any more it stays 200, whatever happens to a site
    afterwards. Before, a site failing to resolve - at startup or later -
    put every sync in 503 for SITE_LOOKUP_RETRY_TIMEOUT_SECONDS, then back
    to 200 for a moment once given up on, then 503 again, taking all the
    healthy sites out of the Service with it."""

    TIMEOUT = 0.05

    @pytest.fixture
    def sync_env(self, controller, monkeypatch):
        module = sys.modules["core.controller"]
        monkeypatch.setattr(module, "SITE_LOOKUP_RETRY_TIMEOUT_SECONDS", self.TIMEOUT)

        env = type("Env", (), {})()
        env.skipped = {}
        env.ready_seen = []

        async def fake_load_site_infos(*_):
            return [], dict(env.skipped)

        def fake_render_config(sites, ready=True):
            env.ready_seen.append(ready)
            return "config"

        monkeypatch.setattr(module, "load_site_infos", fake_load_site_infos)
        monkeypatch.setattr(module, "render_config", fake_render_config)
        # Same content as the rendered one: _sync returns at the "unchanged"
        # step, before it would write files or touch nginx.
        monkeypatch.setattr(controller, "_read_current_config", lambda: "config")
        env.ctrl = controller
        yield env
        controller.cancel_pending_sync()

    @staticmethod
    async def past_timeout():
        await asyncio.sleep(TestReadinessLatch.TIMEOUT * 1.5)

    @pytest.mark.asyncio
    async def test_not_ready_while_a_site_is_pending_at_startup(self, sync_env):
        sync_env.skipped = {"a": "no User owned by it"}
        await sync_env.ctrl._sync()
        assert sync_env.ready_seen == [False]

    @pytest.mark.asyncio
    async def test_ready_once_the_site_is_given_up_on_and_stays_ready(self, sync_env):
        sync_env.skipped = {"a": "no User owned by it"}
        await sync_env.ctrl._sync()
        await self.past_timeout()
        await sync_env.ctrl._sync()  # gives up on "a"
        await sync_env.ctrl._sync()  # "a" is still unresolved: must not go back to pending
        await sync_env.ctrl._sync()

        assert sync_env.ready_seen == [False, True, True, True]
        assert "a" not in sync_env.ctrl._pending_lookups
        assert "a" in sync_env.ctrl._given_up

    @pytest.mark.asyncio
    async def test_a_site_breaking_after_startup_does_not_flip_readiness(self, sync_env):
        await sync_env.ctrl._sync()  # nothing pending: ready from the first sync
        sync_env.skipped = {"b": "no User owned by it"}
        await sync_env.ctrl._sync()  # "b" starts waiting
        await self.past_timeout()
        await sync_env.ctrl._sync()  # "b" given up on
        await sync_env.ctrl._sync()

        assert sync_env.ready_seen == [True, True, True, True]

    @pytest.mark.asyncio
    async def test_given_up_site_is_forgotten_once_it_resolves(self, sync_env):
        sync_env.skipped = {"a": "no User owned by it"}
        await sync_env.ctrl._sync()
        await self.past_timeout()
        await sync_env.ctrl._sync()
        assert "a" in sync_env.ctrl._given_up

        sync_env.skipped = {}  # the User showed up (its event triggered this sync)
        await sync_env.ctrl._sync()
        assert not sync_env.ctrl._given_up
        assert not sync_env.ctrl._pending_lookups

        # Breaking again later starts a fresh wait instead of being ignored.
        sync_env.skipped = {"a": "no User owned by it"}
        await sync_env.ctrl._sync()
        assert "a" in sync_env.ctrl._pending_lookups
        assert sync_env.ready_seen[-1] is True
