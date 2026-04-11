import argparse
import asyncio
import base64
import json
import logging
import os
import ssl
import subprocess
import tempfile
import wave
from contextlib import suppress

import certifi
import websockets

from speech import AUDIO_INPUT_DEVICE, FFMPEG_PATH

REALTIME_MODEL = 'gpt-realtime'
REALTIME_URL = f'wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}'
REALTIME_SAMPLE_RATE = 24000
REALTIME_CHUNK_BYTES = 4800
REALTIME_VOICE = 'marin'
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

DEFAULT_INSTRUCTIONS = (
    'You are a concise, helpful voice assistant that communicates in English. '
    'Answer the user naturally and keep spoken responses fairly short unless they ask for detail. '
    'Wait for the user to speak first. Do not proactively begin the conversation. '
    'After you respond, wait silently for the user.'
)

TURN_DETECTION_TYPE = 'semantic_vad'
TURN_DETECTION_EAGERNESS = 'medium'
TURN_INTERRUPT_RESPONSE = False

LOG_FORMAT = '%(filename)-10.10s %(levelname)-5.5s %(asctime)s %(message)s'
logger = logging.getLogger(__name__)

def _configure_logging(debug: bool) -> None:
    import sys
    local_level = logging.DEBUG if debug else logging.INFO
    use_dark_gray = (
            sys.stderr.isatty()
            and os.getenv('NO_COLOR') is None
            and os.getenv('TERM', '').lower() != 'dumb'
    )
    format_string = f'\x1b[90m{LOG_FORMAT}\x1b[0m' if use_dark_gray else LOG_FORMAT
    logging.basicConfig(
        level=logging.WARNING,
        format=format_string,
        datefmt='%H:%M:%S',
        force=True,
    )
    for logger_name in ('__main__', 'realtime_chat'):
        logging.getLogger(logger_name).setLevel(local_level)


