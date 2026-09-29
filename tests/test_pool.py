"""Regression tests for the worker pool used by nemu_ipc.

Guards the crash reported as `KeyError: WorkerThread(Alasio thread N)` raised from
`WorkerThread._work()` (pool.py:251):

  1. `nemu_ipc` runs every call on a separated thread with a timeout, so a hung
     call turns into `Job.get_or_kill()` -> `Job._kill()` -> `WorkerThread.kill()`.
  2. `kill()` pops the victim out of `WorkerPool.all_workers`, but `capture()`
     catches BaseException, so the `_JobKill` request reaches `_handle_job()` as a
     *value*: the thread survived its own kill and looped back to waiting for jobs.
  3. One IDLE_TIMEOUT later that worker reached `del all_workers[self]` for an
     entry `kill()` had already removed, and died with the KeyError.
"""

import sys
import threading
import time
import types

# `module.logger` builds a loguru file sink backed by a multiprocessing queue at
# import time, which needs named pipes. Importing `module.device.method.pool`
# pulls it in for the single `logger.error()` call in `kill()`, so hand the pool a
# logger stub instead of requiring the real log stack in unit tests.
if "module.logger" not in sys.modules:
    _logger_stub = types.ModuleType("module.logger")
    _logger_stub.logger = types.SimpleNamespace(  # type: ignore[attr-defined]
        error=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    sys.modules["module.logger"] = _logger_stub

import pytest

from module.device.method.pool import JobTimeout, WorkerPool, _JobKill


class _RecordedThreadExceptions:
    """Unhandled exceptions of worker threads, split by expectation."""

    def __init__(self):
        self.kills = []  # `_JobKill` reaching the hook: the intended way to die
        self.crashes = []  # anything else, e.g. the reported KeyError

    def __call__(self, args):
        if args.exc_type is _JobKill:
            self.kills.append(args)
        else:
            self.crashes.append(args)


class _OneShotHang:
    """Callable that blocks until `release()` is called.

    It polls instead of `Event.wait()` without a timeout: an indefinitely blocking
    C-level wait is not interruptible by `PyThreadState_SetAsyncExc`, so `kill()`
    would not reach the thread at all. A hung `nemu_ipc` ctypes call is interruptible
    the same way polling is, since the request is delivered once the thread is back
    in Python code.
    """

    def __init__(self):
        self.released = threading.Event()

    def __call__(self, *args, **kwargs):
        while not self.released.is_set():
            time.sleep(0.01)
        return "released"

    def release(self):
        self.released.set()


def _alive_pool_threads():
    return [t for t in threading.enumerate() if t.name.startswith("Alasio thread")]


class _InterposedWorkers(dict):
    """`all_workers` replacement that runs a hook when a worker leaves the pool.

    Subclassing dict keeps every access the pool makes (`len`, `in`, `pop`,
    iteration) working unchanged; only the removal of a worker is interposed.
    `killed` guards against the recursive `kill()` the hook itself triggers, and
    the hook runs at most once.
    """

    def __init__(self, source, hook, killed):
        super().__init__(source)
        self._hook = hook
        self._killed = killed
        self._fired = False

    def _fire(self, key):
        if not self._fired and key in self and key not in self._killed:
            self._killed.append(key)
            self._fired = True
            self._hook(key)

    def __delitem__(self, key):
        self._fire(key)
        dict.__delitem__(self, key)

    def pop(self, *args, **kwargs):
        self._fire(args[0] if args else None)
        return dict.pop(self, *args, **kwargs)


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def excepthook():
    """Record exceptions that would reach `threading.excepthook`.

    An unhandled exception in a daemon thread neither fails a test nor stops the
    process -- the interpreter reports it and moves on, which is exactly how the
    reported KeyError went unnoticed. Routing the hook into the test turns such a
    thread crash into an assertion failure, while `_JobKill` (the intended way for
    a killed worker to die) is recorded separately.
    """
    recorded = _RecordedThreadExceptions()
    original = threading.excepthook
    threading.excepthook = recorded
    yield recorded
    threading.excepthook = original


@pytest.fixture
def pool(monkeypatch):
    """An isolated pool with a short idle timeout.

    `WorkerThread.__init__` reaches `WorkerPool.IDLE_TIMEOUT` through the module
    global, so patching the class attribute affects workers created afterwards.
    """
    monkeypatch.setattr(WorkerPool, "IDLE_TIMEOUT", 0.5)
    instance = WorkerPool(pool_size=8)
    instance.hangs = []
    yield instance

    # Never let a failing test leave a live daemon thread behind.
    for hang in instance.hangs:
        hang.release()
    for worker in list(instance.all_workers) + list(instance.idle_workers):
        worker.kill()
    _wait_until(lambda: not _alive_pool_threads(), timeout=5.0)


def test_worker_exit_after_kill_does_not_raise(pool, excepthook):
    """`kill()` may remove a worker that is already inside its exit path.

    Interleaving behind the reported traceback, replayed deterministically:

      1. The worker's wait for a job times out; it removes itself from
         `idle_workers` and starts its exit path.
      2. Another thread calls `kill()`, which removes it from `all_workers`.
      3. The worker removes itself from `all_workers`, an entry that is already
         gone -- the `del` that raised KeyError in the report.

    Step 2 is a separate thread because `kill()` sends `_JobKill` into the worker it
    targets: that request would end the worker inside this hook, before it ever
    reached step 3. The test therefore replays only the removal step, which is the
    part the exit path trips over.
    """
    job = pool.start_thread_soon(lambda: None)
    assert job.get() is None

    (worker,) = pool.all_workers
    assert worker in pool.idle_workers

    # Hold the worker lock so the victim blocks in its next `acquire()`, which is
    # the last thing it does before its exit path.
    worker_lock = threading.Lock()
    worker_lock.acquire()
    worker.worker_lock = worker_lock

    # Released from inside the exit path, so the test knows the victim got there.
    at_exit = threading.Event()
    # The killer does its work before the victim may finish the exit path.
    killer_done = threading.Event()

    def kill_in_exit_window(key):
        """Called between the worker's `idle_workers` and `all_workers` removals."""
        if key is not worker or at_exit.is_set():
            return
        assert worker not in pool.idle_workers, "the exit path has started"

        def killer():
            # Mirrors WorkerThread.kill(): remove the worker, then send the request.
            # The request is skipped, see the docstring.
            pool.all_workers.pop(worker, None)
            killer_done.set()

        threading.Thread(target=killer, name="pool-killer").start()
        at_exit.set()
        # Hold the victim inside its exit path until the killer has removed it.
        assert killer_done.wait(timeout=5), "the killer never removed the worker"

    pool.all_workers = _InterposedWorkers(pool.all_workers, kill_in_exit_window, [])

    # Let the worker run into its idle timeout and out through the exit path, and
    # wait for the killer: on the buggy `del`, the victim dies right there.
    assert at_exit.wait(timeout=5), "worker never reached its exit path"
    assert _wait_until(lambda: not worker.thread.is_alive()), "worker did not exit"

    assert killer_done.is_set()
    assert worker not in pool.all_workers
    assert worker not in pool.idle_workers
    assert excepthook.crashes == [], f"worker thread crashed: {[a.exc_value for a in excepthook.crashes]}"


def test_killed_worker_does_not_return_to_idle(pool, excepthook):
    """A worker killed while running a job must exit instead of idling again.

    Before the fix the victim re-registered itself in `idle_workers` while missing
    from `all_workers`, then crashed there one IDLE_TIMEOUT later. `nemu_ipc`
    produces this on every hung call, and it surfaces once the task queue drains.
    """
    hang = _OneShotHang()
    pool.hangs.append(hang)
    job = pool.start_thread_soon(hang)
    with pytest.raises(JobTimeout):
        job.get_or_kill(timeout=0.2)

    assert pool.all_workers == {}
    assert _wait_until(lambda: (not _alive_pool_threads()) and pool.idle_workers == {}), (
        f"killed worker stayed alive or went back to idle: "
        f"alive={[t.name for t in _alive_pool_threads()]} idle={[w.default_name for w in pool.idle_workers]}"
    )
    assert excepthook.kills, "the kill request never reached the worker"

    # The reported crash happened one IDLE_TIMEOUT after the kill; wait it out.
    time.sleep(WorkerPool.IDLE_TIMEOUT + 0.5)
    assert pool.all_workers == {}
    assert pool.idle_workers == {}
    assert excepthook.crashes == [], f"worker thread crashed: {[a.exc_value for a in excepthook.crashes]}"
