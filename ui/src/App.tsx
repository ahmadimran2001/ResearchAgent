import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowDown, BookOpen, Check, ChevronDown, Copy, FileText, FlaskConical, Menu, MessageSquarePlus,
  PanelLeftClose, Pencil, Plus, Search, Send, Settings, Square, ThumbsDown, ThumbsUp,
  Trash2, X,
} from "lucide-react";
import { api, streamChat } from "./api";
import type {
  ChatMessage, Citation, Conversation, ModelId, ModelInfo, StreamEvent,
} from "./contract";

const fallbackModels: ModelInfo[] = [
  { id: "phi4-mini", name: "Phi-4 Mini", description: "Research baseline · Ollama", provider: "ollama", ready: false },
];

function MessageView({ message, onCitations, onFeedback, onRegenerate, onEdit }: {
  message: ChatMessage;
  onCitations: (citations: Citation[]) => void;
  onFeedback: (message: ChatMessage, rating: "up" | "down") => void;
  onRegenerate: (message: ChatMessage) => void;
  onEdit: (message: ChatMessage) => void;
}) {
  const assistant = message.role === "assistant";
  return (
    <article className={`message ${message.role}`}>
      <div className="avatar">{assistant ? "R" : "You"}</div>
      <div className="message-body">
        <div className="message-meta">
          <strong>{assistant ? (message.model_id || "Assistant") : "You"}</strong>
          {message.state === "streaming" && <span className="stream-label"><i /> Generating</span>}
          {message.state === "cancelled" && <span className="muted">Stopped</span>}
          {message.state === "error" && <span className="error-text">Failed</span>}
        </div>
        <div className="markdown">
          {message.state === "streaming" ? (
            <pre className="stream-plain">{message.content || " "}<span className="caret" /></pre>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
                code: ({ className, children, ...props }) => {
                  const block = /language-/.test(className ?? "");
                  return block ? (
                    <div className="code-wrap">
                      <div className="code-head"><span>{className?.replace("language-", "")}</span>
                        <button onClick={() => navigator.clipboard.writeText(String(children))}><Copy size={13} /> Copy</button>
                      </div>
                      <code className={className} {...props}>{children}</code>
                    </div>
                  ) : <code className={className} {...props}>{children}</code>;
                },
              }}
            >{message.content || " "}</ReactMarkdown>
          )}
        </div>
        {message.attachments && message.attachments.length > 0 && (
          <div className="file-chips">{message.attachments.map((file) => (
            <span key={file.id} className="file-chip">{file.filename}</span>
          ))}</div>
        )}
        <div className="message-actions">
          {message.citations.length > 0 && (
            <button className="citation-pill" onClick={() => onCitations(message.citations)}>
              <BookOpen size={14} /> {message.citations.length} source{message.citations.length === 1 ? "" : "s"}
            </button>
          )}
          <div className="spacer" />
          {assistant ? <>
            <button title="Good response" onClick={() => onFeedback(message, "up")}><ThumbsUp size={14} /></button>
            <button title="Needs improvement" onClick={() => onFeedback(message, "down")}><ThumbsDown size={14} /></button>
            <button title="Regenerate" onClick={() => onRegenerate(message)}>↻</button>
          </> : <button title="Edit" onClick={() => onEdit(message)}><Pencil size={14} /></button>}
          <button title="Copy" onClick={() => navigator.clipboard.writeText(message.content)}><Copy size={14} /></button>
        </div>
      </div>
    </article>
  );
}

