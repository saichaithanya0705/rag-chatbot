import { useCallback, useEffect, useRef, useState } from "react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import { cn } from "@/shared/lib/cn";
import styles from "./pdf-viewer.module.css";

interface PdfViewerPanelProps {
  open: boolean;
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const PREVIEW_NOISE_LINE_PATTERN = /^\s*(?:page\s+\d+\b.*|.*copyright\b.*)$/gim;

function formatPreviewExcerpt(excerpt: string | undefined) {
  if (!excerpt) {
    return null;
  }

  const cleaned = excerpt
    .replace(PREVIEW_NOISE_LINE_PATTERN, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();

  return cleaned || null;
}

const PANEL_WIDTH_KEY = "local-rag-chat/pdf-panel-width";

export function PdfViewerPanel({ open }: PdfViewerPanelProps) {
  const { state, actions } = useWorkbench();
  const preview = state.pdfPreview;
  const previewRequest = state.pdfPreviewRequest;
  const [width, setWidth] = useState(() => {
    try {
      const stored = sessionStorage.getItem(PANEL_WIDTH_KEY);
      return stored ? clampWidth(Number(stored)) : 280;
    } catch {
      return 280;
    }
  });
  const dragging = useRef(false);
  const highlightRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const lastFocusedElementRef = useRef<HTMLElement | null>(null);
  const isModalDialog = state.isCompactViewport && open;

  function clampWidth(nextWidth: number) {
    return Math.min(500, Math.max(240, nextWidth));
  }

  function resizeWidth(delta: number) {
    setWidth((current) => clampWidth(current + delta));
  }

  // Persist width to sessionStorage so it survives chat↔pipeline navigation
  useEffect(() => {
    try {
      sessionStorage.setItem(PANEL_WIDTH_KEY, String(width));
    } catch {
      // Silently ignore storage errors (e.g. private browsing quota).
    }
  }, [width]);

  const onMouseDown = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      dragging.current = true;
      const startX = event.clientX;
      const startW = width;

      function onMove(moveEvent: MouseEvent) {
        const delta = startX - moveEvent.clientX;
        setWidth(clampWidth(startW + delta));
      }

      function onUp() {
        dragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [width],
  );

  function onResizerKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "ArrowLeft":
        event.preventDefault();
        resizeWidth(24);
        break;
      case "ArrowRight":
        event.preventDefault();
        resizeWidth(-24);
        break;
      case "Home":
        event.preventDefault();
        setWidth(240);
        break;
      case "End":
        event.preventDefault();
        setWidth(500);
        break;
      default:
        break;
    }
  }

