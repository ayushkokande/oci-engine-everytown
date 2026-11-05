import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ApiError } from "../api";
import type { ChatMessage } from "../types";

const MAX_USER_TURNS = 10;

/**
 * Inline chat panel grounded in one assessment. Used by organizations to refine their
 * feedback and by CSF staff to ask about an individual assessment. The parent owns the
 * transcript so it can persist it and act on it (e.g. "Update my feedback").
 */
export function AssessmentChat({
  id, title, intro, placeholder, suggestions, assistantName, messages, onMessagesChange, send,
  notice, actions,
}: {
  id: string;
  title: string;
  intro: ReactNode;
  placeholder: string;
  suggestions: string[];
  assistantName: string;
  messages: ChatMessage[];
  onMessagesChange: (messages: ChatMessage[]) => void;
  send: (messages: ChatMessage[]) => Promise<string>;
  notice?: string;
  actions?: ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);

  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, sending]);

  const userTurns = messages.filter((m) => m.role === "user").length;
  const awaitingReply = messages[messages.length - 1]?.role === "user";
  const atLimit = userTurns >= MAX_USER_TURNS;

  const requestReply = async (history: ChatMessage[]) => {
    setSending(true);
    setError(null);
    try {
      const reply = await send(history);
      if (mounted.current) onMessagesChange([...history, { role: "assistant", content: reply }]);
    } catch (e: unknown) {
      if (mounted.current) setError(e instanceof ApiError ? e.message : "The assistant could not reply. Please try again.");
    } finally {
      if (mounted.current) setSending(false);
    }
  };

  const submit = (text: string) => {
    const content = text.trim();
    if (!content || sending || awaitingReply || atLimit) return;
    const next: ChatMessage[] = [...messages, { role: "user", content }];
    setDraft("");
    onMessagesChange(next);
    void requestReply(next);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(draft);
  };

  return (
    <section className={`card achat ${messages.length ? "has-messages" : ""}`} aria-labelledby={`${id}-title`}>
      <header className="achat-head">
        <h2 id={`${id}-title`} className="section-title">{title}</h2>
        {messages.length > 0 && !sending && (
          <button type="button" className="linklike small" onClick={() => { onMessagesChange([]); setError(null); }}>
            Clear chat
          </button>
        )}
      </header>
      <div className="muted small achat-intro">{intro}</div>

      {messages.length === 0 ? (
        <div className="achat-suggestions" role="group" aria-label="Suggested questions">
          {suggestions.map((s) => (
            <button key={s} type="button" className="chip-btn" onClick={() => submit(s)} disabled={sending}>{s}</button>
          ))}
        </div>
      ) : (
        <div ref={logRef} className="chat-messages achat-log" role="log" aria-live="polite" aria-busy={sending} tabIndex={0}>
          {messages.map((m, i) => (
            <div key={`${m.role}-${i}`} className={`chat-message ${m.role}`}>
              <strong>{m.role === "assistant" ? assistantName : "You"}</strong>
              <p>{m.content}</p>
            </div>
          ))}
          {sending && <div className="chat-status" role="status">Thinking about your assessment...</div>}
        </div>
      )}

      {error && <div className="chat-error achat-error" role="alert">{error}</div>}
      {!sending && awaitingReply && (
        <button type="button" className="btn ghost small" onClick={() => void requestReply(messages)}>
          Retry the unanswered message
        </button>
      )}
      {atLimit && !awaitingReply && <p className="muted small">This chat has reached its {MAX_USER_TURNS}-message limit. Clear it to start again.</p>}

      <form className="achat-compose" onSubmit={onSubmit}>
        <label htmlFor={`${id}-input`} className="sr-only">Message</label>
        <textarea
          id={`${id}-input`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(draft); }
          }}
          maxLength={1500}
          rows={2}
          placeholder={placeholder}
          disabled={sending || awaitingReply || atLimit}
        />
        <button type="submit" className="btn primary" disabled={!draft.trim() || sending || awaitingReply || atLimit}>
          Send
        </button>
      </form>
      {actions && <div className="achat-actions">{actions}</div>}
      {notice && <p className="muted achat-notice">{notice}</p>}
    </section>
  );
}
