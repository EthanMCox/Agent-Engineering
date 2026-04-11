import argparse
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path

from openai import OpenAI

from speech import AUDIO_INPUT_DEVICE, FFMPEG_PATH
from usage import print_usage

DEFAULT_MODEL = 'gpt-4o-mini-transcribe'
DEFAULT_PROMPT = (
    'Transcribe carefully. The speaker may use proper nouns, technical course terms, '
    'or uncommon names. Prefer plausible spellings over omissions.'
)

client = OpenAI()


def load_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    """Resolve the transcription prompt from a literal string or a file."""
    if prompt_file:
        return prompt_file.read_text().strip()
    if prompt:
        return prompt.strip()
    return ''


def record_audio_with_button_press() -> Path:
    """Record microphone audio until the user presses Enter a second time."""
    input('Press Enter to start recording. ')

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
        audio_path = Path(handle.name)

    process = subprocess.Popen(
        [
            FFMPEG_PATH,
            '-nostdin',
            '-hide_banner',
            '-loglevel',
            'error',
            '-y',
            '-f',
            'avfoundation',
            '-i',
            AUDIO_INPUT_DEVICE,
            '-ac',
            '1',
            '-ar',
            '16000',
            str(audio_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        input('Recording... press Enter to stop. ')
    finally:
        with suppress(ProcessLookupError):
            process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError('No audio was captured from the microphone.')

    return audio_path


def transcribe_speech(audio_path: Path, prompt: str, model: str, mode: str, usages: list[tuple[str, object]]) -> str:
    """Convert recorded speech into text, or into English text in translation mode."""
    with audio_path.open('rb') as audio_file:
        if mode == 'translate':
            model = 'whisper-1'  # no other model supported for translation
            response = client.audio.translations.create(
                file=audio_file,
                model=model,
                prompt=prompt or None,
            )
        else:
            response = client.audio.transcriptions.create(
                file=audio_file,
                model=model,
                prompt=prompt or None,
            )

    usage = getattr(response, 'usage', None)
    if usage is not None:
        usages.append((model, usage))

    if isinstance(response, str):
        return response.strip()

    return getattr(response, 'text', '').strip()


def main(prompt: str | None, prompt_file: Path | None, model: str, mode: str) -> None:
    prompt_text = load_prompt(prompt, prompt_file)
    usages: list[tuple[str, object]] = []
    action = 'translation' if mode == 'translate' else 'transcription'

    print('Speech To Text Demo')
    print(f'Record a short utterance and the program will print the {action}.')
    if prompt_text:
        print(f'\nUsing {action} prompt:')
        print(prompt_text)

    while True:
        audio_path = record_audio_with_button_press()
        try:
            transcript = transcribe_speech(audio_path, prompt_text, model, mode, usages)
        finally:
            with suppress(FileNotFoundError):
                audio_path.unlink()

        print(f'\n{action.title()}:')
        print(transcript or '[no transcript returned]')

        again = input('\nPress Enter to try again, or type q to quit: ').strip().lower()
        if again in {'q', 'quit'}:
            break

    if usages:
        print()
        print_usage(usages)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('SpeechToTextDemo')
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--prompt', default=DEFAULT_PROMPT)
    parser.add_argument('--prompt-file', type=Path, default=None)
    parser.add_argument(
        '--mode',
        choices=['transcribe', 'translate'],
        default='transcribe',
    )
    args = parser.parse_args()
    main(args.prompt, args.prompt_file, args.model, args.mode)
