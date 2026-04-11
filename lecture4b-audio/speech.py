import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from openai import OpenAI

sync_audio_client = OpenAI()

TTS_MODEL = 'gpt-4o-mini-tts'
TTS_VOICE = 'nova'
TTS_SPEED = 1.3
TRANSCRIBE_MODEL = 'gpt-4o-mini-transcribe'
FFMPEG_PATH = '/opt/homebrew/bin/ffmpeg'
AUDIO_INPUT_DEVICE = ':1'                   # configure this for your audio device (run: ffmpeg -f avfoundation -list_devices true -i "")
SILENCE_DURATION_SECONDS = 0.2
SILENCE_THRESHOLD = '-60dB'
MAX_RECORDING_SECONDS = 12.0
MAX_WAIT_FOR_SPEECH_SECONDS = 8.0


def _write_speech_audio(response, out_path: Path) -> None:
    """Write TTS audio bytes from the API response to a local file."""
    if hasattr(response, 'write_to_file'):
        response.write_to_file(str(out_path))
        return

    content = getattr(response, 'content', None)
    if content is None and hasattr(response, 'read'):
        content = response.read()
    if content is None:
        raise RuntimeError('Unable to extract audio bytes from speech response.')
    out_path.write_bytes(content)


def speak_text(message: str) -> None:
    """Convert text to speech, save it temporarily, and play it locally."""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
        audio_path = Path(handle.name)

    try:
        response = sync_audio_client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=message,
            instructions='Speak in a clear, conversational, encouraging tone.',
            response_format='wav',
            speed=TTS_SPEED,
        )
        _write_speech_audio(response, audio_path)
        subprocess.run(
            ['/usr/bin/afplay', str(audio_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        with suppress(FileNotFoundError):
            audio_path.unlink()


def record_user_audio() -> Path:
    """Record microphone audio to a temporary WAV file until the user stops speaking."""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
        audio_path = Path(handle.name)

    print('Listening...')
    process = subprocess.Popen(
        [
            FFMPEG_PATH,
            '-nostdin',
            '-hide_banner',
            '-y',
            '-f',
            'avfoundation',
            '-i',
            AUDIO_INPUT_DEVICE,
            '-ac',
            '1',
            '-ar',
            '16000',
            '-af',
            f'silencedetect=noise={SILENCE_THRESHOLD}:d={SILENCE_DURATION_SECONDS}',
            str(audio_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    heard_speech = False
    start_time = time.monotonic()
    stderr_lines: list[str] = []

    try:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line.rstrip())
            if len(stderr_lines) > 40:
                stderr_lines.pop(0)

            elapsed = time.monotonic() - start_time

            if 'silence_end:' in line:
                heard_speech = True
            elif heard_speech and 'silence_start:' in line:
                break

            if elapsed >= MAX_RECORDING_SECONDS:
                break
    finally:
        with suppress(ProcessLookupError):
            process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()

    if process.returncode not in (0, 255):
        stderr_tail = '\n'.join(stderr_lines[-10:])
        raise RuntimeError(f'Audio capture failed.\n{stderr_tail}')

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError('No audio was captured from the microphone.')

    return audio_path


def transcribe_audio(audio_path: Path) -> str:
    """Send recorded audio to the transcription model and return the text."""
    with audio_path.open('rb') as audio_file:
        response = sync_audio_client.audio.transcriptions.create(
            file=audio_file,
            model=TRANSCRIBE_MODEL,
        )

    if isinstance(response, str):
        return response.strip()

    text = getattr(response, 'text', '')
    return text.strip()


def listen_for_user() -> str:
    """Record the user, transcribe the speech, and return the resulting text."""
    for attempt in range(2):
        audio_path = record_user_audio()
        try:
            transcript = transcribe_audio(audio_path)
        finally:
            with suppress(FileNotFoundError):
                audio_path.unlink()

        if transcript:
            print(f'User: {transcript}')
            return transcript

        if attempt == 0:
            print('I did not catch that. Please try again.')

    raise RuntimeError(
        'Audio was recorded twice, but no transcript was returned. '
        'Try speaking louder, closer to the microphone, or increasing the pause after you finish speaking.'
    )
