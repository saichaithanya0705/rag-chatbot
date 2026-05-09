import { useEffect, useId, useRef } from "react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import styles from "./chat-view.module.css";

export function ChatComposer() {
  const { state, actions } = useWorkbench();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fieldId = useId();
  const hintId = `${fieldId}-hint`;
  const scopeLabel =
    state.collections.find((collection) => collection.id === state.activeCollectionId)?.label ?? "All PDFs";
  const value = state.draftMessage;
  const isMessagePending = state.isSendingMessage;
  const canSend = value.trim().length > 0 && !isMessagePending;

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }

    const textarea = textareaRef.current;
    const rafId = requestAnimationFrame(() => {
      textarea.style.height = "auto";
      const nextHeight = Math.min(textarea.scrollHeight, 140);
      textarea.style.height = `${nextHeight}px`;
    });

    return () => cancelAnimationFrame(rafId);
  }, [value]);

  async function submitMessage() {
    const trimmed = value.trim();
    if (!trimmed || isMessagePending) {
      return;
    }

    await actions.sendMessage(trimmed);
  }

  return (
    <form
      className={styles.inputArea}
      onSubmit={(event) => {
        event.preventDefault();
        void submitMessage();
      }}
    >
      <div className={styles.inputLabelRow}>
        <label className={styles.inputLabel} htmlFor={fieldId}>
          Ask the assistant
        </label>
        <span className={styles.inputScope}>Scope: {scopeLabel}</span>
      </div>
      <div className={styles.inputRow}>
        <textarea
          aria-describedby={hintId}
          className={styles.msgInput}
          id={fieldId}
          onChange={(event) => actions.setDraftMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submitMessage();
            }
          }}
          placeholder="Ask for a summary, compare two documents, or pull the strongest supporting evidence."
          ref={textareaRef}
          rows={1}
          value={value}
        />
        <button
          aria-label={isMessagePending ? "Sending message" : "Send message"}
          className={styles.sendBtn}
          disabled={!canSend}
          type="submit"
        >
          {isMessagePending ? (
            <div className={styles.loadingDots}>
              <span className={styles.dot} />
              <span className={styles.dot} />
              <span className={styles.dot} />
            </div>
          ) : (
            <svg fill="none" height="16" viewBox="0 0 16 16" width="16">
              <path d="M2 14L14 8L2 2V7L10 8L2 9V14Z" fill="currentColor" />
            </svg>
          )}
        </button>
      </div>
      <div className={styles.inputHint} id={hintId}>
        Enter sends your question. Shift + Enter adds a new line.
      </div>
    </form>
  );
}
