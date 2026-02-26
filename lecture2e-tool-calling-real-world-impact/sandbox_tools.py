"""
Tools for interacting with a sandboxed Docker container filesystem.
All file operations happen within the container, not on the host.
"""

import subprocess
import json
from typing import Literal

CONTAINER_NAME = "sandbox-bot"


def _exec_in_container(command: list[str], timeout: int = 10) -> dict:
    """Execute a command in the sandbox container"""
    try:
        docker_cmd = ["docker", "exec", CONTAINER_NAME] + command
        proc = subprocess.run(
            docker_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": "timeout",
            "stdout": e.stdout or "",
            "stderr": e.stderr or ""
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def sandbox_read_file(path: str) -> str:
    """Read a file from the sandbox filesystem.
    
    Args:
        path: Path to the file in the sandbox (e.g., '/sandbox/myfile.txt')
    """
    result = _exec_in_container(["cat", path])
    if result["ok"]:
        return result["stdout"]
    else:
        return f"Error reading file: {result.get('stderr', result.get('error', 'unknown'))}"


def sandbox_write_file(path: str, content: str) -> str:
    """Write content to a file in the sandbox filesystem.
    
    Args:
        path: Path where to write the file in sandbox (e.g., '/sandbox/myfile.txt')
        content: Content to write to the file
    """
    # Use tee to write content (works without pipes)
    result = _exec_in_container(["sh", "-c", f"echo {repr(content)} | tee {path} > /dev/null"])
    if result["ok"]:
        return f"Successfully wrote to {path}"
    else:
        return f"Error writing file: {result.get('stderr', result.get('error', 'unknown'))}"


def sandbox_list_files(path: str = "/sandbox") -> str:
    """List files in a directory in the sandbox filesystem.
    
    Args:
        path: Directory path to list (default: /sandbox)
    """
    result = _exec_in_container(["ls", "-lah", path])
    if result["ok"]:
        return result["stdout"]
    else:
        return f"Error listing directory: {result.get('stderr', result.get('error', 'unknown'))}"


def sandbox_exec_python(code: str) -> str:
    """Execute Python code in the sandbox container.
    
    Args:
        code: Python code to execute
    """
    # Write code to a temp file and execute it
    result = _exec_in_container([
        "sh", "-c",
        f"echo {repr(code)} > /tmp/exec.py && python /tmp/exec.py"
    ])
    
    output = []
    if result["stdout"]:
        output.append(f"STDOUT:\n{result['stdout']}")
    if result["stderr"]:
        output.append(f"STDERR:\n{result['stderr']}")
    if not result["ok"]:
        output.append(f"Exit code: {result['exit_code']}")
    
    return "\n\n".join(output) if output else "No output"


def sandbox_exec_command(command: str) -> str:
    """Execute a shell command in the sandbox container.
    
    Args:
        command: Shell command to execute (e.g., 'pwd', 'mkdir test', 'ls -la')
    """
    result = _exec_in_container(["sh", "-c", command])
    
    output = []
    if result["stdout"]:
        output.append(f"STDOUT:\n{result['stdout']}")
    if result["stderr"]:
        output.append(f"STDERR:\n{result['stderr']}")
    if not result["ok"]:
        output.append(f"Exit code: {result['exit_code']}")
    
    return "\n\n".join(output) if output else "Command completed successfully"


def sandbox_delete_file(path: str) -> str:
    """Delete a file from the sandbox filesystem.
    
    Args:
        path: Path to the file to delete
    """
    result = _exec_in_container(["rm", path])
    if result["ok"]:
        return f"Successfully deleted {path}"
    else:
        return f"Error deleting file: {result.get('stderr', result.get('error', 'unknown'))}"


def sandbox_create_directory(path: str) -> str:
    """Create a directory in the sandbox filesystem.
    
    Args:
        path: Path of directory to create
    """
    result = _exec_in_container(["mkdir", "-p", path])
    if result["ok"]:
        return f"Successfully created directory {path}"
    else:
        return f"Error creating directory: {result.get('stderr', result.get('error', 'unknown'))}"


def check_sandbox_status() -> str:
    """Check if the sandbox container is running"""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            return "Sandbox container is running"
        else:
            return "Sandbox container is not running. Start it with: docker run -d --name sandbox-bot --rm sandbox-bot:latest"
    except Exception as e:
        return f"Error checking sandbox status: {e}"
