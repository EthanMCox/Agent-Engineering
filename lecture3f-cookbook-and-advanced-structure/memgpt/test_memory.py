import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from memory import MemoryManager


class MemoryManagerTests(unittest.TestCase):
    def make_agent(self, storage_dir: str, **memory_overrides):
        memory = {
            'enabled': True,
            'storage_dir': storage_dir,
            'session_id': 'test-session',
            'core_memory_max_tokens': 32,
            'summary_max_tokens': 64,
            'fifo_max_tokens': 16,
            'warning_fraction': 0.7,
            'flush_fraction': 0.3,
            'persona': '',
            'user': '',
        }
        memory.update(memory_overrides)
        return {
            'name': 'main',
            'memory': memory,
        }

    def test_load_clears_stale_greeting_queue_and_summary_noise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / 'main' / 'test-session'
            base.mkdir(parents=True, exist_ok=True)
            (base / 'core_memory.json').write_text(json.dumps({'persona': '', 'user': ''}))
            (base / 'recall_memory.json').write_text('[]')
            (base / 'archival_memory.json').write_text('[]')
            (base / 'memory_state.json').write_text(json.dumps({
                'summary': '\n'.join([
                    'would you like to do today?"',
                    'System Alert: FIFO memory flushed and summary updated.',
                    'System Alert: Memory pressure detected.',
                    'Recent user action/request: "write a poem"',
                ]),
                'fifo_queue': [
                    {'role': 'system', 'content': 'System Alert: FIFO memory flushed and summary updated.'},
                    {
                        'type': 'function_call',
                        'call_id': 'call_1',
                        'name': 'talk_to_user',
                        'arguments': json.dumps({'message': 'Hi - I am your teaching-assistant demo. How can I help you today?'}),
                    },
                ],
            }))

            memory = MemoryManager(self.make_agent(tmpdir), 'not-a-real-model')

            self.assertEqual(memory.state.fifo_queue, [])
            self.assertEqual(memory.state.summary, 'Recent user action/request: "write a poem"')

    def test_talk_to_user_is_stored_as_assistant_and_user_turns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryManager(self.make_agent(tmpdir), 'not-a-real-model')

            memory.append_fifo({
                'type': 'function_call',
                'call_id': 'call_2',
                'name': 'talk_to_user',
                'arguments': json.dumps({'message': 'How can I help?'})
            })
            memory.append_fifo({
                'type': 'function_call_output',
                'call_id': 'call_2',
                'output': 'Tell me what you know about me.',
            })

            self.assertEqual(memory.state.fifo_queue, [
                {'role': 'assistant', 'content': 'How can I help?'},
                {'role': 'user', 'content': 'Tell me what you know about me.'},
            ])

    def test_flush_keeps_latest_user_request_and_filters_noise_from_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MemoryManager(self.make_agent(tmpdir), 'not-a-real-model')
            memory.state.fifo_queue = [
                {'role': 'assistant', 'content': 'Older context that can be evicted. ' * 6},
                {'role': 'system', 'content': 'System Alert: Memory pressure detected. Use memory tools.'},
                {'role': 'assistant', 'content': 'Hi - I am your teaching-assistant demo. How can I help you today?'},
                {'role': 'user', 'content': 'Write a poem about memory systems with a vivid ocean metaphor and a clean closing couplet.'},
            ]

            async def fake_summarize(client, evicted_text, usage):
                return evicted_text

            memory._summarize = fake_summarize  # type: ignore[method-assign]

            asyncio.run(memory.maybe_flush(client=None, prompt='p', usage=[]))

            self.assertTrue(any(
                item.get('role') == 'user' and 'Write a poem about memory systems' in item.get('content', '')
                for item in memory.state.fifo_queue
            ))
            self.assertIn('Older context that can be evicted.', memory.state.summary)
            self.assertNotIn('Memory pressure detected', memory.state.summary)
            self.assertNotIn('teaching-assistant demo', memory.state.summary.lower())


if __name__ == '__main__':
    unittest.main()
