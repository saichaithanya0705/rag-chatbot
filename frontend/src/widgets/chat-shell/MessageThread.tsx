import { useEffect, useRef, useState } from "react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import type { Citation, Message } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { EvidenceDeck } from "@/shared/ui/evidence-deck/EvidenceDeck";
import { MessageMarkdown } from "@/shared/ui/message-markdown/MessageMarkdown";
import threadStyles from "./message-thread.module.css";
import chatStyles from "./chat-view.module.css";

const styles = { ...threadStyles, ...chatStyles };

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

function showModelThinkingPanel(message: Message, thinkingEnabled: boolean) {
  return thinkingEnabled && Boolean(message.thinkingRequested);
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

function CopyMessageButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      onClick={handleCopy}
      className={styles.copyMessageBtn}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        background: "none",
        border: "none",
        color: copied ? "var(--success)" : "var(--text-subtle-aa)",
        cursor: "pointer",
        fontSize: "11px",
        fontWeight: 500,
        padding: "4px 8px",
        borderRadius: "4px",
        transition: "all var(--transition-fast)",
      }}
      type="button"
      title="Copy response"
    >
      {copied ? (
        <>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ color: "var(--success)" }}
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
          <span style={{ color: "var(--success)" }}>Copied!</span>
        </>
      ) : (
        <>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
            <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
          </svg>
          <span>Copy response</span>
        </>
      )}
    </button>
  );
}

export function MessageThread() {
  const { state, actions } = useWorkbench();
  const threadRef = useRef<HTMLDivElement | null>(null);
  const [showScrollFab, setShowScrollFab] = useState(false);
  const [hoveredCitationId, setHoveredCitationId] = useState<string | null>(null);
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
            {message.role === "assistant" && (
              <div className={styles.botMessageHeader}>
                <div className={styles.botAvatarContainer}>
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className={styles.botAvatarIcon}
                  >
                    <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
                  </svg>
                </div>
                <span className={styles.botName}>RAG Assistant</span>
                <span className={styles.botModelBadge}>NVIDIA NIM</span>
                {message.citations.length > 0 && (
                  <span className={styles.botCitationTelemetry}>
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                    {message.citations.length} CITED
                  </span>
                )}
              </div>
            )}

            {message.role === "user" && (
              <div className={styles.userMessageHeader}>
                <span className={styles.userName}>You</span>
              </div>
            )}

            <div className={cn(styles.bubble, message.status === "thinking" && styles.thinkingBubble)}>
              {message.role === "assistant" ? (
                hasVisibleAssistantContent(message) ? (
                  <>
                    {/* Compact Search Process inside the bubble */}
                    {getDisplayTraceItems(message).length > 0 && (
                      <details className={styles.compactTraceDetails}>
                        <summary className={styles.compactTraceSummary}>
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <circle cx="12" cy="12" r="10"/>
                            <path d="M12 16v-4"/>
                            <path d="M12 8h.01"/>
                          </svg>
                          <span>Search Trace ({getDisplayTraceItems(message).length} steps)</span>
                        </summary>
                        <div className={styles.compactTraceBody}>
                          {getDisplayTraceItems(message).map((item) => (
                            <div className={styles.compactTraceItem} key={item}>
                              • {item}
                            </div>
                          ))}
                        </div>
                      </details>
                    )}

                    {/* Collapsible Model Thinking Process inside the bubble */}
                    {showModelThinkingPanel(message, state.thinkingEnabled) && (
                      <details className={styles.modelThinkingDetails} open={message.status === "thinking"}>
                        <summary className={styles.modelThinkingSummary}>
                          <div className={styles.modelThinkingHeader}>
                            <svg
                              width="11"
                              height="11"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              className={styles.bulbIcon}
                            >
                              <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .5 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" />
                              <path d="M9 18h6" />
                              <path d="M10 22h4" />
                            </svg>
                            <span>
                              {message.status === "thinking"
                                ? "Thinking..."
                                : "Thinking Process"}
                            </span>
                          </div>
                        </summary>
                        <div className={styles.modelThinkingContent}>
                          {getModelThinking(message) ? (
                            <MessageMarkdown content={getModelThinking(message) ?? ""} />
                          ) : (
                            <p style={{ margin: 0, opacity: 0.7 }}>
                              Preparing reasoning summary...
                            </p>
                          )}
                        </div>
                      </details>
                    )}

                    <MessageMarkdown
                      content={message.content}
                      citations={message.citations}
                      activeCitationId={hoveredCitationId}
                      onCitationHover={setHoveredCitationId}
                    />

                    {/* Integrated Evidence Deck inside the assistant bubble */}
                    {message.citations.length > 0 && (
                      <EvidenceDeck
                        citations={message.citations}
                        activeCitationId={hoveredCitationId}
                        onCitationHover={setHoveredCitationId}
                        onSelectPdfCitation={(citation) => void actions.openPdfPreview(citation)}
                      />
                    )}
                  </>
                ) : (
                  <div className={styles.loadingDots}>
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                  </div>
                )
              ) : (
                <div className={styles.userBubbleContent}>
                  {message.images && message.images.length > 0 && (
                    <div className={styles.messageImageGrid}>
                      {message.images.map((img, index) => (
                        <img
                          key={index}
                          src={img.url || `data:${img.mimeType};base64,${img.data}`}
                          alt="User upload"
                          className={styles.messageImage}
                        />
                      ))}
                    </div>
                  )}
                  {message.content && <div className={styles.userBubbleText}>{message.content}</div>}
                </div>
              )}
            </div>

            {message.role === "assistant" && hasVisibleAssistantContent(message) ? (
              <div className={styles.assistantActionsRow}>
                <CopyMessageButton text={message.content} />
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

