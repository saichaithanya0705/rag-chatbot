import { useEffect, useId, useRef } from "react";
import { Plus } from "lucide-react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import { cn } from "@/shared/lib/cn";
import { hasDraftSubmissionContent } from "@/app/providers/workbench/workbenchStateHelpers";
import styles from "./chat-view.module.css";

export function ChatComposer() {
  const { state, actions } = useWorkbench();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fieldId = useId();
  const hintId = `${fieldId}-hint`;
  const scopeLabel =
    state.collections.find((collection) => collection.id === state.activeCollectionId)?.label ?? "All PDFs";
  const value = state.draftMessage;
  const isMessagePending = state.isSendingMessage;
  const canSend = hasDraftSubmissionContent(value, state.draftImages.length) && !isMessagePending;

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
    if (!hasDraftSubmissionContent(value, state.draftImages.length) || isMessagePending) {
      return;
    }

    await actions.sendMessage(value);
  }

  function handleAttachClick() {
    fileInputRef.current?.click();
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files) return;

    Array.from(files).forEach((file) => {
      if (!file.type.startsWith("image/")) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        const result = e.target?.result;
        if (typeof result === "string") {
          const commaIndex = result.indexOf(",");
          const base64Data = result.slice(commaIndex + 1);
          actions.addDraftImage({
            data: base64Data,
            mimeType: file.type,
            url: result,
          });
        }
      };
      reader.readAsDataURL(file);
    });

    event.target.value = "";
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

      {state.draftImages && state.draftImages.length > 0 && (
        <div className={styles.draftImagesContainer}>
          {state.draftImages.map((img, idx) => (
            <div key={idx} className={styles.draftImageCard}>
              <img src={img.url} alt="Draft attachment" className={styles.draftImageThumbnail} />
              <button
                type="button"
                className={styles.removeDraftBtn}
                onClick={() => actions.removeDraftImage(idx)}
                aria-label="Remove image"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      )}

      <div className={styles.inputRow}>
        <button
          type="button"
          className={styles.attachBtn}
          onClick={handleAttachClick}
          title="Attach images"
          disabled={isMessagePending}
        >
          <Plus size={16} />
        </button>
        <input
          type="file"
          ref={fileInputRef}
          className={styles.hiddenInput}
          onChange={handleFileChange}
          accept="image/*"
          multiple
        />
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
          placeholder="Ask for a summary, explain an image, or pull the strongest supporting evidence."
          ref={textareaRef}
          rows={1}
          value={value}
          disabled={isMessagePending}
        />
        <button
          aria-label={isMessagePending ? "Stop generating" : "Send message"}
          className={cn(styles.sendBtn, isMessagePending && styles.stopBtn)}
          disabled={isMessagePending ? false : !canSend}
          onClick={isMessagePending ? actions.stopMessage : undefined}
          type={isMessagePending ? "button" : "submit"}
        >
          {isMessagePending ? (
            <svg fill="none" height="16" viewBox="0 0 16 16" width="16">
              <rect x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor" />
            </svg>
          ) : (
            <svg fill="none" height="16" viewBox="0 0 16 16" width="16">
              <path d="M2 14L14 8L2 2V7L10 8L2 9V14Z" fill="currentColor" />
            </svg>
          )}
        </button>
      </div>
      <div className={styles.inputHint} id={hintId}>
        {isMessagePending
          ? "Stop ends the current response and restores your draft."
          : "Enter sends your question. Shift + Enter adds a new line."}
      </div>
    </form>
  );
}
