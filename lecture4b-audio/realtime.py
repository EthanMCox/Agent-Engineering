import asyncio
import base64
import json
import os
import ssl
import subprocess
import time
from contextlib import suppress

import certifi
import websockets

from speech import AUDIO_INPUT_DEVICE, FFMPEG_PATH

#   The flow is:
#
#   1. Open a secure WebSocket connection to the Realtime endpoint.
#   2. Send a session.update event to configure the session.
#      That tells the server:
#       - we are sending audio input
#       - we want transcription
#       - use server-side VAD to detect when the user starts and stops speaking
#   3. Start ffmpeg locally to read microphone audio.
#      It converts the mic input into raw 24kHz PCM bytes.
#   4. Read those bytes in small chunks and send them to the server with input_audio_buffer.append.
#      Each chunk is base64-encoded before being sent.
#   5. Listen for server events coming back.
#      The important ones are:
#       - input_audio_buffer.speech_started
#       - input_audio_buffer.speech_stopped
#       - transcription delta events
#       - transcription completed
#   6. Build up the transcript as text arrives.
#      If a final completed transcript arrives, return it.
#      If only partial transcript text arrives and then the stream goes quiet, the timeout logic stops waiting and uses what
#      it has.
#   7. If no transcript comes back, it retries once.


REALTIME_MODEL = 'gpt-realtime'
REALTIME_TRANSCRIBE_MODEL = 'gpt-4o-mini-transcribe'
REALTIME_URL = f'wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}'
REALTIME_SAMPLE_RATE = 24000
REALTIME_CHUNK_BYTES = 4800
MAX_WAIT_FOR_SPEECH_SECONDS = 8.0
MAX_TURN_SECONDS = 12.0
POST_SPEECH_TIMEOUT_SECONDS = 4.0
VAD_THRESHOLD = 0.4
VAD_PREFIX_PADDING_MS = 300
VAD_SILENCE_DURATION_MS = 200
VAD_IDLE_TIMEOUT_MS = 6000
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _realtime_headers() -> dict[str, str]:
    """Build the authorization headers required for the Realtime WebSocket."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not set.')
    return {'Authorization': f'Bearer {api_key}'}


def _start_microphone_stream() -> subprocess.Popen:
    """Start ffmpeg and stream raw 24kHz PCM microphone audio to stdout."""
    # ffmpeg acts as the local bridge from the system microphone to raw PCM bytes
    # that we can forward directly to the Realtime API.
    return subprocess.Popen(
        [
            FFMPEG_PATH,
            '-nostdin',
            '-hide_banner',
            '-loglevel',
            'error',
            '-f',
            'avfoundation',
            '-i',
            AUDIO_INPUT_DEVICE,
            '-ac',
            '1',
            '-ar',
            str(REALTIME_SAMPLE_RATE),
            '-f',
            's16le',
            '-acodec',
            'pcm_s16le',
            '-',
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def _send_event(ws, event: dict) -> None:
    """Serialize and send one client event over the Realtime WebSocket."""
    await ws.send(json.dumps(event))


async def _configure_session(ws) -> None:
    """Configure the Realtime session for input-audio transcription with VAD."""
    # This tells the server we are streaming audio in, want transcription out,
    # and want server-side VAD to detect turn boundaries automatically.
    await _send_event(
        ws,
        {
            'type': 'session.update',
            'session': {
                'type': 'realtime',
                'model': REALTIME_MODEL,
                'output_modalities': ['text'],
                'audio': {
                    'input': {
                        'format': {
                            'type': 'audio/pcm',
                            'rate': REALTIME_SAMPLE_RATE,
                        },
                        'transcription': {
                            'model': REALTIME_TRANSCRIBE_MODEL,
                        },
                        'turn_detection': {
                            'type': 'server_vad',
                            'create_response': False,
                            'interrupt_response': False,
                            'threshold': VAD_THRESHOLD,
                            'prefix_padding_ms': VAD_PREFIX_PADDING_MS,
                            'silence_duration_ms': VAD_SILENCE_DURATION_MS,
                            'idle_timeout_ms': VAD_IDLE_TIMEOUT_MS,
                        },
                    },
                },
            },
        },
    )
    


async def _stream_microphone_audio(ws, stop_event: asyncio.Event) -> None:
    """Read microphone PCM chunks and append them to the Realtime input audio buffer."""
    process = _start_microphone_stream()
    start_time = time.monotonic()

    try:
        if process.stdout is None:
            raise RuntimeError('Failed to open microphone audio stream.')

        while not stop_event.is_set():
            # Read one chunk of raw PCM audio from ffmpeg.
            chunk = await asyncio.to_thread(process.stdout.read, REALTIME_CHUNK_BYTES)
            if not chunk:
                break

            # The Realtime API expects audio chunks to be base64-encoded inside a
            # JSON event rather than sent as naked binary.
            await _send_event(
                ws,
                {
                    'type': 'input_audio_buffer.append',
                    'audio': base64.b64encode(chunk).decode('ascii'),
                },
            )

            if time.monotonic() - start_time >= MAX_TURN_SECONDS:
                stop_event.set()
                break
    finally:
        with suppress(ProcessLookupError):
            process.terminate()
        with suppress(subprocess.TimeoutExpired):
            await asyncio.to_thread(process.wait, 5)
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()


async def listen_for_user_realtime() -> str:
    """Stream microphone audio to the Realtime API and return the completed transcript."""
    for attempt in range(2):
        print('Listening (realtime)...')

        stop_event = asyncio.Event()
        transcript = ''
        heard_speech = False
        start_time = time.monotonic()

        async with websockets.connect(
            REALTIME_URL,
            extra_headers=_realtime_headers(),
            max_size=None,
            ssl=SSL_CONTEXT,
        ) as ws:
            # Step 1: open the realtime session and tell the server what behavior we want.
            await _configure_session(ws)

            # Step 2: start shipping microphone audio to the server in the background.
            stream_task = asyncio.create_task(_stream_microphone_audio(ws, stop_event))

            try:
                while True:
                    # Before speech begins we allow a longer timeout; once speech has started
                    # we shorten the wait so the turn completes promptly.
                    timeout = MAX_WAIT_FOR_SPEECH_SECONDS if not heard_speech else POST_SPEECH_TIMEOUT_SECONDS
                    try:
                        raw_message = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except asyncio.TimeoutError:
                        stop_event.set()
                        break

                    event = json.loads(raw_message)
                    event_type = event.get('type')

                    if event_type == 'input_audio_buffer.speech_started':
                        # Server VAD has decided the user started speaking.
                        heard_speech = True

                    elif event_type == 'input_audio_buffer.speech_stopped':
                        # Server VAD has decided the user finished speaking.
                        stop_event.set()

                    elif event_type == 'conversation.item.input_audio_transcription.delta':
                        # Transcription can arrive incrementally, so we accumulate partial text.
                        transcript += event.get('delta', '')

                    elif event_type == 'conversation.item.input_audio_transcription.completed':
                        # When a completed transcript arrives, that is our final user turn text.
                        transcript = event.get('transcript', transcript).strip()
                        stop_event.set()
                        break

                    elif event_type == 'conversation.item.input_audio_transcription.failed':
                        error = event.get('error', {})
                        raise RuntimeError(error.get('message', 'Realtime transcription failed.'))

                    elif event_type == 'error':
                        error = event.get('error', {})
                        raise RuntimeError(error.get('message', 'Realtime session failed.'))

                    if not heard_speech and time.monotonic() - start_time >= MAX_WAIT_FOR_SPEECH_SECONDS:
                        stop_event.set()
                        raise RuntimeError('No speech detected. Please try again.')
            finally:
                stop_event.set()
                with suppress(asyncio.CancelledError):
                    await stream_task

        transcript = transcript.strip()
        if transcript:
            print(f'User: {transcript}')
            return transcript

        if attempt == 0:
            # A single retry makes the interaction less brittle when the server
            # heard audio but did not produce a usable transcript.
            print('I did not catch that. Please try again.')

    raise RuntimeError(
        'Realtime audio was captured twice, but no transcript was returned. '
        'Try speaking louder or closer to the microphone.'
    )
