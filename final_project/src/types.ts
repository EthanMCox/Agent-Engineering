export type FeatureStatus = 'coming-soon'

export interface DashboardFeature {
  id: string
  title: string
  description: string
  status: FeatureStatus
}

export type ChatRole = 'assistant' | 'user' | 'error'
export type MessageState = 'complete' | 'pending'

export type ContentBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'code'; language: string; code: string }
  | { type: 'markdown'; text: string }

export interface ChatApiResponse {
  reply: string
  content_blocks?: ContentBlock[]
  format?: 'markdown' | 'blocks'
  model: string
  usage?: Record<string, unknown>
}

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  timestamp: string
  state?: MessageState
  contentBlocks?: ContentBlock[]
}
