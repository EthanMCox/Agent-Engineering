#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

# Basic static check (not a security guarantee — just demo safety)
FORBIDDEN_PATTERNS = [
    "socket",
    "requests",
    "paramiko",
    "ssh",
    "curl",
    "wget",
    "os.environ",
    "open('/etc",
    "docker",
    "/var/run/docker.sock"
]

def contains_forbidden(code_text):
    lower = code_text.lower()
    return any(pat in lower for pat in FORBIDDEN_PATTERNS)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "missing script path"}))
        sys.exit(2)

    script_path = sys.argv[1]
    timeout = 10

    if "--timeout" in sys.argv:
        try:
            timeout = int(sys.argv[sys.argv.index("--timeout") + 1])
        except Exception:
            pass

    # load the provided python script
    try:
        code_text = Path(script_path).read_text()
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"cannot read script: {e}"}))
        sys.exit(2)

    # confirm whether it looks "safe"
    if contains_forbidden(code_text):
        print(json.dumps({"ok": False, "error": "forbidden patterns detected"}))
        sys.exit(2)

    # execute the provided script and capture the output
    try:
        proc = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        result = {
            "ok": True,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timeout_seconds": timeout
        }
    except subprocess.TimeoutExpired as e:
        result = {
            "ok": False,
            "error": "timeout",
            "stdout": e.stdout or "",
            "stderr": e.stderr or ""
        }
    except Exception as e:
        result = {"ok": False, "error": f"execution error: {e}"}

    print(json.dumps(result))

if __name__ == "__main__":
    main()
