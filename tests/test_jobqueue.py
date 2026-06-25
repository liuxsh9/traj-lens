"""Two-lane job queue: lanes drain independently; LLM lane reuses one event
loop while the CPU lane runs without one."""
import threading

from trajlens.api import jobqueue


def test_llm_lane_reuses_one_loop_cpu_lane_has_none():
    seen_llm: list = []
    seen_cpu: list = []
    done = threading.Event()
    n = 3

    def llm_task(loop):
        seen_llm.append(id(loop))  # loop object identity across jobs
        if len(seen_llm) == n:
            done.set()

    for _ in range(n):
        jobqueue.submit_llm(llm_task)
    assert done.wait(5)
    assert len(set(seen_llm)) == 1  # same persistent loop every time
    assert seen_llm[0] is not None

    done.clear()
    def cpu_task(loop):
        seen_cpu.append(loop)
        if len(seen_cpu) == n:
            done.set()
    for _ in range(n):
        jobqueue.submit_cpu(cpu_task)
    assert done.wait(5)
    assert seen_cpu == [None, None, None]  # CPU lane passes no loop


def test_lanes_are_independent():
    """A blocked CPU job must not hold up an LLM job (separate workers)."""
    cpu_gate = threading.Event()
    llm_ran = threading.Event()

    jobqueue.submit_cpu(lambda loop: cpu_gate.wait(5))  # occupy CPU lane
    jobqueue.submit_llm(lambda loop: llm_ran.set())     # must still run
    assert llm_ran.wait(5)
    cpu_gate.set()  # release the CPU worker


def test_bad_job_does_not_kill_lane():
    survived = threading.Event()
    jobqueue.submit_cpu(lambda loop: (_ for _ in ()).throw(RuntimeError("boom")))
    jobqueue.submit_cpu(lambda loop: survived.set())
    assert survived.wait(5)  # second job still ran after the first raised
