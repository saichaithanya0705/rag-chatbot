import { useState, useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import type { Citation } from "@/shared/api/types";

interface MessageMarkdownProps {
  content: string;
  citations?: Citation[];
}

function CodeBlock({ children, className }: { children: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const language = className ? className.replace("language-", "") : "code";

  function handleCopy() {
    void navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div
      className="code-block-container"
      style={{
        margin: "12px 0",
        borderRadius: "8px",
        border: "1px solid var(--border-soft)",
        overflow: "hidden",
        backgroundColor: "var(--surface-soft)",
        boxShadow: "0 2px 8px rgba(0,0,0,0.03)",
      }}
    >
      <div
        className="code-block-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "6px 12px",
          backgroundColor: "var(--surface-muted)",
          borderBottom: "1px solid var(--border-soft)",
          fontSize: "11px",
          color: "var(--text-subtle-aa)",
          textTransform: "uppercase",
          fontWeight: 600,
          letterSpacing: "0.5px",
        }}
      >
        <span>{language}</span>
        <button
          onClick={handleCopy}
          style={{
            background: "none",
            border: "none",
            color: copied ? "#10B981" : "var(--text-subtle-aa)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "4px",
            fontSize: "11px",
            fontWeight: 500,
            padding: "2px 6px",
            borderRadius: "4px",
            transition: "all 0.15s ease",
            outline: "none",
          }}
          type="button"
          title="Copy code"
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
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              <span>Copied!</span>
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
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre
        style={{
          margin: 0,
          padding: "12px",
          overflowX: "auto",
          backgroundColor: "transparent",
          border: "none",
        }}
      >
        <code
          className={className}
          style={{
            padding: 0,
            background: "none",
            border: "none",
            borderRadius: 0,
            fontSize: "12px",
            fontFamily: "'Fira Code', 'Consolas', monospace",
            lineHeight: "1.55",
            display: "block",
            whiteSpace: "pre",
            color: "var(--text-strong)",
          }}
        >
          {children}
        </code>
      </pre>
    </div>
  );
}

function InlineCitationLink({ citation, num }: { citation: Citation; num: number }) {
  const { actions } = useWorkbench();
  const [hovered, setHovered] = useState(false);

  function handleClick(e: React.MouseEvent) {
    e.preventDefault();
    void actions.openPdfPreview(citation);
  }

  const tooltipText =
    citation.kind === "pdf"
      ? `${citation.pdfName} · Page ${citation.page}`
      : `${citation.title || "Web Link"} · ${citation.url}`;

  return (
    <span
      style={{
        position: "relative",
        display: "inline-block",
        userSelect: "none",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        onClick={handleClick}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--surface-accent)",
          border: "0.5px solid var(--accent-border)",
          color: "var(--accent-ink)",
          fontSize: "9px",
          fontWeight: 700,
          borderRadius: "4px",
          padding: "1px 4px",
          margin: "0 2px",
          cursor: "pointer",
          verticalAlign: "super",
          transition: "all var(--transition-fast)",
        }}
        type="button"
        title={tooltipText}
      >
        {num}
      </button>
      {hovered && (
        <span
          style={{
            position: "absolute",
            bottom: "100%",
            left: "50%",
            transform: "translateX(-50%) translateY(-6px)",
            backgroundColor: "var(--text-strong)",
            color: "var(--surface-soft)",
            padding: "5px 8px",
            borderRadius: "6px",
            fontSize: "10px",
            whiteSpace: "nowrap",
            zIndex: 9999,
            boxShadow: "var(--shadow-floating)",
            pointerEvents: "none",
            lineHeight: "1.2",
            animation: "fadeIn 150ms ease",
          }}
        >
          <span style={{ fontWeight: 600 }}>{citation.kind === "pdf" ? "📄 PDF" : "🌐 Web"}</span>{" "}
          {citation.kind === "pdf" ? citation.pdfName : (citation.title || "Web Link")}
          {citation.kind === "pdf" && ` (p. ${citation.page})`}
        </span>
      )}
    </span>
  );
}