function EmptyState({ setInput }: { setInput: (value: string) => void }) {
  const prompts = [
    ["Literature review", "Find recent work on retrieval-augmented generation evaluation"],
    ["Novelty analysis", "Assess novelty of my research idea against retrieved literature"],
    ["Evidence-led draft", "Draft a research outline with verified citations"],
    ["Data experiment", "Help design a bounded experiment for my CSV dataset"],
  ];
  return (
    <div className="empty-state">
      <div className="brand-mark">R</div>
      <h1>What are you researching?</h1>
      <p>Explore scholarly evidence, compare models, and turn findings into traceable work.</p>
      <div className="prompt-grid">
        {prompts.map(([title, body]) => <button key={title} onClick={() => setInput(body)}>
          {title === "Data experiment" ? <FlaskConical /> : title === "Evidence-led draft" ? <FileText /> : <BookOpen />}
          <span><strong>{title}</strong><small>{body}</small></span>
        </button>)}
      </div>
    </div>
  );
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [compareMessages, setCompareMessages] = useState<ChatMessage[]>([]);
  const [models, setModels] = useState<ModelInfo[]>(fallbackModels);
  const [model, setModel] = useState<ModelId>("phi4-mini");
  const [compare, setCompare] = useState(false);
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [sidebar, setSidebar] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [citations, setCitations] = useState<Citation[] | null>(null);
  const [settings, setSettings] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const [pendingFiles, setPendingFiles] = useState<{ id: string; filename: string; kind: string }[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const chatRef = useRef<HTMLElement | null>(null);
  const pinToBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const active = conversations.find((item) => item.id === activeId);
  const compareModel: ModelId =
    models.find((item) => item.id !== model && item.provider === "ollama" && item.ready)?.id
    ?? models.find((item) => item.id !== model)?.id
    ?? model;
  const modelInfo = useMemo(() => models.find((item) => item.id === model) ?? fallbackModels[0], [models, model]);

  const refresh = async (query = "") => {
    try {
      const items = await api.listConversations(query);
      setConversations(items);
      setConnectionError(null);
      if (!activeId && items[0]) setActiveId(items[0].id);
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "Sidecar unavailable");
    }
  };

  useEffect(() => {
    void refresh();
    const loadModels = () => api.getModels().then(setModels).catch(() => undefined);
    void loadModels();
    const timer = window.setInterval(() => void loadModels(), 8000);
    const onSidecarError = (event: Event) =>
      setConnectionError((event as CustomEvent<string>).detail || "Sidecar failed to start");
    window.addEventListener("sidecar-error", onSidecarError);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("sidecar-error", onSidecarError);
    };
  }, []);

  useEffect(() => {
    if (!activeId) { setMessages([]); setCompareMessages([]); return; }
    api.getMessages(activeId).then((items) => {
      setMessages(items.filter((item) => item.model_id !== compareModel || !active?.compare_model_id));
      setCompareMessages(active?.compare_model_id ? items.filter((item) => item.model_id === compareModel) : []);
    }).catch((error: Error) => setConnectionError(error.message));
  }, [activeId]);

  const syncJump = () => {
    const el = chatRef.current;
    if (!el) return;
    const pinned = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
    pinToBottom.current = pinned;
    setShowJump(!pinned);
  };

  const scrollToLatest = () => {
    const el = chatRef.current;
    pinToBottom.current = true;
    setShowJump(false);
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    if (pinToBottom.current) scrollToLatest();
  }, [messages, compareMessages]);

  useEffect(() => {
    pinToBottom.current = true;
    setShowJump(false);
  }, [activeId]);
  useEffect(() => {
    const timeout = window.setTimeout(() => void refresh(search), 250);
    return () => window.clearTimeout(timeout);
  }, [search]);

  const createChat = async () => {
    try {
      const item = await api.createConversation(model);
      setConversations((items) => [item, ...items]);
      setActiveId(item.id);
      setMessages([]);
    } catch (error) { setConnectionError((error as Error).message); }
  };

  const deltaQueue = useRef<Extract<StreamEvent, { type: "message.delta" }>[]>([]);
  const deltaRaf = useRef(0);

  const flushDeltas = () => {
    deltaRaf.current = 0;
    const queued = deltaQueue.current;
    deltaQueue.current = [];
    if (!queued.length) return;
    const byLane: Record<"primary" | "compare", Map<string, string>> = {
      primary: new Map(),
      compare: new Map(),
    };
    for (const event of queued) {
      const lane = event.lane === "compare" ? "compare" : "primary";
      byLane[lane].set(event.message_id, (byLane[lane].get(event.message_id) ?? "") + event.delta);
    }
    (["primary", "compare"] as const).forEach((lane) => {
      const chunks = byLane[lane];
      if (!chunks.size) return;
      const setter = lane === "compare" ? setCompareMessages : setMessages;
      setter((items) =>
        items.map((item) => {
          const extra = chunks.get(item.id);
          return extra ? { ...item, content: item.content + extra } : item;
        }),
      );
    });
  };

  const updateEvent = (event: StreamEvent) => {
    if (event.type === "error") throw new Error(event.message ?? "Generation failed");
    if (event.type === "message.delta") {
      deltaQueue.current.push(event);
      if (!deltaRaf.current) deltaRaf.current = requestAnimationFrame(flushDeltas);
      return;
    }
    if (deltaQueue.current.length) flushDeltas();
    const setter = event.lane === "compare" ? setCompareMessages : setMessages;
    setter((items) => {
      if (event.type === "message.started") return [...items, event.message];
      if (!("message_id" in event)) return items;
      return items.map((item) => {
        if (item.id !== event.message_id) return item;
        if (event.type === "citation") return { ...item, citations: [...item.citations, event.citation] };
        if (event.type === "message.completed") return { ...item, state: "complete" };
        if (event.type === "message.cancelled") return { ...item, state: "cancelled" };
        return item;
      });
    });
  };

  const attachFiles = async (list: FileList | null) => {
    if (!list?.length) return;
    let conversationId = activeId;
    try {
      if (!conversationId) {
        const item = await api.createConversation(model);
        setConversations((items) => [item, ...items]);
        setActiveId(item.id);
        conversationId = item.id;
      }
      for (const file of Array.from(list)) {
        const uploaded = await api.uploadAttachment(conversationId, file);
        setPendingFiles((items) => [...items, { id: uploaded.id, filename: uploaded.filename, kind: uploaded.kind }]);
      }
    } catch (error) {
      setConnectionError((error as Error).message);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const submit = async (content = input, regenerate_message_id?: string) => {
    if ((!content.trim() && pendingFiles.length === 0) || streaming || !modelInfo.ready) return;
    let conversationId = activeId;
    try {
      if (!conversationId) {
        const item = await api.createConversation(model);
        setConversations((items) => [item, ...items]);
        setActiveId(item.id);
        conversationId = item.id;
      }
      if (!regenerate_message_id) {
        setMessages((items) => [...items, {
          id: crypto.randomUUID(), conversation_id: conversationId!, role: "user",
          content: content.trim() || "Please read the attached files.",
          state: "complete", created_at: new Date().toISOString(), citations: [],
          attachments: pendingFiles.map((file) => ({ id: file.id, filename: file.filename, kind: file.kind })),
        }]);
      }
      const attachment_ids = pendingFiles.map((file) => file.id);
      setPendingFiles([]);
      setInput("");
      pinToBottom.current = true;
      setShowJump(false);
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      const id = await streamChat({
        conversation_id: conversationId, content: content.trim(), model_id: model,
        compare_model_id: compare ? compareModel : undefined, regenerate_message_id,
        attachment_ids,
      }, controller.signal, updateEvent, setRunId);
      setRunId(id);
      await refresh(search);
    } catch (error) {
      if ((error as Error).name !== "AbortError") setConnectionError((error as Error).message);
    } finally { setStreaming(false); setRunId(null); abortRef.current = null; }
  };

  const stop = async () => {
    abortRef.current?.abort();
    if (runId) await api.cancel(runId).catch(() => undefined);
    setStreaming(false);
  };

  const rename = async (item: Conversation) => {
    const title = window.prompt("Rename conversation", item.title)?.trim();
    if (!title) return;
    try {
      const updated = await api.renameConversation(item.id, title);
      setConversations((items) => items.map((value) => value.id === item.id ? updated : value));
    } catch (error) { setConnectionError((error as Error).message); }
  };

  const remove = async (item: Conversation) => {
    if (!window.confirm(`Delete “${item.title}”? This cannot be undone.`)) return;
    try {
      await api.deleteConversation(item.id);
      setConversations((items) => items.filter((value) => value.id !== item.id));
      if (activeId === item.id) setActiveId(null);
    } catch (error) { setConnectionError((error as Error).message); }
  };

  const feedback = async (message: ChatMessage, rating: "up" | "down") => {
    const correction = rating === "down" ? window.prompt("What would make this response better? (optional)") ?? undefined : undefined;
    try {
      await api.sendFeedback({ message_id: message.id, rating, correction, consent_training: active?.consent_training ?? false });
      setToast("Feedback saved locally");
      window.setTimeout(() => setToast(""), 2200);
    } catch (error) { setConnectionError((error as Error).message); }
  };

  const regenerate = (message: ChatMessage) => {
    const prompt = messages
      .slice(0, messages.findIndex((item) => item.id === message.id))
      .reverse()
      .find((item) => item.role === "user")?.content;
    if (prompt) void submit(prompt, message.id);
  };

  return (
    <div className="app-shell">
      <aside className={sidebar ? "sidebar" : "sidebar collapsed"}>
        <div className="sidebar-top">
          <div className="logo"><span>R</span><strong>Research Agent</strong></div>
          <button className="icon-button" onClick={() => setSidebar(false)} title="Close sidebar"><PanelLeftClose /></button>
        </div>
        <button className="new-chat" onClick={createChat}><MessageSquarePlus /> New research chat <kbd>Ctrl N</kbd></button>
        <label className="search"><Search /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search conversations" /></label>
        <div className="history">
          <small>RECENT</small>
          {conversations.map((item) => <div className={`history-item ${activeId === item.id ? "active" : ""}`} key={item.id}>
            <button className="history-main" onClick={() => setActiveId(item.id)}>
              <span>{item.title}</span><small>{item.last_message || "Empty conversation"}</small>
            </button>
            <div className="history-actions">
              <button onClick={() => rename(item)} title="Rename"><Pencil /></button>
              <button onClick={() => remove(item)} title="Delete"><Trash2 /></button>
            </div>
          </div>)}
          {!conversations.length && <div className="no-history">{connectionError ? "Connect the sidecar to load history." : "No conversations yet."}</div>}
        </div>
        <button className="settings-button" onClick={() => setSettings(true)}><Settings /><span><strong>Settings</strong><small>Local-first · private</small></span></button>
      </aside>

      <main>
        <header>
          {!sidebar && <button className="icon-button" onClick={() => setSidebar(true)}><Menu /></button>}
          <div className="title"><strong>{active?.title ?? "New research"}</strong><small>{compare ? "Sequential model comparison" : "Evidence-first assistant"}</small></div>
          <label className="compare-toggle"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /><span /> Compare</label>
          <div className="model-select">
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}{item.vision ? " · vision" : ""}{item.ready ? "" : " (unavailable)"}
                </option>
              ))}
            </select>
            <ChevronDown />
          </div>
        </header>

        {connectionError && <div className="connection-banner"><span><i /> Sidecar unavailable</span><p>{connectionError}</p><button onClick={() => void refresh(search)}>Retry</button><button onClick={() => setConnectionError(null)}><X /></button></div>}
        {!connectionError && !modelInfo.ready && (
          <div className="connection-banner setup-banner">
            <span><i /> Model not ready</span>
            <p>Phi-4 Mini is not available yet. Install Ollama and the model with <code>scripts\install-ollama-phi4.ps1</code>, then keep Ollama running.</p>
          </div>
        )}
        <section ref={chatRef} className={`chat ${compare ? "compare" : ""}`} onScroll={syncJump}>
          {compare && <div className="compare-head"><div>{modelInfo.name}<small>Primary</small></div><div>{models.find((m) => m.id === compareModel)?.name}<small>Runs second to conserve memory</small></div></div>}
          {!messages.length && !compare ? <EmptyState setInput={setInput} /> : compare ? (
            <div className="compare-grid">
              <div>{messages.map((item) => <MessageView key={item.id} message={item} onCitations={setCitations} onFeedback={feedback} onRegenerate={regenerate} onEdit={(m) => setInput(m.content)} />)}</div>
              <div>{compareMessages.map((item) => <MessageView key={item.id} message={item} onCitations={setCitations} onFeedback={feedback} onRegenerate={regenerate} onEdit={(m) => setInput(m.content)} />)}</div>
            </div>
          ) : <div className="message-list">{messages.map((item) => <MessageView key={item.id} message={item} onCitations={setCitations} onFeedback={feedback} onRegenerate={regenerate} onEdit={(m) => setInput(m.content)} />)}</div>}
        </section>
        {showJump && (
          <button className="jump-latest" onClick={scrollToLatest} type="button">
            <ArrowDown size={14} /> Latest
          </button>
        )}

        <footer className="composer-area">
          {pendingFiles.length > 0 && (
            <div className="file-chips pending">{pendingFiles.map((file) => (
              <span key={file.id} className="file-chip">
                {file.filename}
                <button type="button" onClick={() => setPendingFiles((items) => items.filter((item) => item.id !== file.id))} aria-label="Remove file">×</button>
              </span>
            ))}</div>
          )}
          <div className="composer">
            <input ref={fileRef} type="file" hidden multiple
              accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.txt,.md,.csv,.json,.html,.bib,.tex,.xml,.yml,.yaml"
              onChange={(e) => void attachFiles(e.target.files)} />
            <button className="attach" title="Attach PDF, image, or document" onClick={() => fileRef.current?.click()}><Plus /></button>
            <textarea rows={1} value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }}
              placeholder="Ask a research question…" />
            {streaming ? <button className="send stop" onClick={stop} title="Stop"><Square /></button>
              : <button className="send" disabled={!modelInfo.ready || (!input.trim() && pendingFiles.length === 0)} onClick={() => void submit()} title="Send"><Send /></button>}
          </div>
        </footer>
      </main>

      {citations && <div className="drawer-backdrop" onClick={() => setCitations(null)}><aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-title"><div><strong>Sources</strong><small>{citations.length} citations in this response</small></div><button onClick={() => setCitations(null)}><X /></button></div>
        {citations.map((citation, index) => <a className="source-card" href={citation.url} target="_blank" rel="noreferrer" key={citation.id}>
          <span>{index + 1}</span><div><strong>{citation.title}</strong><small>{[citation.authors?.join(", "), citation.year].filter(Boolean).join(" · ")}</small>
            {citation.excerpt && <p>{citation.excerpt}</p>}<em className={citation.verified ? "verified" : ""}>{citation.verified ? <><Check /> Verified source</> : "Unverified"}</em>
          </div>
        </a>)}
      </aside></div>}

      {settings && <div className="modal-backdrop" onClick={() => setSettings(false)}><div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><div><strong>Settings</strong><small>Installed Ollama models</small></div><button onClick={() => setSettings(false)}><X /></button></div>
        <section><h3>Model status</h3>{models.map((item) => <div className="model-row" key={item.id}><span className={item.ready ? "status-dot online" : "status-dot"} /><div><strong>{item.name}</strong><small>{item.description}</small></div><em>{item.ready ? "Ready" : "Unavailable"}</em></div>)}</section>
      </div></div>}
      {toast && <div className="toast"><Check /> {toast}</div>}
    </div>
  );
}
