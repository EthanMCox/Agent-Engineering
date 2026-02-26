# Sandbox Bot - Containerized AI Agent

A secure AI agent that operates entirely within a Docker container. The bot can read, write, and manipulate files, but only within the isolated sandbox environment—never touching your actual filesystem.

## Features

- 🔒 **Isolated Filesystem** - All operations happen in a Docker container
- 👤 **Human-in-the-Loop** - Requires approval for all destructive actions
- 🛠️ **Full Tool Access** - Read, write, execute code, run shell commands
- 🚫 **No Network** - Container has no internet access
- ⚡ **Resource Limited** - 1 CPU, 512MB RAM max

## Setup

### 1. Build the Sandbox Container

```powershell
cd docker/sandbox
docker build -t sandbox-bot:latest .
```

Or on Linux/Mac:
```bash
./build.sh
```

### 2. Start the Container

```powershell
docker run -d --name sandbox-bot --rm --network none --cpus="1.0" --memory="512m" --cap-drop ALL --security-opt no-new-privileges:true sandbox-bot:latest
```

Or use the script:
```bash
./start.sh    # Linux/Mac
```

### 3. Verify It's Running

```powershell
docker ps | findstr sandbox-bot
```

You should see the container running.

## Usage

### Console Mode (with approval prompts)

```powershell
cd C:\Users\ethan\CS-301R-Agent-Engineering\lecture2e-tool-calling-real-world-impact
python toolbot_sandbox.py
```

### Web Interface

```powershell
python toolbot_sandbox.py --web
```

**Note:** In web mode, you'll need to monitor the console for approval prompts!

### With a System Prompt

```powershell
python toolbot_sandbox.py sandbox_prompt.md --show-reasoning
```

## Available Tools

The bot has these sandbox tools (all require approval):

| Tool | Description |
|------|-------------|
| `sandbox_read(path)` | Read a file from the sandbox |
| `sandbox_write(path, content)` | Write content to a file |
| `sandbox_list(path)` | List files in a directory |
| `sandbox_python(code)` | Execute Python code |
| `sandbox_command(cmd)` | Execute shell command |
| `sandbox_delete(path)` | Delete a file |
| `sandbox_mkdir(path)` | Create a directory |
| `sandbox_status()` | Check if container is running |

Plus all the regular toolbot tools (like `get_superbowl_info`).

## Example Interactions

**User:** "Create a file called hello.txt with 'Hello World' in it"

**Agent:** *Calls `sandbox_write("/sandbox/hello.txt", "Hello World")`*

**You see:**
```
========== sandbox_write ==========
Arguments: {'path': '/sandbox/hello.txt', 'content': 'Hello World'}
===================================
Allow this action? [y/N] y
```

**Agent:** "✓ Successfully created hello.txt"

---

**User:** "List all files in /sandbox"

**Agent:** *Calls `sandbox_list("/sandbox")`*

**You approve:** y

**Agent:** Shows file listing

---

**User:** "Write a Python script that calculates fibonacci numbers"

**Agent:** *Calls `sandbox_python(code)`*

**You approve:** y

**Agent:** Executes code and shows results

## Security Features

### Container Isolation
- ✅ No access to your host filesystem
- ✅ No network access
- ✅ Limited CPU/memory
- ✅ Runs as non-root user
- ✅ All capabilities dropped

### Human-in-the-Loop
- ✅ Every file operation requires approval
- ✅ Code execution requires approval
- ✅ Shell commands require approval
- ✅ You see exactly what will be executed

### What the Bot CAN Do
- ✓ Create/read/write files in `/sandbox`
- ✓ Execute Python code
- ✓ Run shell commands (ls, mkdir, etc.)
- ✓ Install Python packages (within container)
- ✓ Access standard Linux utilities

### What the Bot CANNOT Do
- ✗ Access your actual files
- ✗ Access the internet
- ✗ See your environment variables
- ✗ Escape the container
- ✗ Use excessive resources

## Maintenance

### Check Container Status

```powershell
python -c "from sandbox_tools import check_sandbox_status; print(check_sandbox_status())"
```

### Stop the Container

```powershell
docker stop sandbox-bot
```

### View Container Files

```powershell
docker exec sandbox-bot ls -la /sandbox
```

### Access Container Shell (for debugging)

```powershell
docker exec -it sandbox-bot /bin/bash
```

### Clean Up

The container is created with `--rm` so it automatically deletes itself when stopped. All files created inside are lost when the container stops (unless you mount a volume).

## Persistence (Optional)

To keep files between runs, mount a volume:

```powershell
docker run -d --name sandbox-bot --rm `
  --network none --cpus="1.0" --memory="512m" `
  -v sandbox-data:/sandbox `
  sandbox-bot:latest
```

This creates a named volume `sandbox-data` that persists.

## Troubleshooting

**"Sandbox container is not running"**
- Start it: `docker run -d --name sandbox-bot --rm sandbox-bot:latest`

**"Error: Conflict. The container name '/sandbox-bot' is already in use"**
- Stop existing: `docker stop sandbox-bot`
- Or use: `docker rm -f sandbox-bot`

**Container exited immediately**
- Check logs: `docker logs sandbox-bot`
- The `sleep infinity` should keep it running

**Tool calls fail**
- Verify container is running: `docker ps`
- Check if Docker daemon is running

## Use Cases

This sandbox bot is perfect for:
- 🧪 Experimenting with AI-generated code safely
- 📝 Having AI manage a project directory
- 🔬 Testing file manipulation logic
- 📚 Creating documentation automatically
- 🛠️ Building multi-file projects with AI assistance
- 🎓 Learning tool-calling without risk

## Architecture

```
User → toolbot_sandbox.py → Approval? → sandbox_tools.py → Docker Container
                                ↓                              ↓
                               Yes                      /sandbox filesystem
```

The agent never directly touches your files—everything goes through Docker!
