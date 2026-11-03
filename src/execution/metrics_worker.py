"""Trusted standalone JSON-lines worker copied into the container, never imported by host.

Only algorithm.py and this file are mounted. Each step contains exactly the
current processed observation. No dataset paths, labels, role manifests or keys.
"""

import contextlib
import importlib.util
import json
import sys
import traceback


def parse(raw):
    def invalid(_):
        raise ValueError("non-JSON numeric constant")
    return json.loads(raw, parse_constant=invalid)


def state_text(detector):
    raw = detector.save_state()
    if not isinstance(raw, str) or len(raw.encode()) > 128 * 1024 or not isinstance(parse(raw), dict):
        raise ValueError("save_state must return bounded JSON object text")
    return raw


def main():
    spec = importlib.util.spec_from_file_location("algorithm", "/code/algorithm.py")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
    detector = None
    for raw in iter(lambda: sys.stdin.buffer.readline(32 * 1024 * 1024 + 1), b""):
        if len(raw) > 32 * 1024 * 1024 or not raw.endswith(b"\n"):
            break
        try:
            request = parse(raw)
            operation = request["op"]
            with contextlib.redirect_stdout(sys.stderr):
                if operation == "fit":
                    detector = module.create_detector(request["config"])
                    detector.fit(request["points"])
                    result = None
                elif detector is None:
                    raise ValueError("fit required")
                elif operation == "reset":
                    detector.reset()
                    result = None
                elif operation == "step":
                    result = detector.score_one(request["point"])
                elif operation == "save":
                    result = state_text(detector)
                elif operation == "load":
                    state = request["state"]
                    if not isinstance(state, str) or len(state.encode()) > 128 * 1024 or not isinstance(parse(state), dict):
                        raise ValueError("invalid JSON state")
                    detector.load_state(state)
                    result = None
                elif operation == "close":
                    break
                else:
                    raise ValueError("unknown operation")
            response = {"ok": True, "result": result}
            encoded = json.dumps(response, allow_nan=False)
            if len(encoded.encode()) > 128 * 1024:
                raise ValueError("worker response too large")
        except Exception as error:
            frames = [frame.lineno for frame in traceback.extract_tb(error.__traceback__)
                      if frame.filename == "/code/algorithm.py"]
            encoded = json.dumps({"ok": False, "error": {"code": "CANDIDATE_ERROR",
                                  "type": type(error).__name__, "line": frames[-1] if frames else None,
                                  "message": str(error)[:500]}}, allow_nan=False)
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
