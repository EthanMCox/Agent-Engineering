import './style.css'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import type { ChatApiResponse, ChatMessage, DashboardFeature } from './types'

type AppSection = 'dashboard' | 'chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const SESSION_STORAGE_KEY = 'canvas-study-coach-session-id'
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
})

const FEATURES: DashboardFeature[] = [
  {
    id: 'grades',
    title: 'Grade Summary',
    description: 'Review current grade signals, missing work, and class-level trends.',
    status: 'in-progress',
  },
  {
    id: 'plan',
    title: 'Study Plan',
    description: 'Generate a daily or weekly plan based on deadlines and available time.',
    status: 'in-progress',
  },
  {
    id: 'quiz',
    title: 'Quiz Generator',
    description: 'Create targeted practice questions from weak topics and past mistakes.',
    status: 'in-progress',
  },
  {
    id: 'context',
    title: 'Course Context / Sources',
    description: 'View citation-backed context from Canvas content and local study materials.',
    status: 'in-progress',
  },
]

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: crypto.randomUUID(),
    role: 'assistant',
    text: 'Welcome to Canvas Study Coach. Ask for study priorities, assignment planning, or quiz practice and I will respond with grounded, course-aware guidance when available.',
    timestamp: new Date().toLocaleTimeString(),
    state: 'complete',
  },
]

const appRoot = document.querySelector<HTMLDivElement>('#app')
if (!appRoot) {
  throw new Error('App root not found')
}
const app: HTMLDivElement = appRoot

