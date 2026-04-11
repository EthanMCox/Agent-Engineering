# Audio Demos

This directory contains several small demos for teaching speech, transcription, and realtime audio interaction with OpenAI models.

## `speech.py`
Shared helper module for local audio input/output.

- Text-to-speech with `gpt-4o-mini-tts`
- Microphone recording with `ffmpeg`
- File-based speech-to-text with `gpt-4o-mini-transcribe`
- Local playback with `afplay`

This file is used by other demos and is not meant to be run directly.

## `agents.py`
Multi-agent CLI app with a `talk_to_user()` tool and a `talk_to_user_realtime()` tool.

- Reads an agent config file in YAML format
- Lets an agent speak to the user and listen for spoken replies
- Can use either the file-based speech path or the Realtime API path depending on the tool configured in the YAML

Example:

```bash
python agents.py twenty_questions.yaml
```

## `twenty_questions.yaml`
Agent configuration for a spoken 20 Questions animal game.

- Uses the tools defined in `agents.py`
- Instructs the model how to explain and run the game

## `speech_to_text.py`
Command-line speech-to-text demo.

- Press Enter to start recording
- Press Enter again to stop
- Prints the transcription or translation result
- Supports an optional prompt to bias the transcription
- Tracks usage across runs and prints totals when you quit

Examples:

```bash
python speech_to_text.py
python speech_to_text.py --mode translate
python speech_to_text.py --prompt-file my_prompt.txt
```

## `text_to_speech.py`
Command-line text-to-speech demo.

- Enter text
- Generates speech audio from that text
- Plays it locally with `afplay`
- Tracks usage across runs and prints totals when you quit

Examples:

```bash
python text_to_speech.py
python text_to_speech.py --text "Hello class"
python text_to_speech.py --voice marin
```

## `realtime.py`
Helper module for the realtime speech-input path.

- Streams microphone audio to the Realtime API
- Uses server-side turn detection / VAD
- Returns transcribed user speech as text

Used by `agents.py` for the `talk_to_user_realtime()` tool.

## `realtime_chat.py`
Standalone speech-to-speech realtime chat demo.

- Streams microphone audio continuously to the Realtime API
- Receives assistant transcript text and audio responses
- Plays completed assistant audio responses locally
- Useful for demonstrating full duplex-style voice interaction, though it is more experimental than the file-based demos

Example:

```bash
python realtime_chat.py
```

## `run_agent.py`
Core multi-agent execution loop.

- Sends messages to the Responses API
- Handles tool calls
- Recursively runs sub-agents when they are exposed as tools

## `tools.py`
Tool registration and execution helpers used by the agent demos.

## `usage.py`
Utility for aggregating and printing token/cost usage across calls.
