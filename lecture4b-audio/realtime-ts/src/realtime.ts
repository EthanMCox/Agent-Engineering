import { RealtimeAgent, RealtimeSession } from '@openai/agents/realtime'

const DEFAULT_INSTRUCTIONS =
  'You are a helpful assistant. Keep your messages brief and concise.'

function promptForEphemeralKey(): string | null {
  return window.prompt(
    'Paste an ephemeral Realtime API key. Do not commit it to the codebase.',
  )
}

export async function startRealtimeDemo(statusEl: HTMLElement) {
  const apiKey = promptForEphemeralKey()
  if (!apiKey) {
    statusEl.textContent = 'No key provided.'
    return
  }

  const agent = new RealtimeAgent({
    name: 'Assistant',
    instructions: DEFAULT_INSTRUCTIONS,
  })

  const session = new RealtimeSession(agent, {
    model: 'gpt-realtime',
    config: {
      voice: 'cedar',
      turnDetection: {
        type: 'semantic_vad',
        eagerness: 'medium',
      },
    },
  })

  try {
    statusEl.textContent = 'Connecting...'
    await session.connect({ apiKey })
    statusEl.textContent = 'Connected. Start speaking.'
    console.log('Realtime session connected.')
  } catch (error) {
    statusEl.textContent = 'Connection failed. Check the console.'
    console.error(error)
  }
}
