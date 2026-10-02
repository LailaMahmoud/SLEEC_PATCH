import threading
import time
from collections import OrderedDict

from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine


class FakeDetector:
    def __init__(self):
        self.state_lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run_text(self, sleec_text):
        with self.state_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

        # Give the second thread enough time to try entering the detector.
        time.sleep(0.05)

        with self.state_lock:
            self.active -= 1

        return {"text": sleec_text}


def test_run_detector_cached_serializes_detector_execution():
    engine = SLEECPatchWorkbenchEngine.__new__(SLEECPatchWorkbenchEngine)

    detector = FakeDetector()
    engine.detector = detector
    engine.detector_cache = OrderedDict()
    engine.detector_cache_lock = threading.RLock()
    engine.detector_execution_lock = threading.RLock()
    engine.detector_cache_max_entries = 64

    barrier = threading.Barrier(3)
    results = []

    def worker(text):
        barrier.wait()
        results.append(engine.run_detector_cached(text))

    t1 = threading.Thread(target=worker, args=("spec-A",))
    t2 = threading.Thread(target=worker, args=("spec-B",))

    t1.start()
    t2.start()

    # Release both workers at approximately the same time.
    barrier.wait()

    t1.join()
    t2.join()

    assert detector.max_active == 1
    assert len(results) == 2
    assert {result["text"] for result in results} == {"spec-A", "spec-B"}
