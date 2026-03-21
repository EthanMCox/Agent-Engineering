import './style.css'
import type { ChatMessage, DashboardFeature } from './types'

type AppSection = 'dashboard' | 'chat'

const FEATURES: DashboardFeature[] = [
  {
    id: 'grades',
    title: 'Grade Summary',
    description: 'Review current grade signals, missing work, and class-level trends.',
    status: 'coming-soon',
  },
  {
    id: 'plan',
    title: 'Study Plan',
    description: 'Generate a daily or weekly plan based on deadlines and available time.',
    status: 'coming-soon',
  },
  {
    id: 'quiz',
    title: 'Quiz Generator',
    description: 'Create targeted practice questions from weak topics and past mistakes.',
    status: 'coming-soon',
  },
  {
    id: 'context',
    title: 'Course Context / Sources',
    description: 'View citation-backed context from Canvas content and local study materials.',
    status: 'coming-soon',
  },
]

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: crypto.randomUUID(),
    role: 'assistant',
    text: 'Template Mode: Chat is wired for local echo only. Canvas, MCP, and RAG integrations will be added later.',
    timestamp: new Date().toLocaleTimeString(),
  },
]

const appRoot = document.querySelector<HTMLDivElement>('#app')
if (!appRoot) {
  throw new Error('App root not found')
}
const app: HTMLDivElement = appRoot

let activeSection: AppSection = resolveSectionFromHash()
let messages: ChatMessage[] = [...INITIAL_MESSAGES]

window.addEventListener('hashchange', () => {
  activeSection = resolveSectionFromHash()
  render()
})

render()

function resolveSectionFromHash(): AppSection {
  return window.location.hash === '#chat' ? 'chat' : 'dashboard'
}

function render(): void {
  app.innerHTML = `
    <main class="app-shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">Canvas Study Coach</p>
          <h1>Frontend Starter</h1>
        </div>
        <span class="badge">Template Mode</span>
      </header>

      <nav class="tabs" aria-label="Main sections">
        <a href="#dashboard" class="tab ${activeSection === 'dashboard' ? 'active' : ''}">Dashboard</a>
        <a href="#chat" class="tab ${activeSection === 'chat' ? 'active' : ''}">Chat</a>
      </nav>

      <section class="panel ${activeSection === 'dashboard' ? '' : 'hidden'}" id="dashboard-panel">
        <h2>Dashboard</h2>
        <p class="helper">Feature placeholders are ready. Tool calls and backend logic are not yet connected.</p>
        <div class="feature-grid">
          ${FEATURES.map(
            (feature) => `
              <article class="feature-card">
                <h3>${feature.title}</h3>
                <p>${feature.description}</p>
                <button type="button" disabled>Coming Soon</button>
              </article>
            `,
          ).join('')}
        </div>
      </section>

      <section class="panel ${activeSection === 'chat' ? '' : 'hidden'}" id="chat-panel">
        <h2>Chat</h2>
        <p class="helper">This is a local frontend placeholder chat. No model or Canvas calls are running yet.</p>
        <div class="chat-log" id="chat-log">
          ${messages
            .map(
              (message) => `
                <article class="message ${message.role}">
                  <div class="meta">${message.role} • ${message.timestamp}</div>
                  <p>${escapeHtml(message.text)}</p>
                </article>
              `,
            )
            .join('')}
        </div>

        <form id="chat-form" class="chat-input" autocomplete="off">
          <input id="chat-text" name="chat-text" type="text" placeholder="Type a message..." required />
          <button type="submit">Send</button>
        </form>
      </section>
    </main>
  `

  const chatForm = document.querySelector<HTMLFormElement>('#chat-form')
  chatForm?.addEventListener('submit', handleChatSubmit)

  const chatLog = document.querySelector<HTMLElement>('#chat-log')
  if (chatLog) {
    chatLog.scrollTop = chatLog.scrollHeight
  }
}

function handleChatSubmit(event: SubmitEvent): void {
  event.preventDefault()
  const form = event.currentTarget as HTMLFormElement
  const input = form.querySelector<HTMLInputElement>('#chat-text')
  const raw = input?.value.trim() ?? ''
  if (!raw) {
    return
  }

  messages = [
    ...messages,
    {
      id: crypto.randomUUID(),
      role: 'user',
      text: raw,
      timestamp: new Date().toLocaleTimeString(),
    },
    {
      id: crypto.randomUUID(),
      role: 'assistant',
      text: `Echo (template): ${raw}`,
      timestamp: new Date().toLocaleTimeString(),
    },
  ]

  form.reset()
  render()
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
