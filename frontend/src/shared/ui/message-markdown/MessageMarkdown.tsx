import { useState, useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import type { Citation } from "@/shared/api/types";

interface MessageMarkdownProps {
  content: string;
  citations?: Citation[];
  activeCitationId?: string | null;
  onCitationHover?: (citationId: string | null) => void;
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
            fontFamily: "var(--font-mono)",
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

function InlineCitationLink({
  citation,
  num,
  isActive,
  onHover,
}: {
  citation: Citation;
  num: number;
  isActive?: boolean;
  onHover?: (id: string | null) => void;
}) {
  let actions: ReturnType<typeof useWorkbench>["actions"] | null = null;
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    actions = useWorkbench().actions;
  } catch {
    actions = null;
  }
  const [hovered, setHovered] = useState(false);

  function handleClick(e: React.MouseEvent) {
    e.preventDefault();
    if (citation.kind === "pdf") {
      void actions?.openPdfPreview(citation);
    } else if (citation.url) {
      window.open(citation.url, "_blank", "noopener,noreferrer");
    }
  }

  const isPdf = citation.kind === "pdf";
  const title = isPdf
    ? citation.pdfName || "Indexed PDF"
    : citation.title || citation.url || "Web Source";
  const excerpt = citation.sourceText || citation.excerpt;
  const excerptSnippet = excerpt
    ? excerpt.replace(/\s+/g, " ").trim().slice(0, 110)
    : null;

  return (
    <span
      style={{
        position: "relative",
        display: "inline-block",
        userSelect: "none",
        verticalAlign: "baseline",
      }}
      onMouseEnter={() => {
        setHovered(true);
        onHover?.(citation.id || `idx-${num - 1}`);
      }}
      onMouseLeave={() => {
        setHovered(false);
        onHover?.(null);
      }}
    >
      <button
        onClick={handleClick}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: isActive ? "var(--accent)" : hovered ? "var(--surface-accent)" : "var(--surface-soft)",
          border: isActive
            ? "1px solid var(--accent)"
            : hovered
            ? "1px solid var(--accent)"
            : "0.5px solid var(--border-strong)",
          color: isActive ? "#ffffff" : hovered ? "var(--accent-ink)" : "var(--accent)",
          fontFamily: "var(--font-mono)",
          fontSize: "10px",
          fontWeight: 700,
          borderRadius: "4px",
          padding: "0 4px",
          margin: "0 2px",
          height: "17px",
          cursor: "pointer",
          verticalAlign: "super",
          boxShadow: isActive || hovered ? "var(--glow-accent)" : "var(--shadow-soft)",
          transform: isActive || hovered ? "translateY(-1px) scale(1.06)" : "none",
          transition: "all var(--transition-fast)",
        }}
        type="button"
        aria-label={`Source citation ${num}: ${title}`}
      >
        [{num}]
      </button>

      {hovered && (
        <span
          style={{
            position: "absolute",
            bottom: "100%",
            left: "50%",
            transform: "translateX(-50%) translateY(-6px)",
            backgroundColor: "var(--surface-hud)",
            backdropFilter: "blur(8px)",
            color: "var(--text-strong)",
            border: "1px solid var(--accent-border)",
            padding: "8px 10px",
            borderRadius: "8px",
            fontSize: "11px",
            width: "max-content",
            maxWidth: "260px",
            zIndex: 9999,
            boxShadow: "var(--shadow-hud), var(--glow-subtle)",
            pointerEvents: "none",
            lineHeight: "1.35",
            animation: "hudPopIn 160ms ease",
            textAlign: "left",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "6px" }}>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "9px",
                fontWeight: 700,
                color: isPdf ? "var(--accent)" : "var(--tech-amber)",
                background: isPdf ? "var(--surface-accent)" : "var(--warning-surface)",
                padding: "1px 4px",
                borderRadius: "3px",
                textTransform: "uppercase",
              }}
            >
              {isPdf ? "📄 PDF EVIDENCE" : "🌐 WEB EVIDENCE"}
            </span>
            {isPdf && citation.page !== undefined && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "9px",
                  fontWeight: 600,
                  color: "var(--text-subtle-aa)",
                }}
              >
                p. {citation.page}
              </span>
            )}
          </div>

          <div
            style={{
              fontWeight: 600,
              fontSize: "11px",
              color: "var(--text-strong)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {title}
          </div>

          {excerptSnippet && (
            <div
              style={{
                fontSize: "10px",
                color: "var(--text-muted)",
                fontStyle: "italic",
                borderLeft: "2px solid var(--accent)",
                paddingLeft: "6px",
                marginTop: "2px",
                lineHeight: "1.3",
              }}
            >
              “{excerptSnippet}...”
            </div>
          )}

          <div
            style={{
              marginTop: "4px",
              paddingTop: "4px",
              borderTop: "0.5px solid var(--border-soft)",
              fontFamily: "var(--font-mono)",
              fontSize: "9px",
              fontWeight: 600,
              color: "var(--accent)",
              textAlign: "right",
            }}
          >
            {isPdf ? "Click to view page in PDF preview ➔" : "Click to open web source ↗"}
          </div>
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

export function MessageMarkdown({
  content,
  citations,
  activeCitationId,
  onCitationHover,
}: MessageMarkdownProps) {
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
            const isActive =
              activeCitationId === citation.id ||
              activeCitationId === `idx-${idx}`;
            return (
              <InlineCitationLink
                citation={citation}
                num={idx + 1}
                isActive={isActive}
                onHover={onCitationHover}
              />
            );
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
  }, [citations, activeCitationId, onCitationHover]);

  return (
    <Markdown
      components={dynamicComponents}
      remarkPlugins={[remarkGfm]}
      urlTransform={(url) => url}
    >
      {processedText}
    </Markdown>
  );
}
