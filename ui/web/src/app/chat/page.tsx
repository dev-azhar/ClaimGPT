"use client";

import { useEffect, useState, useRef, type FormEvent } from "react";

const CHAT_BASE = process.env.NEXT_PUBLIC_CHAT_BASE || "http://localhost:8000/chat";

function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, lang, code) =>
    `<pre class="code-block" data-lang="${lang}"><code>${code.trim()}</code></pre>`
  );
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h">$1</h5>');
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h">$1</h2>');
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/^---$/gm, '<hr class="md-hr"/>');
  html = html.replace(/^(\s*)[-•]\s+(.+)$/gm, (_m, indent, content) => {
    const depth = Math.floor((indent?.length || 0) / 2);
    return `<div class="md-li" style="padding-left:${depth * 1.2}rem">• ${content}</div>`;
  });
  html = html.replace(/^\s*(\d+)\.\s+(.+)$/gm, '<div class="md-li"><span class="md-num">$1.</span> $2</div>');
  html = html.replace(/^&gt;\s?(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');
  html = html.replace(/\n/g, "<br/>");
  html = html.replace(/<\/(pre|table|blockquote|div|h[2-5])><br\/>/g, "</$1>");
  html = html.replace(/<br\/><(pre|table|blockquote|h[2-5])/g, "<$1");
  return html;
}

interface Message {
  role: string;
  message: string;
  suggestions?: string[];
}

const STARTER_TOPICS = [
  { icon: "📋", label: "Claims Pipeline", question: "How does the claim processing pipeline work?" },
  { icon: "🏥", label: "ICD-10 & CPT", question: "Explain ICD-10 and CPT medical codes" },
  { icon: "💰", label: "Billing & Coverage", question: "How does insurance billing work in ClaimGPT?" },
  { icon: "📊", label: "Rejection Risk", question: "How is the rejection risk score calculated?" },
  { icon: "📤", label: "Upload Docs", question: "What file types can I upload?" },
  { icon: "📄", label: "TPA Submission", question: "How do I generate a TPA PDF?" },
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [claimId, setClaimId] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);
  const sessionId = useRef(`session-${Date.now()}`);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function doSend(text: string) {
    if (!text.trim()) return;
    const userMsg = text.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", message: userMsg }]);
    setSending(true);

    /* Try streaming first */
    try {
      const resp = await fetch(`${CHAT_BASE}/${sessionId.current}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, claim_id: claimId || undefined }),
      });

      if (resp.ok && resp.body) {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";
        let botIdx: number | null = null;
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.suggestions) {
                setMessages((prev) => {
                  const copy = [...prev];
                  if (copy.length > 0 && copy[copy.length - 1].role === "assistant") {
                    copy[copy.length - 1] = { ...copy[copy.length - 1], suggestions: payload.suggestions };
                  }
                  return copy;
                });
                continue;
              }
              const chunk = payload.content || "";
              if (!chunk) continue;
              accumulated += chunk;
              if (botIdx === null) {
                setMessages((prev) => {
                  botIdx = prev.length;
                  return [...prev, { role: "assistant", message: accumulated }];
                });
              } else {
                const snap = accumulated;
                setMessages((prev) => {
                  const copy = [...prev];
                  if (botIdx !== null && copy[botIdx]) copy[botIdx] = { ...copy[botIdx], message: snap };
                  return copy;
                });
              }
            } catch { /* skip malformed */ }
          }
        }
        if (!accumulated) throw new Error("empty");
        setSending(false);
        return;
      }
      throw new Error("no stream");
    } catch {
      /* Fallback to regular endpoint */
      try {
        const resp2 = await fetch(`${CHAT_BASE}/${sessionId.current}/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: userMsg, claim_id: claimId || undefined }),
        });
        if (resp2.ok) {
          const data = await resp2.json();
          setMessages((prev) => [
            ...prev.filter((m) => !(m.role === "assistant" && m.message === "")),
            { role: "assistant", message: data.message, suggestions: data.suggestions || [] },
          ]);
        } else {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", message: "Sorry, I encountered an error. Please try again." },
          ]);
        }
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", message: "Unable to connect to the chat service." },
        ]);
      }
    } finally {
      setSending(false);
    }
  }

  function handleSend(e: FormEvent) {
    e.preventDefault();
    doSend(input);
  }

  return (
    <div className="container">
      <a href="/" style={{ color: "var(--accent)", marginBottom: "1rem", display: "block" }}>← Home</a>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>Chat Assistant</h1>
      <p style={{ color: "var(--muted)", marginBottom: "1rem", fontSize: "0.875rem" }}>
        Ask questions about your claims, billing, coding, or submission status
      </p>

      <div style={{ marginBottom: "1rem" }}>
        <input
          type="text"
          placeholder="Claim ID (optional — for claim-specific questions)"
          value={claimId}
          onChange={(e) => setClaimId(e.target.value)}
          style={{ maxWidth: "400px" }}
        />
      </div>

      <div className="chat-container" style={{ minHeight: "70vh", display: "flex", flexDirection: "column" }}>
        <div className="chat-messages" style={{ flex: 1, overflow: "auto", padding: 0 }}>
          {messages.length === 0 && (
            <div className="chatgpt-welcome" style={{ padding: "3rem 2rem", display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div className="welcome-logo"><span className="logo-glow">CG</span></div>
              <h2 className="welcome-title">How can I help you today?</h2>
              <p className="welcome-sub">Pick a topic or type a question below</p>
              <div className="starter-grid-home">
                {STARTER_TOPICS.map((t) => (
                  <button key={t.label} className="starter-card-home" onClick={() => doSend(t.question)}>
                    <span className="sc-icon">{t.icon}</span>
                    <span className="sc-title">{t.label}</span>
                    <span className="sc-desc" style={{ fontSize: "11px", color: "var(--text-muted)" }}>{t.question}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg-row ${m.role === "user" ? "user" : "bot"}`}>
              <div className="msg-avatar">
                {m.role === "user" ? <span className="avatar-user">You</span> : <span className="avatar-bot">CG</span>}
              </div>
              <div className="msg-body">
                <div className={`msg-content ${m.role === "user" ? "user" : "bot"}`}>
                  <span dangerouslySetInnerHTML={{ __html: renderMarkdown(m.message) }} />
                </div>
                {m.role === "assistant" && (
                  <div className="msg-actions">
                    <button className="msg-action-btn" title="Copy" onClick={() => navigator.clipboard.writeText(m.message)}>📋</button>
                  </div>
                )}
                {m.role === "assistant" && m.suggestions && m.suggestions.length > 0 && i === messages.length - 1 && (
                  <div className="suggestion-row">
                    {m.suggestions.map((s) => (
                      <button key={s} className="suggestion-chip" onClick={() => doSend(s)}>{s}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="msg-row bot">
              <div className="msg-avatar"><span className="avatar-bot">CG</span></div>
              <div className="msg-body">
                <div className="msg-content bot typing-indicator">
                  <span className="dot"></span><span className="dot"></span><span className="dot"></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEnd} />
        </div>

        <div className="chat-input-bar">
          <form onSubmit={handleSend} className="input-wrapper">
            <input
              type="text"
              placeholder={sending ? "ClaimGPT is thinking..." : "Message ClaimGPT..."}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button type="submit" className="send-btn" disabled={sending || !input.trim()}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M1 8.5L1 1.5L15 8L1 14.5L1 8.5ZM1 8.5L8 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          </form>
          <p className="input-hint">ClaimGPT can make mistakes. Verify important medical codes.</p>
        </div>
      </div>
    </div>
  );
}
