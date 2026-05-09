import { useEffect, useRef, useState } from "react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import type { Citation, Message } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { CitationChip } from "@/shared/ui/citation-chip/CitationChip";
import { MessageMarkdown } from "@/shared/ui/message-markdown/MessageMarkdown";
import threadStyles from "./message-thread.module.css";
import chatStyles from "./chat-view.module.css";

const styles = { ...threadStyles, ...chatStyles };

function getWebCitationLabel(citation: Citation) {
  if (citation.title) {
    return citation.title;
  }

  if (!citation.url) {
    return "Web result";
  }

  try {
    return new URL(citation.url).hostname.replace(/^www\./, "");
  } catch {
    return citation.url;
  }
}

function getAnswerTraceItems(message: Message) {
  const items: string[] = [];

  if (message.toolCall) {
    items.push(
      message.status === "thinking"
        ? "Checking live sources to supplement the indexed PDFs."
        : "Supplemented the answer with current web evidence where the local library was not enough.",
    );
  }

  if (message.crossSessionMemoryUsed) {
    items.push(
      `Reused relevant context from ${message.crossSessionMemoryUsed} other session${
        message.crossSessionMemoryUsed === 1 ? "" : "s"
      } in this local workspace. Start a fresh chat if you want answers grounded only in the current thread.`,
    );
  }

  if (message.citations.length > 0) {
    items.push(
      `Grounded the answer in ${message.citations.length} cited source${
        message.citations.length === 1 ? "" : "s"
      }.`,
    );
  }

  return items;
}

function getDisplayTraceItems(message: Message) {
  if (message.answerTrace && message.answerTrace.length > 0) {
    return message.answerTrace.map((step) => step.detail);
  }

  return getAnswerTraceItems(message);
}

function getModelThinking(message: Message) {
  const content = message.modelThinking?.trim();
  return content && content.length > 0 ? content : null;
}

function showModelThinkingPanel(message: Message) {
  return Boolean(message.thinkingRequested);
}

function hasVisibleAssistantContent(message: Message) {
  const content = message.content.trim();
  return content.length > 0 && !(message.status === "thinking" && content === "Thinking...");
}

function EmptyStateIllustration() {
  return (
    <svg
      aria-hidden="true"
      className={styles.emptyIllustration}
      fill="none"
      viewBox="0 0 96 96"
      width="96"
    >
      <path
        d="M26 29.5C26 26.4624 28.4624 24 31.5 24H56.5L70 37.5V66.5C70 69.5376 67.5376 72 64.5 72H31.5C28.4624 72 26 69.5376 26 66.5V29.5Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <path d="M56 24V37.5H69.5" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.5" />
      <path d="M20 36H22.5V68.5C22.5 71.5376 24.9624 74 28 74H58" stroke="currentColor" strokeWidth="1.5" />
      <path d="M34 47H60" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
      <path d="M34 55H60" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
      <path d="M34 63H52" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
      <path
        d="M75 18.5L76.7735 23.2265L81.5 25L76.7735 26.7735L75 31.5L73.2265 26.7735L68.5 25L73.2265 23.2265L75 18.5Z"
        fill="var(--accent)"
      />
    </svg>
  );
}

