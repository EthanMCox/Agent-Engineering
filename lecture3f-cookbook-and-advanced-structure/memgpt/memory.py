import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tiktoken

logger = logging.getLogger(__name__)
SYSTEM_ALERT_PREFIX = 'System Alert:'
GREETING_SNIPPETS = (
    'how can i help you today',
    'what would you like to do today',
    'would you like to do today',
    'teaching-assistant demo',
)


def _message_text(value: Any) -> str:
    content = getattr(value, 'content', None)
    if content is None:
        return _coerce_to_text(value)
    texts = []
    for chunk in content:
        text = getattr(chunk, 'text', None)
        if text:
            texts.append(text)
    return '\n'.join(texts)


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _coerce_to_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        if value.get('role'):
            parts.append(f"role={value['role']}")
        if value.get('type'):
            parts.append(f"type={value['type']}")
        if 'content' in value:
            parts.append(_coerce_to_text(value['content']))
        if 'output' in value:
            parts.append(_coerce_to_text(value['output']))
        if 'arguments' in value:
            parts.append(_coerce_to_text(value['arguments']))
        return ' '.join(part for part in parts if part)
    if isinstance(value, list):
        return '\n'.join(_coerce_to_text(item) for item in value)

    item_type = getattr(value, 'type', None)
    role = getattr(value, 'role', None)
    content = getattr(value, 'content', None)
    if item_type == 'message' and content is not None:
        texts = []
        for chunk in content:
            text = getattr(chunk, 'text', None)
            if text:
                texts.append(text)
        prefix = f'{role}: ' if role else ''
        return prefix + '\n'.join(texts)
    if item_type == 'function_call':
        return f"function_call {getattr(value, 'name', '')}({getattr(value, 'arguments', '')})"

    output = getattr(value, 'output', None)
    if output is not None:
        return _coerce_to_text(output)

    if hasattr(value, 'model_dump'):
        return _coerce_to_text(value.model_dump())

    return str(value)


def _normalize_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        normalized = dict(item)
        normalized.setdefault('timestamp', _now())
        normalized['text'] = _coerce_to_text(item)
        return normalized
    if hasattr(item, 'model_dump'):
        data = item.model_dump()
        data.setdefault('timestamp', _now())
        data['text'] = _coerce_to_text(item)
        return data
    return {'type': 'unknown', 'timestamp': _now(), 'text': _coerce_to_text(item)}


def _queue_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)

    item_type = getattr(item, 'type', None)
    if item_type == 'message':
        return {
            'role': getattr(item, 'role', 'assistant'),
            'content': _message_text(item),
        }
    if item_type == 'function_call':
        return {
            'type': 'function_call',
            'call_id': getattr(item, 'call_id', ''),
            'name': getattr(item, 'name', ''),
            'arguments': getattr(item, 'arguments', ''),
        }
    if hasattr(item, 'model_dump'):
        return item.model_dump()
    return {'role': 'system', 'content': _coerce_to_text(item)}


def _json_load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _substring_score(text: str, query: str) -> tuple[int, int]:
    text_lower = text.lower()
    query_lower = query.lower().strip()
    if not query_lower:
        return 0, len(text_lower)

    score = 0
    for token in query_lower.split():
        if token in text_lower:
            score += 1

    position = text_lower.find(query_lower)
    if position == -1:
        position = len(text_lower)
    return score, -position


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_system_alert_text(text: str) -> bool:
    return text.strip().startswith(SYSTEM_ALERT_PREFIX)


def _is_greeting_text(text: str) -> bool:
    lowered = text.lower()
    return any(snippet in lowered for snippet in GREETING_SNIPPETS)


def _is_noise_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get('role') != 'system':
        return False
    return _is_system_alert_text(str(item.get('content', '')))


