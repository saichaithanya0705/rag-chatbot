import { useState } from "react";
import type { Citation } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import styles from "./evidence-deck.module.css";

interface EvidenceDeckProps {
  citations: Citation[];
  activeCitationId?: string | null;
  onCitationHover?: (citationId: string | null) => void;
  onSelectPdfCitation: (citation: Citation) => void;
}

function getWebHostname(url?: string) {
  if (!url) return "web.archive";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function getExcerptSnippet(citation: Citation): string | null {
  const text = citation.sourceText || citation.excerpt;
  if (!text) return null;
  const cleaned = text.replace(/\s+/g, " ").trim();
  return cleaned.length > 140 ? `${cleaned.slice(0, 140)}...` : cleaned;
}

export function EvidenceDeck({
  citations,
  activeCitationId,
  onCitationHover,
  onSelectPdfCitation,
}: EvidenceDeckProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  if (!citations || citations.length === 0) {
    return null;
  }

  const pdfCount = citations.filter((c) => c.kind === "pdf").length;
  const webCount = citations.filter((c) => c.kind === "web").length;

  return (
    <div className={styles.deckContainer}>
      <div className={styles.deckHeader}>
        <button
          className={styles.deckHeaderToggle}
          onClick={() => setIsExpanded(!isExpanded)}
          type="button"
          aria-expanded={isExpanded}
        >
          <div className={styles.deckHeaderLeft}>
            <span className={styles.deckIcon}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
            </span>
            <span className={styles.deckTitle}>
              EVIDENCE SOURCES <span className={styles.deckCountBadge}>{citations.length}</span>
            </span>
            <span className={styles.deckTelemetry}>
              {pdfCount > 0 && `${pdfCount} PDF${pdfCount > 1 ? "s" : ""}`}
              {pdfCount > 0 && webCount > 0 && " · "}
              {webCount > 0 && `${webCount} WEB`}
            </span>
          </div>

          <div className={styles.deckHeaderRight}>
            <span className={styles.expandLabel}>{isExpanded ? "Collapse" : "Expand"}</span>
            <svg
              className={cn(styles.chevronIcon, isExpanded && styles.chevronRotated)}
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </div>
        </button>
      </div>

      {isExpanded && (
        <div className={styles.deckCardsGrid}>
          {citations.map((citation, index) => {
            const isTargeted = activeCitationId === citation.id || activeCitationId === `idx-${index}`;
            const numStr = String(index + 1).padStart(2, "0");
            const isPdf = citation.kind === "pdf";
            const excerpt = getExcerptSnippet(citation);
            const title = isPdf
              ? citation.pdfName || "Indexed Document"
              : citation.title || getWebHostname(citation.url);

            return (
              <div
                key={citation.id || `cit-${index}`}
                id={`evidence-card-${index}`}
                className={cn(
                  styles.sourceCard,
                  isTargeted && styles.sourceCardActive,
                  isPdf ? styles.cardPdf : styles.cardWeb,
                )}
                onMouseEnter={() => onCitationHover?.(citation.id || `idx-${index}`)}
                onMouseLeave={() => onCitationHover?.(null)}
                onClick={() => {
                  if (isPdf) {
                    onSelectPdfCitation(citation);
                  } else if (citation.url) {
                    window.open(citation.url, "_blank", "noopener,noreferrer");
                  }
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    if (isPdf) {
                      onSelectPdfCitation(citation);
                    } else if (citation.url) {
                      window.open(citation.url, "_blank", "noopener,noreferrer");
                    }
                  }
                }}
              >
                <div className={styles.cardHeader}>
                  <div className={styles.cardIndexBadge}>
                    <span className={styles.cardIndexGlyph}>[{numStr}]</span>
                    <span className={styles.cardTypePill}>
                      {isPdf ? "PDF" : "WEB"}
                    </span>
                  </div>

                  {isPdf && citation.page !== undefined && (
                    <span className={styles.cardPageTag}>
                      p. {citation.page}
                      {citation.sourceLocation && ` · ${citation.sourceLocation}`}
                    </span>
                  )}
                  {!isPdf && citation.url && (
                    <span className={styles.cardHostTag}>
                      {getWebHostname(citation.url)}
                    </span>
                  )}
                </div>

                <div className={styles.cardTitle} title={title}>
                  {title}
                </div>

                {excerpt && (
                  <div className={styles.cardExcerpt}>
                    <span className={styles.cardQuoteMarker}>“</span>
                    {excerpt}
                  </div>
                )}

                <div className={styles.cardFooter}>
                  <span className={styles.cardActionHint}>
                    {isPdf ? (
                      <>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <circle cx="11" cy="11" r="8" />
                          <line x1="21" y1="21" x2="16.65" y2="16.65" />
                        </svg>
                        Inspect page {citation.page ?? ""} ➔
                      </>
                    ) : (
                      <>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                        Open source ↗
                      </>
                    )}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
