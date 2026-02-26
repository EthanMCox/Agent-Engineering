# Quick Start Guide for Sandbox Bot

## Windows PowerShell Commands

### Build the container

```powershell
cd docker/sandbox
docker build -t sandbox-bot:latest .
cd ../..
```

### Start the container

```powershell
docker run -d --name sandbox-bot --rm --network none --cpus="1.0" --memory="512m" --cap-drop ALL --security-opt no-new-privileges:true sandbox-bot:latest
```

### Verify it's running

```powershell
docker ps | findstr sandbox-bot
```

### Run the bot

```powershell
python toolbot_sandbox.py sandbox_prompt.md --show-reasoning
```

### Stop the container when done

```powershell
docker stop sandbox-bot
```

## Try These Example Prompts

- "Check what files are in /sandbox"
- "Create a file called test.txt with 'Hello World' in it"
- "Write a Python script that prints the first 10 fibonacci numbers"
- "Create a directory called projects and make a README.md inside it"
- "List all files recursively"
- "Execute a Python script that tests if the container can access the network" (it can't!)