@dataclass
class MemoryConfig:
    enabled: bool = False
    session_id: str = 'default'
    storage_dir: str = '.memories'
    core_memory_max_tokens: int = 300
    summary_max_tokens: int = 250
    fifo_max_tokens: int = 1200
    warning_fraction: float = 0.7
    flush_fraction: float = 1.0
    archival_search_result_limit: int = 5
    recall_search_result_limit: int = 5
    initial_persona: str = ''
    initial_user: str = ''

    @classmethod
    def from_agent(cls, agent: dict[str, Any]) -> 'MemoryConfig':
        raw = dict(agent.get('memory') or {})
        enabled = bool(raw.get('enabled'))
        name = agent.get('name', 'agent')
        return cls(
            enabled=enabled,
            session_id=str(raw.get('session_id') or f'{name}-default'),
            storage_dir=str(raw.get('storage_dir') or '.memories'),
            core_memory_max_tokens=int(raw.get('core_memory_max_tokens', 300)),
            summary_max_tokens=int(raw.get('summary_max_tokens', 250)),
            fifo_max_tokens=int(raw.get('fifo_max_tokens', 1200)),
            warning_fraction=float(raw.get('warning_fraction', 0.7)),
            flush_fraction=float(raw.get('flush_fraction', 1.0)),
            archival_search_result_limit=int(raw.get('archival_search_result_limit', 5)),
            recall_search_result_limit=int(raw.get('recall_search_result_limit', 5)),
            initial_persona=str(raw.get('persona', '')),
            initial_user=str(raw.get('user', '')),
        )


@dataclass
class MemoryState:
    core_memory: dict[str, str] = field(default_factory=lambda: {'persona': '', 'user': ''})
    summary: str = ''
    fifo_queue: list[Any] = field(default_factory=list)
    recall_records: list[dict[str, Any]] = field(default_factory=list)
    archival_records: list[dict[str, Any]] = field(default_factory=list)
    memory_pressure_sent: bool = False


