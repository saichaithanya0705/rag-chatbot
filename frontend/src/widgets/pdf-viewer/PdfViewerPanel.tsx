import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

function parsePreviewHtml(htmlContent: string) {
  if (typeof DOMParser === "undefined") {
    return htmlContent;
  }

  const parser = new DOMParser();
  const parsed = parser.parseFromString(`<div>${htmlContent}</div>`, "text/html");
  const root = parsed.body.firstElementChild;
  if (!root) {
    return htmlContent;
  }

  let nextKey = 0;
  const renderNode = (node: ChildNode): React.ReactNode => {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent;
    }

    if (!(node instanceof HTMLElement)) {
      return null;
    }

    if (node.tagName === "BR") {
      const key = `br-${nextKey}`;
      nextKey += 1;
      return <br key={key} />;
    }

    if (node.tagName === "SPAN" && node.classList.length === 1 && node.classList.contains("pdf-highlight")) {
      const key = `hl-${nextKey}`;
      nextKey += 1;
      return (
        <span key={key} className="pdf-highlight">
          {Array.from(node.childNodes).map((child) => renderNode(child))}
        </span>
      );
    }

    return node.textContent ?? "";
  };

  return Array.from(root.childNodes).map((child) => renderNode(child));
}

const PANEL_WIDTH_KEY = "local-rag-chat/pdf-panel-width";

export function PdfViewerPanel({ open }: PdfViewerPanelProps) {
  const { state, actions } = useWorkbench();
  const preview = state.pdfPreview;
  const previewRequest = state.pdfPreviewRequest;
  const [width, setWidth] = useState(() => {
    try {
      const stored = sessionStorage.getItem(PANEL_WIDTH_KEY);
      return stored ? clampWidth(Number(stored)) : 420;
    } catch {
      return 420;
    }
  });
  const dragging = useRef(false);
  const highlightRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const lastFocusedElementRef = useRef<HTMLElement | null>(null);
  const isModalDialog = state.isCompactViewport && open;

  function clampWidth(nextWidth: number) {
    return Math.min(800, Math.max(320, nextWidth));
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
        setWidth(320);
        break;
      case "End":
        event.preventDefault();
        setWidth(800);
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

  const [activeTab, setActiveTab] = useState<"pdf" | "text">("pdf");

  const requestedPage = previewRequest?.page ?? preview?.page ?? 1;
  const visiblePage = preview?.page ?? requestedPage;
  const totalPages = preview?.totalPages ?? Math.max(requestedPage, 1);
  const canGoPrevious = requestedPage > 1;
  const canGoNext = requestedPage < totalPages;
  const formattedExcerpt = formatPreviewExcerpt(previewRequest?.excerpt);
  const previewContent = useMemo(
    () => (preview ? parsePreviewHtml(preview.htmlContent) : null),
    [preview?.htmlContent],
  );

  const userId = useMemo(() => {
    if (typeof window === "undefined") {
      return "default";
    }
    return window.localStorage.getItem("local-rag-chat/user-id") || "default";
  }, []);

  const iframeSrc = useMemo(() => {
    if (!preview?.fileUrl) {
      return "";
    }
    try {
      const url = new URL(preview.fileUrl);
      url.searchParams.set("userId", userId);
      return `${url.toString()}#page=${requestedPage}`;
    } catch {
      const baseUrl = import.meta.env.VITE_API_BASE_URL ?? window.location.origin;
      try {
        const url = new URL(preview.fileUrl, baseUrl);
        url.searchParams.set("userId", userId);
        return `${url.toString()}#page=${requestedPage}`;
      } catch {
        return `${preview.fileUrl}#page=${requestedPage}`;
      }
    }
  }, [preview?.fileUrl, requestedPage, userId]);

  useEffect(() => {
    if (activeTab === "text" && preview) {
      const timer = setTimeout(() => {
        const container = panelRef.current;
        if (container) {
          const hl = container.querySelector(".pdf-highlight");
          if (hl) {
            hl.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }
      }, 120);
      return () => clearTimeout(timer);
    }
  }, [activeTab, requestedPage, preview]);

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

      <div className={styles.tabsContainer}>
        <button
          className={cn(styles.tabButton, activeTab === "pdf" && styles.activeTab)}
          onClick={() => setActiveTab("pdf")}
          type="button"
        >
          📄 Original PDF
        </button>
        <button
          className={cn(styles.tabButton, activeTab === "text" && styles.activeTab)}
          onClick={() => setActiveTab("text")}
          type="button"
        >
          🔍 Extracted Text
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
          activeTab === "pdf" ? (
            <div className={styles.iframeContainer}>
              {state.isPdfPreviewLoading && (
                <div className={styles.loadingOverlay}>
                  <div className={styles.loadingSpinner} />
                  <span>Loading PDF layout...</span>
                </div>
              )}
              {iframeSrc ? (
                <iframe
                  key={iframeSrc}
                  src={iframeSrc}
                  className={styles.pdfIframe}
                  title="PDF Native Viewer"
                />
              ) : (
                <div className={styles.pdfState}>
                  <div className={styles.pdfStateTitle}>No PDF File Available</div>
                  <div className={styles.pdfStateBody}>We couldn't resolve the source file for this preview.</div>
                </div>
              )}
            </div>
          ) : (
            <div className={styles.textScrollContainer}>
              {state.isPdfPreviewLoading ? (
                <div className={styles.loadingBanner}>
                  {requestedPage === visiblePage
                    ? `Loading page ${requestedPage}...`
                    : `Loading page ${requestedPage}. Still showing page ${visiblePage} until it arrives.`}
                </div>
              ) : null}
              <div className={styles.pdfPage}>
                {previewContent}
              </div>
              <div className={styles.pdfPageNum}>Page {visiblePage}</div>
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}



