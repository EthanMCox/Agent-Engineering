import json
import tempfile
import os
import subprocess
from openai import OpenAI   # replace with your actual client import/setup

client = OpenAI()   # configure with API key / env

EXEC_IMAGE = "safe-container:latest"

def execute_code(python_code: str, timeout: int) -> dict:
    """Execute a python script. Return results in json format.
    	python_script: the script to run
    	timeout: max length the script can run before termination
    """

    print(f'\n---------------\nDEBUG executing code in container\n---------------')

    # write code to a temporary file on the host
    with tempfile.TemporaryDirectory() as tmpdir:
        host_script = os.path.join(tmpdir, "task.py")
        with open(host_script, "w", encoding="utf-8") as f:
            f.write(python_code)

        # compose docker run command (no network, resource caps, read-only runner)
        # mount the host script into /workspace/task.py read-only
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--cpus=0.5",
            "--memory=256m",
            "--pids-limit=50",
            "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777",
            "--user", "1000:1000",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "-v", f"{host_script}:/workspace/task.py:ro",
            EXEC_IMAGE,
            "/workspace/task.py", "--timeout", str(timeout)
        ]

        try:
            proc = subprocess.run(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout + 5  # a little headroom for docker startup
            )
            # runner prints a single JSON object to stdout
            raw = proc.stdout.strip()
            try:
                runner_result = json.loads(raw) if raw else {"ok": False, "error": "no output", "stdout": "",
                                                             "stderr": proc.stderr}
            except json.JSONDecodeError:
                runner_result = {"ok": False, "error": "bad-runner-output", "stdout": raw, "stderr": proc.stderr}
        except subprocess.TimeoutExpired as e:
            runner_result = {"ok": False, "error": "docker-run-timeout", "stdout": e.stdout or "",
                             "stderr": e.stderr or ""}
    return runner_result


# async def handle_model_response(response):
#     """
#     response: object returned by client.responses.create(...) that contains .id and .output items.
#     This inspects .output for function_call items and executes them.
#     """
#     tool_outputs = []
#     prev_response_id = response.id
#
#     for item in response.output:
#         # only handle function_call items
#         if getattr(item, "type", None) != "function_call":
#             continue
#
#         if item.name != "execute_code":
#             continue
#
#         # item.arguments is a JSON string per Responses API
#         args = json.loads(item.arguments)
#
#         # only python supported in this demo
#         lang = args.get("language", "python")
#         code = args.get("code", "")
#         timeout = int(args.get("timeout", 10))
#
#         # write code to a temporary file on the host
#         with tempfile.TemporaryDirectory() as tmpdir:
#             host_script = os.path.join(tmpdir, "task.py")
#             with open(host_script, "w", encoding="utf-8") as f:
#                 f.write(code)
#
#             # compose docker run command (no network, resource caps, read-only runner)
#             # mount the host script into /workspace/task.py read-only
#             docker_cmd = [
#                 "docker", "run", "--rm",
#                 "--network", "none",
#                 "--cpus=0.5",
#                 "--memory=256m",
#                 "--pids-limit=50",
#                 "--read-only",
#                 "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777",
#                 "--user", "1000:1000",
#                 "--cap-drop", "ALL",
#                 "--security-opt", "no-new-privileges:true",
#                 "-v", f"{host_script}:/workspace/task.py:ro",
#                 EXEC_IMAGE,
#                 "/workspace/task.py", "--timeout", str(timeout)
#             ]
#
#             try:
#                 proc = subprocess.run(
#                     docker_cmd,
#                     stdout=subprocess.PIPE,
#                     stderr=subprocess.PIPE,
#                     text=True,
#                     timeout=timeout + 5  # a little headroom for docker startup
#                 )
#                 # runner prints a single JSON object to stdout
#                 raw = proc.stdout.strip()
#                 try:
#                     runner_result = json.loads(raw) if raw else {"ok": False, "error": "no output", "stdout": "", "stderr": proc.stderr}
#                 except json.JSONDecodeError:
#                     runner_result = {"ok": False, "error": "bad-runner-output", "stdout": raw, "stderr": proc.stderr}
#             except subprocess.TimeoutExpired as e:
#                 runner_result = {"ok": False, "error": "docker-run-timeout", "stdout": e.stdout or "", "stderr": e.stderr or ""}
#
#         # construct the function_call_output entry referencing the original call_id
#         tool_outputs.append({
#             "type": "function_call_output",
#             "call_id": item.call_id,   # must match the function_call's call_id
#             "output": json.dumps(runner_result)
#         })
#
#     if not tool_outputs:
#         # nothing to do
#         return response
#
#     # continue the conversation using previous_response_id, supplying only the tool outputs
#     followup = await client.responses.create(
#         model=MODEL_NAME,
#         previous_response_id=prev_response_id,
#         input=tool_outputs
#     )
#
#     return followup
