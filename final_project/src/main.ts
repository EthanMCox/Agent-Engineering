import './style.css'
import type { ChatApiResponse, ChatMessage, ContentBlock, DashboardFeature } from './types'

type AppSection = 'dashboard' | 'chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const SESSION_STORAGE_KEY = 'canvas-study-coach-session-id'

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
    text: 'Chat backend is active for basic context-aware responses. MCP, RAG, and multi-agent features are not connected yet.',
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
        <p class="helper">This chat uses a basic backend with per-session memory. Canvas/MCP/RAG features are still placeholders.</p>
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
    messages = messages.map((message) =>
      message.id === pendingId
        ? createMessage(
            'assistant',
            payload.reply,
            new Date().toLocaleTimeString(),
            'complete',
            pendingId,
            payload.content_blocks ?? undefined,
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
  contentBlocks?: ContentBlock[],
): ChatMessage {
  return {
    id,
    role,
    text,
    timestamp,
    state,
    contentBlocks,
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
  if (message.contentBlocks && message.contentBlocks.length > 0) {
    return message.contentBlocks.map(renderBlock).join('')
  }

  return `<p>${escapeHtml(message.text).replace(/\n/g, '<br />')}</p>`
}

function renderBlock(block: ContentBlock): string {
  if (block.type === 'markdown') {
    return renderMarkdown(block.text)
  }

  if (block.type === 'paragraph') {
    return `<p>${renderInlineMarkdown(block.text).replace(/\n/g, '<br />')}</p>`
  }

  if (block.type === 'list') {
    const items = block.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('')
    return `<ul>${items}</ul>`
  }

  return `<pre><code class="language-${escapeHtml(block.language)}">${escapeHtml(block.code)}</code></pre>`
}

function renderMarkdown(markdown: string): string {
  const normalized = markdown.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
  if (!normalized) {
    return '<p></p>'
  }

  const parts: string[] = []
  const codePattern = /```([A-Za-z0-9_-]+)?\n([\s\S]*?)```/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = codePattern.exec(normalized)) !== null) {
    const before = normalized.slice(lastIndex, match.index)
    parts.push(renderMarkdownTextBlocks(before))

    const language = escapeHtml((match[1] ?? 'text').trim() || 'text')
    const code = escapeHtml(match[2].replace(/\n$/, ''))
    parts.push(`<pre><code class="language-${language}">${code}</code></pre>`)
    lastIndex = match.index + match[0].length
  }

  parts.push(renderMarkdownTextBlocks(normalized.slice(lastIndex)))
  return parts.filter(Boolean).join('')
}

function renderMarkdownTextBlocks(segment: string): string {
  const chunks = segment
    .split(/\n\s*\n+/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)

  return chunks
    .map((chunk) => {
      const lines = chunk.split('\n').map((line) => line.trimEnd())
      if (!lines.length) {
        return ''
      }

      if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
        const items = lines
          .map((line) => line.replace(/^\s*[-*]\s+/, ''))
          .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
          .join('')
        return `<ul>${items}</ul>`
      }

      if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
        const items = lines
          .map((line) => line.replace(/^\s*\d+\.\s+/, ''))
          .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
          .join('')
        return `<ol>${items}</ol>`
      }

      const heading = lines[0].match(/^(#{1,6})\s+(.*)$/)
      if (heading) {
        const level = heading[1].length
        const text = renderInlineMarkdown(heading[2])
        return `<h${level}>${text}</h${level}>`
      }

      if (lines.every((line) => /^>\s?/.test(line))) {
        const text = lines.map((line) => line.replace(/^>\s?/, '')).join('\n')
        return `<blockquote>${renderInlineMarkdown(text).replace(/\n/g, '<br />')}</blockquote>`
      }

      return `<p>${renderInlineMarkdown(lines.join('\n')).replace(/\n/g, '<br />')}</p>`
    })
    .join('')
}

function renderInlineMarkdown(value: string): string {
  const escaped = escapeHtml(value)
  return escaped
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
