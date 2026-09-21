"""Keep the test run from ending in a native crash.

When OCR has run, onnxruntime's telemetry teardown can race a worker thread at interpreter exit and abort
the process (SIGABRT, macOS "Python quit unexpectedly") after the results are printed. Leaving directly
once pytest has finished reporting skips that teardown. Only done when onnxruntime was loaded.
"""
import atexit
import os
import sys

_status = 0


def pytest_sessionfinish(session, exitstatus):
    global _status
    _status = int(exitstatus)


def pytest_unconfigure(config):  # runs after the summary has been printed
    if "onnxruntime" in sys.modules:
        atexit._run_exitfuncs()  # release multiprocessing's semaphores; skip only the crashing C++ teardown
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_status)