let activeSection: AppSection = resolveSectionFromHash()
let messages: ChatMessage[] = [...INITIAL_MESSAGES]
let isSending = false
const sessionId = getOrCreateSessionId()

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
          <h1>Student Workspace</h1>
        </div>
        <span class="badge">Final Project Build</span>
      </header>

      <nav class="tabs" aria-label="Main sections">
        <a href="#dashboard" class="tab ${activeSection === 'dashboard' ? 'active' : ''}">Dashboard</a>
        <a href="#chat" class="tab ${activeSection === 'chat' ? 'active' : ''}">Chat</a>
      </nav>

      <section class="panel ${activeSection === 'dashboard' ? '' : 'hidden'}" id="dashboard-panel">
        <h2>Dashboard</h2>
        <p class="helper">These planning tools are being actively integrated with Canvas context and citation-backed reasoning.</p>
        <div class="feature-grid">
          ${FEATURES.map(
            (feature) => `
              <article class="feature-card">
                <h3>${feature.title}</h3>
                <p>${feature.description}</p>
                <button type="button" disabled>In Progress</button>
              </article>
            `,
          ).join('')}
        </div>
      </section>

      <section class="panel ${activeSection === 'chat' ? '' : 'hidden'}" id="chat-panel">
        <h2>Chat</h2>
        <p class="helper">Use chat for Canvas-informed support, including study planning and course-grounded explanations with citations when available.</p>
        <div class="chat-actions">
          <button type="button" id="reset-chat" class="secondary-btn" ${isSending ? 'disabled' : ''}>Reset Chat</button>
        </div>

        <div class="chat-log" id="chat-log">
          ${messages
            .map(
              (message) => `
                <article class="message ${message.role} ${message.state === 'pending' ? 'pending' : ''}">
                  <div class="meta">${message.role} • ${message.timestamp}</div>
                  <div class="message-body">${renderMessageBody(message)}</div>
                </article>
              `,
            )
            .join('')}
        </div>

        <form id="chat-form" class="chat-input" autocomplete="off">
          <input id="chat-text" name="chat-text" type="text" placeholder="Type a message..." ${isSending ? 'disabled' : ''} required />
          <button type="submit" ${isSending ? 'disabled' : ''}>${isSending ? 'Sending...' : 'Send'}</button>
        </form>
      </section>
    </main>
  `

  const chatForm = document.querySelector<HTMLFormElement>('#chat-form')
  chatForm?.addEventListener('submit', handleChatSubmit)

  const resetChatButton = document.querySelector<HTMLButtonElement>('#reset-chat')
  resetChatButton?.addEventListener('click', handleResetChat)

  const chatLog = document.querySelector<HTMLElement>('#chat-log')
  if (chatLog) {
    chatLog.scrollTop = chatLog.scrollHeight
  }
}

async function handleChatSubmit(event: SubmitEvent): Promise<void> {
  event.preventDefault()
  if (isSending) {
    return
  }

  const form = event.currentTarget as HTMLFormElement
  const input = form.querySelector<HTMLInputElement>('#chat-text')
  const raw = input?.value.trim() ?? ''
  if (!raw) {
    return
  }

  isSending = true
  const pendingId = crypto.randomUUID()
  const now = new Date().toLocaleTimeString()

  messages = [
    ...messages,
    createMessage('user', raw, now),
    createMessage('assistant', 'Thinking...', now, 'pending', pendingId),
  ]
  form.reset()
  render()

  try {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message: raw,
      }),
    })

    if (!response.ok) {
      const errorPayload = (await safeJson(response)) as { detail?: string } | null
      const detail = errorPayload?.detail ?? `Request failed with status ${response.status}.`
      throw new Error(detail)
    }

    const payload = (await response.json()) as ChatApiResponse
    const rendered = resolveRenderedMessage(payload)
    messages = messages.map((message) =>
      message.id === pendingId
        ? createMessage(
            'assistant',
            rendered.fallbackText,
            new Date().toLocaleTimeString(),
            'complete',
            pendingId,
            rendered.markdown,
          )
        : message,
    )
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'Unexpected chat error.'
    messages = messages.map((message) =>
      message.id === pendingId
        ? createMessage('error', `Could not send message: ${detail}`, new Date().toLocaleTimeString(), 'complete', pendingId)
        : message,
    )
  } finally {
    isSending = false
    render()
  }
}

async function handleResetChat(): Promise<void> {
  if (isSending) {
    return
  }

  isSending = true
  render()

  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/reset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    })

    if (!response.ok) {
      throw new Error('Reset endpoint failed.')
    }

    messages = [...INITIAL_MESSAGES]
  } catch {
    messages = [
      ...messages,
      createMessage(
        'error',
        'Unable to reach reset endpoint. Local chat remains visible.',
        new Date().toLocaleTimeString(),
      ),
    ]
  } finally {
    isSending = false
    render()
  }
}

function createMessage(
  role: ChatMessage['role'],
  text: string,
  timestamp: string,
  state: ChatMessage['state'] = 'complete',
  id: string = crypto.randomUUID(),
  markdown?: string,
): ChatMessage {
  return {
    id,
    role,
    text,
    timestamp,
    state,
    markdown,
  }
}

function getOrCreateSessionId(): string {
  const existing = localStorage.getItem(SESSION_STORAGE_KEY)
  if (existing) {
    return existing
  }

  const created = crypto.randomUUID()
  localStorage.setItem(SESSION_STORAGE_KEY, created)
  return created
}

async function safeJson(response: Response): Promise<unknown | null> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function renderMessageBody(message: ChatMessage): string {
  if (message.markdown) {
    return renderMarkdown(message.markdown)
  }

  if (!message.text.trim()) {
    return '<p></p>'
  }

  return `<p>${escapeHtml(message.text).replace(/\n/g, '<br />')}</p>`
}

function renderMarkdown(content: string): string {
  const html = markdown.render(content)
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'p',
      'br',
      'h1',
      'h2',
      'h3',
      'h4',
      'h5',
      'h6',
      'ul',
      'ol',
      'li',
      'blockquote',
      'pre',
      'code',
      'strong',
      'em',
      'a',
      'table',
      'thead',
      'tbody',
      'tr',
      'th',
      'td',
      'hr',
    ],
    ALLOWED_ATTR: ['href', 'title'],
    ALLOW_DATA_ATTR: false,
  })
}

function resolveRenderedMessage(payload: ChatApiResponse): { markdown?: string; fallbackText: string } {
  const isMarkdownContract = payload.content_type === 'text/markdown' && payload.format === 'markdown'
  if (isMarkdownContract && typeof payload.markdown === 'string' && payload.markdown.trim()) {
    return {
      markdown: payload.markdown,
      fallbackText: payload.markdown,
    }
  }

  return { fallbackText: 'Received unsupported response format from server.' }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
