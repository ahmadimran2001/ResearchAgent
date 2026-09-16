import type {
  ApiErrorShape,
  ChatMessage,
  Conversation,
  FeedbackRequest,
  ModelInfo,
  StreamEvent,
  StreamRequest,
} from "./contract";
import { CHAT_API, IPC_CONTRACT } from "./contract";

declare global {
  interface Window {
    __RESEARCH_AGENT_IPC__?: { baseUrl: string; token: string };
  }
}

const devBase = import.meta.env.VITE_SIDECAR_URL ?? "http://127.0.0.1:8000";
const ipc = () => window.__RESEARCH_AGENT_IPC__;

function headers(json = true): HeadersInit {
  const value: Record<string, string> = {};
  if (json) value["Content-Type"] = "application/json";
  const token = ipc()?.token || import.meta.env.VITE_SIDECAR_TOKEN;
  if (token) value.Authorization = `${IPC_CONTRACT.authorizationScheme} ${token}`;
  return value;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${ipc()?.baseUrl ?? devBase}${path}`, {
    ...init,
    headers: { ...headers(init?.body != null), ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as ApiErrorShape;
    throw new Error(payload.detail ?? payload.message ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  listConversations: (query = "") =>
    request<Conversation[]>(`${CHAT_API.conversations}?query=${encodeURIComponent(query)}`),
  createConversation: (model_id: string) =>
    request<Conversation>(CHAT_API.conversations, {
      method: "POST",
      body: JSON.stringify({ model_id }),
    }),
  renameConversation: (id: string, title: string) =>
    request<Conversation>(CHAT_API.conversation(id), {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    request<void>(CHAT_API.conversation(id), { method: "DELETE" }),
  getMessages: (id: string) =>
    request<ChatMessage[]>(CHAT_API.messages(id)),
  uploadAttachment: async (conversationId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`${ipc()?.baseUrl ?? devBase}${CHAT_API.attachments(conversationId)}`, {
      method: "POST",
      headers: headers(false),
      body,
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as ApiErrorShape;
      throw new Error(payload.detail ?? payload.message ?? `Upload failed (${response.status})`);
    }
    return response.json() as Promise<{ id: string; filename: string; kind: string; bytes: number; preview: string }>;
  },
  getModels: () => request<ModelInfo[]>(CHAT_API.models),
  sendFeedback: (feedback: FeedbackRequest) =>
    request<void>(CHAT_API.feedback, {
      method: "POST",
      body: JSON.stringify(feedback),
    }),
  cancel: (runId: string) =>
    request<void>(CHAT_API.cancel(runId), { method: "POST" }),
};

export async function streamChat(
  payload: StreamRequest,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
  onRunId?: (runId: string) => void,
): Promise<string | null> {
  const response = await fetch(`${ipc()?.baseUrl ?? devBase}${CHAT_API.stream}`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    const error = (await response.json().catch(() => ({}))) as ApiErrorShape;
    throw new Error(error.detail ?? error.message ?? `Stream failed (${response.status})`);
  }
  const runId = response.headers.get(IPC_CONTRACT.runIdHeader);
  if (runId) onRunId?.(runId);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line) as StreamEvent);
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as StreamEvent);
  return runId;
}