function preprocessContent(content: string, citations?: Citation[]): string {
  if (!citations || citations.length === 0) {
    return content;
  }

  let processed = content;

  // Let's create lookup maps for fast matching
  const pdfIdMap = new Map<string, number>();
  const pdfPageMap = new Map<string, number>();
  const webUrlMap = new Map<string, number>();

  citations.forEach((citation, idx) => {
    if (citation.id) {
      pdfIdMap.set(citation.id.trim().toLowerCase(), idx);
    }
    if (citation.pdfName && citation.page !== undefined) {
      const key = `${citation.pdfName.trim().toLowerCase()}_p${citation.page}`;
      pdfPageMap.set(key, idx);
    }
    if (citation.url) {
      webUrlMap.set(citation.url.trim().toLowerCase(), idx);
    }
  });

  // 1. Replace [SourceID: <id>]
  processed = processed.replace(/\[SourceID:\s*([^\]]+)\]/gi, (match, idStr) => {
    const cleanId = idStr.trim().toLowerCase();
    const idx = pdfIdMap.get(cleanId);
    if (idx !== undefined) {
      return `[${idx + 1}](citation://${idx})`;
    }
    return match;
  });

  // 2. Replace [Source: <pdf>, p.<page>] or chunk c.<chunk>
  processed = processed.replace(/\[Source:\s*([^,\]]+),\s*p\.(\d+)(?:,\s*c\.\d+)?\]/gi, (match, pdfStr, pageStr) => {
    const cleanPdf = pdfStr.trim().toLowerCase();
    const pageNum = parseInt(pageStr, 10);
    const key = `${cleanPdf}_p${pageNum}`;
    const idx = pdfPageMap.get(key);
    if (idx !== undefined) {
      return `[${idx + 1}](citation://${idx})`;
    }
    return match;
  });

  // 3. Replace [Web: <url>]
  processed = processed.replace(/\[Web:\s*([^\]]+)\]/gi, (match, urlStr) => {
    const cleanUrl = urlStr.trim().toLowerCase();
    const idx = webUrlMap.get(cleanUrl);
    if (idx !== undefined) {
      return `[${idx + 1}](citation://${idx})`;
    }
    return match;
  });

  return processed;
}

export function MessageMarkdown({ content, citations }: MessageMarkdownProps) {
  // Pre-process text to convert raw RAG markers to interactive markdown links
  const processedText = useMemo(() => preprocessContent(content, citations), [content, citations]);

  // Construct components map dynamically to capture citations scope
  const dynamicComponents = useMemo(() => {
    const comps: Components = {
      a({ children, href, ...props }) {
        if (href && href.startsWith("citation://")) {
          const idx = parseInt(href.replace("citation://", ""), 10);
          const citation = citations?.[idx];
          if (citation) {
            return <InlineCitationLink citation={citation} num={idx + 1} />;
          }
        }
        return (
          <a href={href} rel="noreferrer noopener" target="_blank" {...props}>
            {children}
          </a>
        );
      },
      code({ className, children, ...props }) {
        const match = /language-(\w+)/.exec(className || "");
        const codeText = String(children).replace(/\n$/, "");
        const isInline = !match && !codeText.includes("\n");

        if (isInline) {
          return (
            <code
              className={className}
              {...props}
              style={{
                fontFamily: "'Fira Code', 'Consolas', monospace",
                fontSize: "11.5px",
                background: "var(--surface-muted)",
                border: "0.5px solid var(--border-soft)",
                borderRadius: "4px",
                padding: "2px 5px",
                color: "var(--accent-ink)",
              }}
            >
              {children}
            </code>
          );
        }

        return <CodeBlock className={className}>{codeText}</CodeBlock>;
      },
      table({ children }) {
        return (
          <div
            className="table-responsive-container"
            style={{
              width: "100%",
              overflowX: "auto",
              margin: "16px 0",
              borderRadius: "8px",
              border: "1px solid var(--border-soft)",
              boxShadow: "0 2px 8px rgba(0,0,0,0.02)",
            }}
          >
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "12px",
                color: "var(--text-strong)",
                textAlign: "left",
              }}
            >
              {children}
            </table>
          </div>
        );
      },
      thead({ children }) {
        return (
          <thead
            style={{
              backgroundColor: "var(--surface-muted)",
              borderBottom: "1px solid var(--border-soft)",
            }}
          >
            {children}
          </thead>
        );
      },
      th({ children }) {
        return (
          <th
            style={{
              padding: "8px 12px",
              fontWeight: 600,
              color: "var(--text-strong)",
            }}
          >
            {children}
          </th>
        );
      },
      td({ children }) {
        return (
          <td
            style={{
              padding: "8px 12px",
              borderTop: "1px solid var(--border-soft)",
            }}
          >
            {children}
          </td>
        );
      },
      blockquote({ children }) {
        return (
          <blockquote
            style={{
              margin: "16px 0",
              padding: "8px 16px",
              borderLeft: "4px solid var(--accent)",
              background: "rgba(127, 119, 221, 0.04)",
              color: "var(--text-muted)",
              fontStyle: "italic",
              borderRadius: "0 6px 6px 0",
            }}
          >
            {children}
          </blockquote>
        );
      },
    };
    return comps;
  }, [citations]);

  return (
    <Markdown components={dynamicComponents} remarkPlugins={[remarkGfm]}>
      {processedText}
    </Markdown>
  );
}