class MemoryManager:
    def __init__(self, agent: dict[str, Any], model: str):
        self.agent = agent
        self.model = model
        self.config = MemoryConfig.from_agent(agent)
        self._pending_tool_calls: dict[str, str] = {}
        try:
            self._encoding = tiktoken.encoding_for_model(model)
        except Exception:
            logger.warning('Falling back to approximate token counting for model %s', model)
            self._encoding = None
        self.base_dir = (
            Path(self.config.storage_dir)
            / agent.get('name', 'agent')
            / self.config.session_id
        )
        self.core_path = self.base_dir / 'core_memory.json'
        self.recall_path = self.base_dir / 'recall_memory.json'
        self.archival_path = self.base_dir / 'archival_memory.json'
        self.state_path = self.base_dir / 'memory_state.json'
        self.state = MemoryState()
        if self.config.enabled:
            self._load()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _load(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.state.core_memory = _json_load(
            self.core_path,
            {
                'persona': self.config.initial_persona,
                'user': self.config.initial_user,
            }
        )
        self.state.recall_records = _json_load(self.recall_path, [])
        self.state.archival_records = _json_load(self.archival_path, [])
        state_payload = _json_load(self.state_path, {})
        self.state.summary = self._sanitize_summary(state_payload.get('summary', ''))
        self.state.fifo_queue = self._sanitize_loaded_fifo(state_payload.get('fifo_queue', []))
        self.state.memory_pressure_sent = False

    def save(self) -> None:
        if not self.enabled:
            return
        _json_dump(self.core_path, self.state.core_memory)
        _json_dump(self.recall_path, self.state.recall_records)
        _json_dump(self.archival_path, self.state.archival_records)
        _json_dump(
            self.state_path,
            {
                'summary': self._sanitize_summary(self.state.summary),
                'fifo_queue': self._sanitize_fifo_for_persistence(self.state.fifo_queue),
                'memory_pressure_sent': self.state.memory_pressure_sent,
                'updated_at': _now(),
            }
        )

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._encoding is None:
            return max(1, len(text) // 4)
        return len(self._encoding.encode(text))

    def count_item_tokens(self, item: Any) -> int:
        return self.count_tokens(_coerce_to_text(item))

    def _trim_text(self, text: str, max_tokens: int) -> str:
        if self.count_tokens(text) <= max_tokens:
            return text
        if self._encoding is None:
            approx_chars = max_tokens * 4
            return text[-approx_chars:]
        tokens = self._encoding.encode(text)
        return self._encoding.decode(tokens[-max_tokens:])

    def get_core_memory_text(self) -> str:
        persona = self.state.core_memory.get('persona', '').strip()
        user = self.state.core_memory.get('user', '').strip()
        parts = ['Core memory:']
        parts.append(f'Persona:\n{persona or "(empty)"}')
        parts.append(f'User:\n{user or "(empty)"}')
        return '\n\n'.join(parts)

    def get_summary_text(self) -> str:
        if not self.state.summary:
            return ''
        return f"Conversation summary of evicted memory:\n{self.state.summary}"

    def _normalize_fifo_item(self, item: Any) -> list[dict[str, Any]]:
        queued = _queue_item(item)
        if queued.get('type') == 'function_call':
            call_id = str(queued.get('call_id', ''))
            name = str(queued.get('name', ''))
            if call_id:
                self._pending_tool_calls[call_id] = name
            if name == 'talk_to_user':
                message = str(_parse_json_object(queued.get('arguments')).get('message', '')).strip()
                if message:
                    return [{'role': 'assistant', 'content': message}]
                return []
            return [queued]

        if queued.get('type') == 'function_call_output':
            call_id = str(queued.get('call_id', ''))
            call_name = self._pending_tool_calls.pop(call_id, '')
            if call_name == 'talk_to_user':
                text = str(queued.get('output', '')).strip()
                if text:
                    return [{'role': 'user', 'content': text}]
                return []
            return [queued]

        if 'role' in queued and 'content' in queued:
            return [{
                'role': queued.get('role', 'system'),
                'content': str(queued.get('content', '')),
            }]

        text = _coerce_to_text(queued).strip()
        return [{'role': 'system', 'content': text}] if text else []

    def _sanitize_fifo_for_persistence(self, queue: list[Any]) -> list[dict[str, Any]]:
        call_ids_with_output = {
            str(item.get('call_id', ''))
            for item in queue
            if isinstance(item, dict) and item.get('type') == 'function_call_output'
        }
        sanitized = []
        for item in queue:
            normalized = _queue_item(item)
            if normalized.get('type') == 'function_call' and str(normalized.get('call_id', '')) not in call_ids_with_output:
                continue
            sanitized.append(normalized)
        return sanitized

    def _sanitize_loaded_fifo(self, queue: list[Any]) -> list[dict[str, Any]]:
        self._pending_tool_calls = {}
        call_ids_with_output = {
            str(item.get('call_id', ''))
            for item in queue
            if isinstance(item, dict) and item.get('type') == 'function_call_output'
        }
        sanitized: list[dict[str, Any]] = []
        for item in queue:
            normalized = _queue_item(item)
            if normalized.get('type') == 'function_call' and str(normalized.get('call_id', '')) not in call_ids_with_output:
                continue
            sanitized.extend(self._normalize_fifo_item(normalized))

        while sanitized and (_is_noise_item(sanitized[0]) or _is_greeting_text(str(sanitized[0].get('content', '')))):
            sanitized.pop(0)

        has_user_turn = any(item.get('role') == 'user' for item in sanitized)
        if not has_user_turn and all(
            _is_noise_item(item) or _is_greeting_text(str(item.get('content', '')))
            for item in sanitized
        ):
            return []
        return sanitized

    def _sanitize_summary(self, summary: str) -> str:
        lines = []
        for raw_line in summary.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _is_system_alert_text(line) or 'memory pressure detected' in line.lower() or 'fifo memory flushed' in line.lower():
                continue
            if _is_greeting_text(line):
                continue
            lines.append(line)
        return self._trim_text('\n'.join(lines), self.config.summary_max_tokens) if lines else ''

    def _protected_fifo_start(self) -> int | None:
        for index in range(len(self.state.fifo_queue) - 1, -1, -1):
            item = self.state.fifo_queue[index]
            if isinstance(item, dict) and item.get('role') == 'user':
                return index
        return None

    def append_fifo(self, item: Any) -> None:
        self.state.fifo_queue.extend(self._normalize_fifo_item(item))

    def add_recall_item(self, item: Any) -> None:
        if not self.enabled:
            return
        self.state.recall_records.append(_normalize_item(item))

    def build_input(self, prompt: str | None) -> list[Any]:
        assembled = []
        if prompt:
            assembled.append({'role': 'system', 'content': prompt})
        assembled.append({'role': 'system', 'content': self.get_core_memory_text()})
        if summary_text := self.get_summary_text():
            assembled.append({'role': 'system', 'content': summary_text})
        assembled.extend(self.state.fifo_queue)
        return assembled

    def prompt_token_count(self, prompt: str | None) -> int:
        return sum(self.count_item_tokens(item) for item in self.build_input(prompt))

    def total_budget(self) -> int:
        return (
            self.config.core_memory_max_tokens
            + self.config.summary_max_tokens
            + self.config.fifo_max_tokens
        )

    def maybe_add_memory_pressure_message(self, prompt: str | None) -> None:
        if self.state.memory_pressure_sent:
            return
        total = self.prompt_token_count(prompt)
        warning_tokens = int(self.total_budget() * self.config.warning_fraction)
        if total >= warning_tokens:
            self.state.memory_pressure_sent = True
            self.append_fifo({
                'role': 'system',
                'content': (
                    'System Alert: Memory pressure detected. '
                    'Use memory tools to save important facts to core memory or archival memory.'
                )
            })

    async def maybe_flush(self, client, prompt: str | None, usage: list | None) -> None:
        flush_tokens = int(self.total_budget() * self.config.flush_fraction)
        if self.prompt_token_count(prompt) <= flush_tokens:
            return

        target_tokens = max(1, int(self.total_budget() * 0.5))
        evicted = []
        protected_start = self._protected_fifo_start()
        while self.state.fifo_queue and self.prompt_token_count(prompt) > target_tokens:
            if protected_start is not None and protected_start <= 0:
                break
            evicted.append(self.state.fifo_queue.pop(0))
            if protected_start is not None:
                protected_start -= 1

        if not evicted:
            return

        evicted_text = '\n\n'.join(
            _coerce_to_text(item)
            for item in evicted
            if not _is_noise_item(item) and not _is_greeting_text(_coerce_to_text(item))
            if _coerce_to_text(item)
        )
        if evicted_text:
            self.state.summary = self._sanitize_summary(await self._summarize(client, evicted_text, usage))

        self.state.memory_pressure_sent = False
        self.append_fifo({
            'role': 'system',
            'content': 'System Alert: FIFO memory flushed and summary updated.'
        })

    async def _summarize(self, client, evicted_text: str, usage: list | None) -> str:
        if not evicted_text.strip():
            return self.state.summary

        existing = self.state.summary.strip()
        messages = [
            {
                'role': 'system',
                'content': (
                    'Summarize the evicted conversation history into a compact memory. '
                    'Preserve durable facts, user preferences, commitments, unresolved tasks, '
                    'and important recent context. Return plain text only.'
                )
            },
            {
                'role': 'user',
                'content': (
                    f'Existing summary:\n{existing or "(none)"}\n\n'
                    f'Newly evicted content:\n{evicted_text}'
                )
            }
        ]
        try:
            response = await client.responses.create(
                model=self.model,
                input=messages,
            )
            if usage is not None:
                usage.append((response.model, response.usage))
            texts = [
                chunk.text
                for item in response.output
                if item.type == 'message'
                for chunk in item.content
                if getattr(chunk, 'text', None)
            ]
            summary = '\n'.join(texts).strip()
            if summary:
                return self._sanitize_summary(summary)
        except Exception:
            logger.exception('Failed to summarize evicted memory; using fallback compression')

        fallback = '\n'.join(part for part in (existing, evicted_text) if part)
        return self._sanitize_summary(fallback)

    def append_core_memory(self, section: str, content: str) -> str:
        self._validate_core_section(section)
        existing = self.state.core_memory.get(section, '')
        new_value = (existing + '\n' + content).strip() if existing else content.strip()
        self.state.core_memory[section] = self._trim_text(new_value, self.config.core_memory_max_tokens)
        self.save()
        return f'Updated {section} core memory.'

    def replace_core_memory(self, section: str, content: str) -> str:
        self._validate_core_section(section)
        self.state.core_memory[section] = self._trim_text(content.strip(), self.config.core_memory_max_tokens)
        self.save()
        return f'Replaced {section} core memory.'

    def _validate_core_section(self, section: str) -> None:
        if section not in {'persona', 'user'}:
            raise ValueError("section must be 'persona' or 'user'")

    def insert_archival_memory(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        record = {
            'id': f'archive-{len(self.state.archival_records) + 1}',
            'timestamp': _now(),
            'content': content,
            'metadata': metadata or {},
        }
        self.state.archival_records.append(record)
        self.save()
        return record['id']

    def search_recall_memory(self, query: str, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self._search_records(
            self.state.recall_records,
            query,
            limit or self.config.recall_search_result_limit,
            offset,
            content_key='text',
        )

    def search_archival_memory(self, query: str, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self._search_records(
            self.state.archival_records,
            query,
            limit or self.config.archival_search_result_limit,
            offset,
            content_key='content',
        )

    def _search_records(
            self,
            records: list[dict[str, Any]],
            query: str,
            limit: int,
            offset: int,
            content_key: str,
    ) -> list[dict[str, Any]]:
        ranked = []
        for record in records:
            text = str(record.get(content_key, ''))
            score, position = _substring_score(text, query)
            if score > 0 or not query.strip():
                ranked.append((score, position, record))

        ranked.sort(
            key=lambda item: (item[0], item[1], item[2].get('timestamp', '')),
            reverse=True,
        )
        selected = [item[2] for item in ranked[offset:offset + max(limit, 0)]]
        return selected

    def format_search_results(self, label: str, query: str, results: list[dict[str, Any]], content_key: str) -> str:
        lines = [f'{label} search results for "{query}":']
        if not results:
            lines.append('(no matches)')
            return '\n'.join(lines)

        for idx, record in enumerate(results, start=1):
            timestamp = record.get('timestamp', 'unknown-time')
            content = str(record.get(content_key, '')).strip().replace('\n', ' ')
            lines.append(f'{idx}. [{timestamp}] {content[:240]}')
        return '\n'.join(lines)

    def status(self, prompt: str | None) -> str:
        core_tokens = self.count_tokens(self.get_core_memory_text())
        summary_tokens = self.count_tokens(self.get_summary_text())
        fifo_tokens = sum(self.count_item_tokens(item) for item in self.state.fifo_queue)
        total = self.prompt_token_count(prompt)
        return (
            f'session_id={self.config.session_id}\n'
            f'core_tokens={core_tokens}/{self.config.core_memory_max_tokens}\n'
            f'summary_tokens={summary_tokens}/{self.config.summary_max_tokens}\n'
            f'fifo_tokens={fifo_tokens}/{self.config.fifo_max_tokens}\n'
            f'prompt_tokens={total}\n'
            f'recall_records={len(self.state.recall_records)}\n'
            f'archival_records={len(self.state.archival_records)}'
        )