def _realtime_headers() -> dict[str, str]:
    """Build the authorization headers required for the Realtime WebSocket."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not set.')
    return {'Authorization': f'Bearer {api_key}'}


def _start_microphone_stream() -> subprocess.Popen:
    """Start ffmpeg and stream raw 24kHz PCM microphone audio to stdout."""
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


async def _play_pcm_audio(audio_bytes: bytes) -> None:
    """Wrap PCM audio in a WAV container and play it locally with afplay."""
    if not audio_bytes:
        return

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
        wav_path = handle.name

    try:
        with wave.open(wav_path, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(REALTIME_SAMPLE_RATE)
            wav_file.writeframes(audio_bytes)

        await asyncio.to_thread(
            subprocess.run,
            ['/usr/bin/afplay', wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        with suppress(FileNotFoundError):
            os.unlink(wav_path)


async def _send_event(ws, event: dict) -> None:
    """Serialize and send one client event over the Realtime WebSocket."""
    await ws.send(json.dumps(event))


async def _configure_session(ws, instructions: str, voice: str) -> None:
    """Configure a speech-to-speech session with server VAD and audio output."""
    await _send_event(
        ws,
        {
            'type': 'session.update',
            'session': {
                'type': 'realtime',
                'model': REALTIME_MODEL,
                'instructions': instructions,
                'output_modalities': ['audio'],
                'audio': {
                    'input': {
                        'format': {
                            'type': 'audio/pcm',
                            'rate': REALTIME_SAMPLE_RATE,
                        },
                        'transcription': {
                            'model': 'gpt-4o-mini-transcribe',
                        },
                        'turn_detection': {
                            'type': TURN_DETECTION_TYPE,
                            'create_response': True,
                            'interrupt_response': TURN_INTERRUPT_RESPONSE,
                            'eagerness': TURN_DETECTION_EAGERNESS,
                        },
                        'noise_reduction': {
                            'type': 'near_field',
                        },
                    },
                    'output': {
                        'format': {
                            'type': 'audio/pcm',
                            'rate': REALTIME_SAMPLE_RATE,
                        },
                        'voice': voice,
                        'speed': 1.15,
                    },
                },
            },
        },
    )


async def _stream_microphone_audio(ws, stop_event: asyncio.Event) -> None:
    """Continuously read microphone PCM chunks and append them to the Realtime input buffer."""
    process = _start_microphone_stream()

    try:
        if process.stdout is None:
            raise RuntimeError('Failed to open microphone audio stream.')

        while not stop_event.is_set():
            chunk = await asyncio.to_thread(process.stdout.read, REALTIME_CHUNK_BYTES)
            if not chunk:
                break

            await _send_event(
                ws,
                {
                    'type': 'input_audio_buffer.append',
                    'audio': base64.b64encode(chunk).decode('ascii'),
                },
            )
    finally:
        with suppress(ProcessLookupError):
            process.terminate()
        with suppress(subprocess.TimeoutExpired):
            await asyncio.to_thread(process.wait, 5)
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()


async def run_realtime_chat(instructions: str, voice: str) -> None:
    """Run a continuous speech-to-speech chat session until interrupted."""
    print('Realtime voice chat started.')
    print("Speak naturally. Press Ctrl-C to exit.\nStart talking. I'm listening...\n")

    stop_event = asyncio.Event()

    async with websockets.connect(
        REALTIME_URL,
        extra_headers=_realtime_headers(),
        max_size=None,
        ssl=SSL_CONTEXT,
    ) as ws:
        await _configure_session(ws, instructions, voice)
#        await _request_initial_response(ws, voice)
        mic_task = asyncio.create_task(_stream_microphone_audio(ws, stop_event))

        user_transcript = ''
        assistant_transcript = ''
        assistant_audio = bytearray()

        try:
            async for raw_message in ws:
                event = json.loads(raw_message)
                event_type = event.get('type')

                if event_type == 'input_audio_buffer.speech_started':
                    user_transcript = ''
                    logger.debug('input_audio_buffer.speech_started')
                    print('\nYou: ', end='', flush=True)

                elif event_type == 'conversation.item.input_audio_transcription.delta':
                    delta = event.get('delta', '')
                    user_transcript += delta
                    logger.debug(f'conversation.item.input_audio_transcription.delta: {delta}')
                    print(delta, end='', flush=True)

                elif event_type == 'conversation.item.input_audio_transcription.completed':
                    transcript = event.get('transcript', user_transcript).strip()
                    logger.debug(f'conversation.item.input_audio_transcription.completed: {transcript}')
                    if transcript and transcript != user_transcript.strip():
                        print(f'\rYou: {transcript}')
                    else:
                        print()

                elif event_type == 'response.created':
                    logger.debug('response.created')
                    assistant_transcript = ''
                    assistant_audio.clear()
                    print('Assistant: ', end='', flush=True)

                elif event_type == 'response.output_audio_transcript.delta':
                    delta = event.get('delta', '')
                    assistant_transcript += delta
                    logger.debug(f'response.output_audio_transcript.delta: {delta}')
                    print(delta, end='', flush=True)

                elif event_type == 'response.output_audio.delta':
                    logger.debug('response.output_audio.delta')
                    assistant_audio.extend(base64.b64decode(event.get('delta', '')))

                elif event_type == 'response.output_audio.done':
                    logger.debug('response.output_audio.done')
                    print()
                    await _play_pcm_audio(bytes(assistant_audio))
                    assistant_audio.clear()

                elif event_type == 'error':
                    logger.debug('error')
                    error = event.get('error', {})
                    raise RuntimeError(error.get('message', 'Realtime session failed.'))
                else:
                    logger.debug(f'unhandled event: {event_type} -> {event}')
        finally:
            stop_event.set()
            mic_task.cancel()
            with suppress(asyncio.CancelledError):
                await mic_task


def main(instructions: str, voice: str) -> None:
    asyncio.run(run_realtime_chat(instructions, voice))


if __name__ == '__main__':
    parser = argparse.ArgumentParser('RealtimeChat')
    parser.add_argument('--instructions', default=DEFAULT_INSTRUCTIONS)
    parser.add_argument(
        '--voice',
        default=REALTIME_VOICE,
        choices=['alloy', 'ash', 'ballad', 'coral', 'echo', 'marin', 'sage', 'shimmer', 'verse'],
    )
    args = parser.parse_args()
    _configure_logging(False)
    main(args.instructions, args.voice)