export function MessageThread() {
  const { state, actions } = useWorkbench();
  const threadRef = useRef<HTMLDivElement | null>(null);
  const [showScrollFab, setShowScrollFab] = useState(false);
  const messages = state.messagesBySession[state.activeSessionId] ?? [];

  useEffect(() => {
    if (!threadRef.current) {
      return;
    }

    const { clientHeight, scrollHeight, scrollTop } = threadRef.current;
    if (scrollHeight - scrollTop - clientHeight < 50) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [messages]);

  function handleScroll() {
    if (!threadRef.current) {
      return;
    }

    const { clientHeight, scrollHeight, scrollTop } = threadRef.current;
    setShowScrollFab(scrollHeight - scrollTop - clientHeight > 200);
  }

  function scrollToBottom() {
    if (!threadRef.current) {
      return;
    }

    threadRef.current.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }

  if (messages.length === 0) {
    return (
      <div className={styles.messages}>
        <div className={styles.emptyState}>
          <EmptyStateIllustration />
          <div className={styles.emptyStateHeading}>Ask across your library</div>
          <div className={styles.emptyStateSubtext}>
            Ask for a brief, a comparison, or the strongest evidence across the PDFs already indexed here.
          </div>
          <div className={styles.suggestionPills}>
            {[
              "Brief the latest uploads",
              "Compare two documents",
              "Find the strongest supporting evidence",
            ].map((suggestion) => (
              <button
                className={styles.suggestionPill}
                key={suggestion}
                onClick={() => {
                  actions.setDraftMessage(suggestion);
                  void actions.sendMessage(suggestion);
                }}
                type="button"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.messagesWrapper}>
      <div aria-live="polite" className={styles.srOnly}>
        {state.isSendingMessage
          ? "Assistant is preparing a response."
          : messages.at(-1)?.role === "assistant"
            ? "Assistant response ready."
            : ""}
      </div>
      <div
        aria-busy={state.isSendingMessage}
        aria-live="off"
        className={styles.messages}
        onScroll={handleScroll}
        ref={threadRef}
        role="log"
      >
        {messages.map((message) => (
          <div
            className={cn(styles.msg, message.role === "user" ? styles.msgUser : styles.msgBot)}
            key={message.id}
          >
            {getDisplayTraceItems(message).length > 0 ? (
              <details className={styles.toolCall}>
                <summary className={styles.toolCallSummary}>
                  <span className={styles.toolCallLabel}>Answer trace</span>
                  <span>
                    {message.status === "thinking"
                      ? "View current retrieval steps"
                      : "View how this answer was grounded"}
                  </span>
                </summary>
                <div className={styles.toolCallBody}>
                  {getDisplayTraceItems(message).map((item) => (
                    <p className={styles.toolCallItem} key={item}>
                      {item}
                    </p>
                  ))}
                </div>
              </details>
            ) : null}

            {showModelThinkingPanel(message) ? (
              <details className={cn(styles.toolCall, styles.modelThinkingPanel)}>
                <summary className={styles.toolCallSummary}>
                  <span className={styles.toolCallLabel}>Model thinking</span>
                  <span>
                    {message.status === "thinking"
                      ? "Preparing reasoning summary"
                      : getModelThinking(message)
                        ? "View reasoning summary"
                        : "Reasoning summary unavailable"}
                  </span>
                </summary>
                <div className={cn(styles.toolCallBody, styles.modelThinkingBody)}>
                  {getModelThinking(message) ? (
                    <MessageMarkdown content={getModelThinking(message) ?? ""} />
                  ) : (
                    <p className={styles.toolCallItem}>
                      {message.status === "thinking"
                        ? "Preparing the reasoning summary for this response."
                        : "The backend could not prepare a reasoning summary for this response."}
                    </p>
                  )}
                </div>
              </details>
            ) : null}

            <div className={cn(styles.bubble, message.status === "thinking" && styles.thinkingBubble)}>
              {message.role === "assistant" ? (
                hasVisibleAssistantContent(message) ? (
                  <MessageMarkdown content={message.content} />
                ) : (
                  <div className={styles.loadingDots}>
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                  </div>
                )
              ) : (
                message.content
              )}
            </div>

            {message.citations.length > 0 ? (
              <div className={styles.citations}>
                {message.citations.map((citation) =>
                  citation.kind === "pdf" ? (
                    <CitationChip
                      key={citation.id}
                      label={`${citation.pdfName ?? "PDF"} · p.${citation.page ?? "?"}`}
                      onClick={() => void actions.openPdfPreview(citation)}
                      title={citation.excerpt ?? citation.pdfName ?? "Open PDF preview"}
                      variant="pdf"
                    />
                  ) : (
                    <CitationChip
                      href={citation.url}
                      key={citation.id}
                      label={getWebCitationLabel(citation)}
                      title={citation.url ?? citation.title ?? "Open web source"}
                      variant="web"
                    />
                  ),
                )}
              </div>
            ) : null}

            {message.webSearchUsed || message.crossSessionMemoryUsed ? (
              <div className={styles.assistantSignals}>
                {message.crossSessionMemoryUsed ? (
                  <span className={styles.memoryBadge}>
                    Used context from {message.crossSessionMemoryUsed} other session
                    {message.crossSessionMemoryUsed === 1 ? "" : "s"}
                  </span>
                ) : null}
                {message.webSearchUsed ? (
                  <span className={styles.webSearchUsed}>Included live web evidence</span>
                ) : null}
              </div>
            ) : null}

            {message.sessionWarning ? (
              <div className={styles.sessionWarning}>{message.sessionWarning}</div>
            ) : null}
          </div>
        ))}
      </div>
      {showScrollFab ? (
        <button
          aria-label="Scroll to bottom"
          className={styles.scrollFab}
          onClick={scrollToBottom}
          type="button"
        >
          <svg fill="none" height="16" viewBox="0 0 16 16" width="16">
            <path
              d="M8 3V13M8 13L4 9M8 13L12 9"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="1.5"
            />
          </svg>
        </button>
      ) : null}
    </div>
  );
}
