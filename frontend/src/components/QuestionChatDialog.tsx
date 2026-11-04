import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api";
import type { ChatMessage, Question } from "../types";

const INITIAL_MESSAGE = "Explain this statement in plain language and give me a neutral example.";
const MAX_USER_TURNS = 6;

export function QuestionChatDialog({
  question,
  domainName,
  messages,
  onMessagesChange,
  onClose,
}: {
  question: Question;
  domainName: string;
  messages: ChatMessage[];
  onMessagesChange: (messages: ChatMessage[]) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);
  const mounted = useRef(true);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestReply = async (history: ChatMessage[]) => {
    setSending(true);
    setError(null);
    try {
      const response = await api.questionChat(question.id, history);
      onMessagesChange([...history, { role: "assistant", content: response.reply }]);
    } catch (e: unknown) {
      if (mounted.current) {
        setError(e instanceof ApiError ? e.message : "The explanation could not be generated. Please try again.");
      }
    } finally {
      if (mounted.current) setSending(false);
    }
  };

  useEffect(() => {
    mounted.current = true;
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    window.requestAnimationFrame(() => inputRef.current?.focus());

    if (!started.current && messages.length === 0) {
      started.current = true;
      const initial: ChatMessage[] = [{ role: "user", content: INITIAL_MESSAGE }];
      onMessagesChange(initial);
      void requestReply(initial);
    }

    return () => {
      mounted.current = false;
    };
    // The component is keyed by question id; initialization must run once per opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question.id]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, sending]);

  const userTurns = messages.filter((message) => message.role === "user").length;
  const awaitingReply = messages[messages.length - 1]?.role === "user";
  const atTurnLimit = userTurns >= MAX_USER_TURNS && !awaitingReply;

  const send = (event: FormEvent) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sending || awaitingReply || userTurns >= MAX_USER_TURNS) return;
    const next: ChatMessage[] = [...messages, { role: "user", content }];
    setDraft("");
    onMessagesChange(next);
    void requestReply(next);
  };

  const startOver = () => {
    if (sending) return;
    const initial: ChatMessage[] = [{ role: "user", content: INITIAL_MESSAGE }];
    onMessagesChange(initial);
    void requestReply(initial);
  };

  const close = () => dialogRef.current?.close();

  return (
    <dialog
      ref={dialogRef}
      id="question-explanation-dialog"
      className="chat-dialog"
      aria-labelledby="question-chat-title"
      aria-describedby="question-chat-statement"
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="chat-shell">
        <header className="chat-header">
          <div>
            <p className="eyebrow">{domainName}</p>
            <h2 id="question-chat-title">Explain this statement</h2>
          </div>
          <button type="button" className="chat-close" onClick={close} aria-label="Close explanation chat">
            Close
          </button>
        </header>

        <p id="question-chat-statement" className="chat-statement">{question.text}</p>

        <div
          ref={logRef}
          className="chat-messages"
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-busy={sending}
          tabIndex={0}
        >
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`chat-message ${message.role}`}>
              <strong>{message.role === "assistant" ? "OCI guide" : "You"}</strong>
              <p>{message.content}</p>
            </div>
          ))}
          {sending && <div className="chat-status" role="status">Preparing a plain-language explanation...</div>}
        </div>

        {error && <div className="chat-error" role="alert">{error}</div>}
        {!sending && awaitingReply && (
          <button type="button" className="btn ghost small chat-retry" onClick={() => void requestReply(messages)}>
            Retry the unanswered message
          </button>
        )}
        {atTurnLimit && (
          <div className="chat-limit">
            <span>This chat has reached its six-turn limit.</span>
            <button type="button" className="linklike" onClick={startOver}>Start this chat over</button>
          </div>
        )}

        <form className="chat-composer" onSubmit={send}>
          <label htmlFor="question-chat-input">Ask a follow-up question</label>
          <div className="chat-compose-row">
            <textarea
              ref={inputRef}
              id="question-chat-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={1000}
              rows={2}
              placeholder="For example: What would this look like in day-to-day work?"
              disabled={sending || awaitingReply || userTurns >= MAX_USER_TURNS}
            />
            <button
              type="submit"
              className="btn primary"
              disabled={!draft.trim() || sending || awaitingReply || userTurns >= MAX_USER_TURNS}
            >
              Send
            </button>
          </div>
        </form>
        <p className="chat-notice">Do not include names or sensitive information. This chat explains the statement but does not choose an answer.</p>
      </div>
    </dialog>
  );
}
