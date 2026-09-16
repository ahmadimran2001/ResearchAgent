export type ModelId = string;
export type MessageRole = "user" | "assistant" | "system" | "tool";
export type MessageState = "complete" | "streaming" | "cancelled" | "error";

export interface Citation {
  id: string;
  title: string;
  url: string;
  authors?: string[];
  year?: number;
  excerpt?: string;
  verified: boolean;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  model_id?: ModelId;
  state: MessageState;
  created_at: string;
  citations: Citation[];
  attachments?: { id: string; filename: string; kind: string; media_type?: string }[];
  branch_id?: string;
}

export interface Conversation {
  id: string;
  title: string;
  model_id: ModelId;
  compare_model_id?: ModelId;
  consent_training: boolean;
  created_at: string;
  updated_at: string;
  last_message?: string;
}

export interface ModelInfo {
  id: ModelId;
  name: string;
  description: string;
  provider: "ollama" | "local";
  ready: boolean;
  vision?: boolean;
}

export interface StreamRequest {
  conversation_id: string;
  content: string;
  model_id: ModelId;
  compare_model_id?: ModelId;
  parent_message_id?: string;
  regenerate_message_id?: string;
  attachment_ids?: string[];
}

export type StreamEvent =
  | { type: "message.started"; message: ChatMessage; lane: "primary" | "compare" }
  | { type: "message.delta"; message_id: string; delta: string; lane: "primary" | "compare" }
  | { type: "citation"; message_id: string; citation: Citation; lane: "primary" | "compare" }
  | { type: "message.completed"; message_id: string; lane: "primary" | "compare" }
  | { type: "message.cancelled"; message_id: string; lane: "primary" | "compare" }
  | { type: "error"; message?: string; code?: string; lane?: "primary" | "compare" };

export interface FeedbackRequest {
  message_id: string;
  rating: "up" | "down";
  correction?: string;
  consent_training: boolean;
}

export interface ApiErrorShape {
  detail?: string;
  message?: string;
}

export const CHAT_API = {
  health: "/api/health",
  conversations: "/api/chat/conversations",
  conversation: (id: string) => `/api/chat/conversations/${id}`,
  messages: (id: string) => `/api/chat/conversations/${id}/messages`,
  attachments: (id: string) => `/api/chat/conversations/${id}/attachments`,
  consent: (id: string) => `/api/chat/conversations/${id}/consent`,
  stream: "/api/chat/stream",
  cancel: (runId: string) => `/api/chat/runs/${runId}/cancel`,
  models: "/api/chat/models",
  feedback: "/api/chat/feedback",
} as const;

export const IPC_CONTRACT = {
  bindHost: "127.0.0.1",
  tokenEnvironmentVariable: "RESEARCH_AGENT_IPC_TOKEN",
  authorizationScheme: "Bearer",
  streamMediaType: "application/x-ndjson",
  runIdHeader: "x-run-id",
} as const;
