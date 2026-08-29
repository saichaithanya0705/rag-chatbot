import { useEffect, useRef, useState, useCallback } from "react";
import * as pdfjs from "pdfjs-dist";
import pdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";

// Configure local Vite-bundled worker
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorker;

interface PdfCanvasViewerProps {
  fileUrl: string;
  pageNumber: number;
  scale?: number;
  userId?: string;
  onSwitchToText?: () => void;
  onPageCount?: (totalPages: number) => void;
}

export function PdfCanvasViewer({
  fileUrl,
  pageNumber,
  scale = 1.2,
  userId,
  onSwitchToText,
  onPageCount,
}: PdfCanvasViewerProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pdfDoc, setPdfDoc] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const currentRenderTaskRef = useRef<any>(null);
  const lastLoadedUrlRef = useRef<string | null>(null);

  const effectiveUserId =
    userId ||
    (typeof window !== "undefined" ? window.localStorage.getItem("local-rag-chat/user-id") : null) ||
    "default";

  // Build authenticated URL
  const authenticatedUrl = useCallback(() => {
    if (!fileUrl) return "";
    try {
      const parsed = new URL(fileUrl, window.location.origin);
      if (!parsed.searchParams.has("userId")) {
        parsed.searchParams.set("userId", effectiveUserId);
      }
      return parsed.toString();
    } catch {
      return fileUrl;
    }
  }, [fileUrl, effectiveUserId]);

  // Load document
  useEffect(() => {
    let active = true;
    const url = authenticatedUrl();
    if (!url) {
      setLoading(false);
      return;
    }

    if (lastLoadedUrlRef.current === url && pdfDoc) {
      return;
    }

    async function loadDocument() {
      setLoading(true);
      setError(null);

      try {
        const loadingTask = pdfjs.getDocument({
          url,
          httpHeaders: {
            "x-user-id": effectiveUserId,
          },
          withCredentials: false,
        });

        const doc = await loadingTask.promise;
        if (!active) return;

        setPdfDoc(doc);
        lastLoadedUrlRef.current = url;
        if (onPageCount) {
          onPageCount(doc.numPages);
        }
      } catch (err: any) {
        if (!active) return;
        console.error("PDF.js document load error:", err);
        setError(err.message || "Failed to load PDF document.");
        setLoading(false);
      }
    }

    void loadDocument();

    return () => {
      active = false;
    };
  }, [authenticatedUrl, effectiveUserId, onPageCount, pdfDoc]);

  // Render current page
  useEffect(() => {
    let active = true;
    if (!pdfDoc) {
      return;
    }

    async function renderPage() {
      setLoading(true);
      setError(null);

      try {
        const clampedPageNumber = Math.max(1, Math.min(pageNumber, pdfDoc.numPages));
        const page = await pdfDoc.getPage(clampedPageNumber);
        if (!active) return;

        const canvas = canvasRef.current;
        if (!canvas) return;

        const context = canvas.getContext("2d");
        if (!context) return;

        // Cancel previous rendering task if running
        if (currentRenderTaskRef.current) {
          try {
            currentRenderTaskRef.current.cancel();
          } catch {
            // Ignore cancellation error
          }
          currentRenderTaskRef.current = null;
        }

        const pixelRatio = window.devicePixelRatio || 1;
        const viewport = page.getViewport({ scale });

        // Set dimensions for high-DPI crisp rendering
        canvas.width = Math.floor(viewport.width * pixelRatio);
        canvas.height = Math.floor(viewport.height * pixelRatio);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        const renderContext = {
          canvasContext: context,
          viewport: viewport,
          transform: pixelRatio !== 1 ? [pixelRatio, 0, 0, pixelRatio, 0, 0] : undefined,
          canvas: canvas,
        };

        const renderTask = page.render(renderContext);
        currentRenderTaskRef.current = renderTask;

        await renderTask.promise;

        if (active) {
          setLoading(false);
        }
      } catch (err: any) {
        if (active && err?.name !== "RenderingCancelledException") {
          console.error("PDF.js render error:", err);
          setError(err.message || "Failed to render PDF page.");
          setLoading(false);
        }
      }
    }

    void renderPage();

    return () => {
      active = false;
      if (currentRenderTaskRef.current) {
        try {
          currentRenderTaskRef.current.cancel();
        } catch {
          // Ignore
        }
        currentRenderTaskRef.current = null;
      }
    };
  }, [pdfDoc, pageNumber, scale]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "flex-start",
        padding: "16px",
        minHeight: "200px",
        position: "relative",
        background: "var(--surface-soft)",
        overflow: "auto",
        width: "100%",
        height: "100%",
        boxSizing: "border-box",
      }}
    >
      {loading && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "rgba(253, 251, 247, 0.85)",
            backdropFilter: "blur(2px)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "12px",
            zIndex: 5,
            fontSize: "13px",
            color: "var(--text-muted)",
          }}
        >
          <div
            style={{
              width: "28px",
              height: "28px",
              border: "2.5px solid var(--border-soft)",
              borderTopColor: "var(--accent)",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
            }}
          />
          <span>Rendering page {pageNumber}...</span>
        </div>
      )}

      {error ? (
        <div
          style={{
            margin: "auto",
            padding: "24px",
            maxWidth: "360px",
            textAlign: "center",
            background: "var(--surface-base)",
            border: "1px solid var(--border-soft)",
            borderRadius: "12px",
            boxShadow: "var(--shadow-card)",
          }}
        >
          <div style={{ color: "var(--danger)", fontSize: "14px", fontWeight: 600, marginBottom: "8px" }}>
            Could not render page
          </div>
          <p style={{ fontSize: "12px", color: "var(--text-muted)", margin: "0 0 16px" }}>
            {error}
          </p>
          <div style={{ display: "flex", gap: "8px", justifyContent: "center", flexWrap: "wrap" }}>
            {onSwitchToText && (
              <button
                onClick={onSwitchToText}
                type="button"
                style={{
                  padding: "6px 12px",
                  fontSize: "12px",
                  borderRadius: "6px",
                  border: "1px solid var(--accent)",
                  background: "var(--surface-accent)",
                  color: "var(--accent-ink)",
                  cursor: "pointer",
                  fontWeight: 500,
                }}
              >
                View Extracted Text
              </button>
            )}
            <a
              href={authenticatedUrl()}
              target="_blank"
              rel="noreferrer"
              style={{
                padding: "6px 12px",
                fontSize: "12px",
                borderRadius: "6px",
                border: "1px solid var(--border-strong)",
                background: "var(--surface-base)",
                color: "var(--text-strong)",
                textDecoration: "none",
                fontWeight: 500,
              }}
            >
              Open PDF File
            </a>
          </div>
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          style={{
            maxWidth: "100%",
            height: "auto",
            boxShadow: "var(--shadow-floating)",
            borderRadius: "4px",
            backgroundColor: "#ffffff",
            display: loading ? "none" : "block",
            transition: "transform 0.15s ease",
          }}
        />
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
