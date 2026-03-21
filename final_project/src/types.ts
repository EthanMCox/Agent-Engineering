export type FeatureStatus = 'coming-soon'

export interface DashboardFeature {
  id: string
  title: string
  description: string
  status: FeatureStatus
}

export type ChatRole = 'assistant' | 'user'

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  timestamp: string
}
