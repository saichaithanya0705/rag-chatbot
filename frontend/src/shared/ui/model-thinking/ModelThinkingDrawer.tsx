import { useState } from "react";
import type { Citation, Message } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { MessageMarkdown } from "@/shared/ui/message-markdown/MessageMarkdown";
import styles from "./model-thinking-drawer.module.css";

interface ModelThinkingDrawerProps {
  message: Message;
  onSelectPdfCitation?: (citation: Citation) => void;
}

export function ModelThinkingDrawer({ message }: ModelThinkingDrawerProps) {
  const isThinking = message.status === "thinking";
  const [isOpen, setIsOpen] = useState(isThinking);

  const rawThinking = message.modelThinking?.trim();
  const traceSteps = message.answerTrace || [];

  const hasContent = Boolean(rawThinking) || traceSteps.length > 0 || isThinking;
  if (!hasContent) {
    return null;
  }

  const label = isThinking ? "Thinking..." : "Thought process";

  return (
    <div className={styles.thinkingShell} aria-label="Model thought process">
      {/* Subtle, un-highlighted trigger button */}
      <button
        className={cn(
          styles.triggerBtn,
          isOpen && styles.triggerBtnOpen,
          isThinking && styles.triggerBtnThinking,
        )}
        onClick={() => setIsOpen(!isOpen)}
        type="button"
        aria-expanded={isOpen}
      >
        <span className={cn(styles.thinkingIcon, isThinking && styles.thinkingIconPulsing)}>
          {isThinking ? (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          ) : (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7Z" />
              <path d="M9 21h6" />
            </svg>
          )}
        </span>

        <span className={styles.triggerLabel}>{label}</span>

        <svg
          className={cn(styles.chevronArrow, isOpen && styles.chevronRotated)}
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Indented, quiet thought container */}
      {isOpen && (
        <div className={styles.thoughtContent} role="region" aria-label="Reasoning steps">
          {rawThinking ? (
            <div className={styles.thoughtMarkdown}>
              <MessageMarkdown content={rawThinking} />
            </div>
          ) : traceSteps.length > 0 ? (
            <div className={styles.thoughtSteps}>
              {traceSteps.map((step, idx) => (
                <div key={idx} className={styles.stepItem}>
                  <span className={styles.stepNum}>{idx + 1}.</span>
                  <span className={styles.stepText}>{step.detail}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.thoughtPlaceholder}>Formulating reasoning and grounding facts...</div>
          )}
        </div>
      )}
    </div>
  );
}