  useEffect(() => {
    if (!isModalDialog) {
      return;
    }

    const dialog = panelRef.current;
    if (!dialog) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    lastFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";

    const focusableElements = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (element) => !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true",
    );
    focusableElements[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        actions.closePdfPreview();
        return;
      }

      if (event.key !== "Tab" || focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      lastFocusedElementRef.current?.focus();
    };
  }, [actions, isModalDialog]);

  const requestedPage = previewRequest?.page ?? preview?.page ?? 1;
  const visiblePage = preview?.page ?? requestedPage;
  const totalPages = preview?.totalPages ?? Math.max(requestedPage, 1);
  const canGoPrevious = requestedPage > 1;
  const canGoNext = requestedPage < totalPages;
  const formattedExcerpt = formatPreviewExcerpt(previewRequest?.excerpt);

  if (!open) {
    return null;
  }

  return (
    <div
      aria-labelledby="pdf-preview-title"
      aria-modal={isModalDialog ? "true" : undefined}
      className={cn(styles.pdfPanel, styles.pdfPanelOpen)}
      ref={panelRef}
      role={isModalDialog ? "dialog" : undefined}
      style={{ width, minWidth: width }}
    >
      <div
        aria-label="Resize PDF panel"
        aria-orientation="vertical"
        aria-valuemax={500}
        aria-valuemin={240}
        aria-valuenow={width}
        className={styles.resizer}
        onKeyDown={onResizerKeyDown}
        onMouseDown={onMouseDown}
        role="separator"
        tabIndex={0}
      />
      <div className={styles.pdfHeader}>
        <svg className={styles.pdfHeaderIcon} fill="none" height="14" viewBox="0 0 16 16" width="14">
          <rect height="14" rx="1.5" stroke="currentColor" strokeWidth="1.2" width="10" x="3" y="1" />
          <path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" strokeLinecap="round" strokeWidth="1" />
        </svg>
        <div className={styles.pdfHeaderText}>
          <span className={styles.pdfLabel}>Evidence preview</span>
          <span className={styles.pdfTitle} id="pdf-preview-title">
            {preview?.pdfName ?? previewRequest?.pdfName ?? "PDF preview"}
          </span>
        </div>
        <button
          aria-label="Close PDF preview"
          className={styles.closeBtn}
          onClick={actions.closePdfPreview}
          type="button"
        >
          <svg fill="none" height="14" viewBox="0 0 16 16" width="14">
            <path d="M4 4L12 12M12 4L4 12" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
          </svg>
        </button>
      </div>
      <div className={styles.pdfToolbar}>
        <div className={styles.pdfPageInfo}>
          Page {requestedPage} of {totalPages}
        </div>
        <div className={styles.pdfToolbarActions}>
          <button
            aria-label="Previous page"
            className={styles.toolbarButton}
            disabled={!canGoPrevious || state.isPdfPreviewLoading}
            onClick={() => void actions.goToPdfPreviewPage(requestedPage - 1)}
            type="button"
          >
            Prev
          </button>
          <button
            aria-label="Next page"
            className={styles.toolbarButton}
            disabled={!canGoNext || state.isPdfPreviewLoading}
            onClick={() => void actions.goToPdfPreviewPage(requestedPage + 1)}
            type="button"
          >
            Next
          </button>
          {preview?.fileUrl ? (
            <a className={styles.toolbarLink} href={preview.fileUrl} rel="noreferrer" target="_blank">
              Open PDF
            </a>
          ) : null}
        </div>
      </div>
      {formattedExcerpt ? <div className={styles.pdfExcerpt}>{formattedExcerpt}</div> : null}
      <div className={styles.pdfMock}>
        {state.isPdfPreviewLoading && !preview ? (
          <div className={styles.pdfState}>
            <div className={styles.pdfStateTitle}>Loading cited page</div>
            <div className={styles.pdfStateBody}>Pulling the referenced page so you can inspect the original wording.</div>
          </div>
        ) : state.pdfPreviewError ? (
          <div className={styles.pdfState}>
            <div className={styles.pdfStateTitle}>This preview could not be opened</div>
            <div className={styles.pdfStateBody}>{state.pdfPreviewError}</div>
            <button className={styles.retryButton} onClick={() => void actions.retryPdfPreview()} type="button">
              Retry preview
            </button>
          </div>
        ) : preview ? (
          <>
            {state.isPdfPreviewLoading ? (
              <div className={styles.loadingBanner}>
                {requestedPage === visiblePage
                  ? `Loading page ${requestedPage}...`
                  : `Loading page ${requestedPage}. Still showing page ${visiblePage} until it arrives.`}
              </div>
            ) : null}
            <div
              className={styles.pdfPage}
              dangerouslySetInnerHTML={{ __html: preview.htmlContent }}
              ref={(el) => {
                highlightRef.current = el;
                if (el) {
                  const hl = el.querySelector(".pdf-highlight");
                  if (hl) {
                    hl.scrollIntoView({ behavior: "smooth", block: "center" });
                  }
                }
              }}
            />
            <div className={styles.pdfPageNum}>Page {visiblePage}</div>
          </>
        ) : null}
      </div>
    </div>
  );
}
