export type FeatureStatus = 'coming-soon'

export interface DashboardFeature {
  id: string
  title: string
  description: string
  status: FeatureStatus
}

export type ChatRole = 'assistant' | 'user' | 'error'
export type MessageState = 'complete' | 'pending'

export interface ChatApiResponse {
  markdown?: string
  content_type?: string
  format?: string
  model: string
  usage?: Record<string, unknown>
  sources?: ChatSource[]
}

export interface ChatSource {
  source_type: string
  source_id: string
  label: string
  details: string
}

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  timestamp: string
  state?: MessageState
  markdown?: string
}
