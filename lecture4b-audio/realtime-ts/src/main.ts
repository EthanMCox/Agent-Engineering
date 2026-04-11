import './style.css'
import { startRealtimeDemo } from './realtime.ts'

document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <main class="page">
    <section class="card">
      <h1>Realtime Audio Demo</h1>
      <p>
        This browser demo uses the OpenAI Realtime API through the TypeScript
        agents library.
      </p>
      <p>
        When you load the page, enter an ephemeral realtime key and allow
        microphone access.
      </p>
      <p id="status" class="status">Waiting to connect...</p>
    </section>
  </main>
`

void startRealtimeDemo(
  document.querySelector<HTMLElement>('#status')!,
)
