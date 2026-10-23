import threading
import time

from remastr.jobs import JobRunner, JobStore
from remastr.models import JobStatus, JobType


def wait_for(store, job_id, statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job.status in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {store.get(job_id).status}")


def make_runner(tmp_path, handlers):
    runner = JobRunner(JobStore(tmp_path / "jobs.db"), handlers)
    runner.start()
    return runner


def test_dependency_runs_after_parent(tmp_path):
    order = []
    runner = make_runner(
        tmp_path,
        {
            JobType.download: lambda ctx: order.append("download"),
            JobType.process: lambda ctx: order.append("process"),
        },
    )
    try:
        dl = runner.submit(JobType.download, "1")
        proc = runner.submit(JobType.process, "1", depends_on=dl.id)
        wait_for(runner.store, proc.id, {JobStatus.done})
        assert order == ["download", "process"]
    finally:
        runner.stop()


def test_failed_parent_fails_dependents(tmp_path):
    def boom(ctx):
        raise RuntimeError("ftp down")

    runner = make_runner(tmp_path, {JobType.download: boom, JobType.process: lambda ctx: None})
    try:
        dl = runner.submit(JobType.download, "1")
        proc = runner.submit(JobType.process, "1", depends_on=dl.id)
        assert "ftp down" in wait_for(runner.store, dl.id, {JobStatus.failed}).message
        assert wait_for(runner.store, proc.id, {JobStatus.failed}).message.startswith("Dependency")
    finally:
        runner.stop()


def test_cancel_running_job(tmp_path):
    started = threading.Event()

    def long_job(ctx):
        started.set()
        while not ctx.cancel.is_set():
            time.sleep(0.01)
        from remastr.pipeline import Cancelled

        raise Cancelled()

    runner = make_runner(tmp_path, {JobType.process: long_job})
    try:
        job = runner.submit(JobType.process, "1")
        assert started.wait(5)
        runner.cancel(job.id)
        wait_for(runner.store, job.id, {JobStatus.cancelled})
    finally:
        runner.stop()


def test_restart_marks_running_jobs_failed(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create(JobType.process, "1")
    store.update(job.id, status=JobStatus.running)
    JobRunner(store, {}).store.mark_interrupted()
    assert store.get(job.id).status == JobStatus.failed
