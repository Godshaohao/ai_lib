from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory


class WebJobSchedulerTest(unittest.TestCase):
    def test_admission_caps_running_jobs_and_rejects_excess_queue(self):
        from lib_guard.web.job_scheduler import JobAdmission

        admission = JobAdmission(max_workers=1, max_pending=1)
        gate = threading.Event()
        started = threading.Event()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            first = admission.submit(pool, lambda: (started.set(), gate.wait(2)))
            self.assertTrue(started.wait(1))
            second = admission.submit(pool, lambda: None)
            with self.assertRaises(RuntimeError):
                admission.submit(pool, lambda: None)
            gate.set()
            first.result(timeout=2)
            second.result(timeout=2)
        finally:
            gate.set()
            pool.shutdown(wait=True)

    def test_mutating_jobs_conflict_per_library_but_semantic_review_can_overlap(self):
        from lib_guard.web.job_scheduler import actions_conflict

        self.assertTrue(actions_conflict("scan", "cmp"))
        self.assertFalse(actions_conflict("scan", "semantic-review"))
        self.assertFalse(actions_conflict("semantic-review", "scan"))
        self.assertTrue(actions_conflict("scan", "scan"))

    def test_shared_slot_files_bound_concurrency_across_scheduler_instances(self):
        from lib_guard.web.job_scheduler import acquire_global_slot

        with TemporaryDirectory() as temp_dir:
            lock_root = Path(temp_dir)
            active = 0
            peak = 0
            guard = threading.Lock()
            barrier = threading.Barrier(4)

            def run_one():
                nonlocal active, peak
                barrier.wait(timeout=2)
                with acquire_global_slot(lock_root, 2, poll_interval=0.01):
                    with guard:
                        active += 1
                        peak = max(peak, active)
                    time.sleep(0.04)
                    with guard:
                        active -= 1

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(run_one) for _ in range(4)]
                for future in futures:
                    future.result(timeout=3)
            self.assertEqual(peak, 2)

    def test_catalog_writer_lock_serializes_writes_from_different_libraries(self):
        from lib_guard.web.job_scheduler import acquire_catalog_writer_lock

        with TemporaryDirectory() as temp_dir:
            lock_root = Path(temp_dir)
            entered = threading.Event()
            release = threading.Event()
            second_writer_entered = threading.Event()

            def hold_first():
                with acquire_catalog_writer_lock(lock_root):
                    entered.set()
                    release.wait(2)

            def wait_second_writer():
                with acquire_catalog_writer_lock(lock_root):
                    second_writer_entered.set()

            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(hold_first)
                self.assertTrue(entered.wait(1))
                second_writer = pool.submit(wait_second_writer)
                time.sleep(0.05)
                self.assertFalse(second_writer_entered.is_set())
                release.set()
                first.result(timeout=2)
                second_writer.result(timeout=2)
            self.assertTrue(second_writer_entered.is_set())


if __name__ == "__main__":
    unittest.main()
