import { useCallback, useEffect, useRef, useState } from "react";
import type { Citation } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import styles from "./evidence-deck.module.css";

interface EvidenceDeckProps {
  citations: Citation[];
  activeCitationId?: string | null;
  onCitationHover?: (citationId: string | null) => void;
  onSelectPdfCitation: (citation: Citation) => void;
}

type FilterTab = "all" | "pdf" | "web";

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
  return cleaned.length > 120 ? `${cleaned.slice(0, 120)}...` : cleaned;
}

function isCitationActive(citation: Citation, index: number, activeId?: string | null): boolean {
  if (!activeId) return false;
  return (
    activeId === citation.id ||
    activeId === `idx-${index}` ||
    activeId === `cit-${index}` ||
    activeId === String(index + 1)
  );
}

export function EvidenceDeck({
  citations,
  activeCitationId,
  onCitationHover,
  onSelectPdfCitation,
}: EvidenceDeckProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<FilterTab>("all");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const scrollTrackRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  if (!citations || citations.length === 0) {
    return null;
  }

  const pdfCount = citations.filter((c) => c.kind === "pdf").length;
  const webCount = citations.filter((c) => c.kind === "web").length;
  const hasMixedKinds = pdfCount > 0 && webCount > 0;

  // Filter citations based on activeTab
  const visibleCitationsWithIndex = citations
    .map((cit, originalIndex) => ({ citation: cit, originalIndex }))
    .filter(({ citation }) => {
      if (activeTab === "pdf") return citation.kind === "pdf";
      if (activeTab === "web") return citation.kind === "web";
      return true;
    });

  const updateScrollButtons = useCallback(() => {
    const track = scrollTrackRef.current;
    if (!track) return;
    setCanScrollLeft(track.scrollLeft > 6);
    setCanScrollRight(track.scrollLeft + track.clientWidth < track.scrollWidth - 6);
  }, []);

  // Update scroll buttons on resize/scroll
  useEffect(() => {
    const track = scrollTrackRef.current;
    if (!track) return;
    updateScrollButtons();
    track.addEventListener("scroll", updateScrollButtons, { passive: true });
    window.addEventListener("resize", updateScrollButtons, { passive: true });
    return () => {
      track.removeEventListener("scroll", updateScrollButtons);
      window.removeEventListener("resize", updateScrollButtons);
    };
  }, [updateScrollButtons, visibleCitationsWithIndex, isExpanded]);

  // When activeCitationId changes, auto-scroll to the matching card inside the small box
  useEffect(() => {
    if (!activeCitationId || !isExpanded) return;

    const matchedIndex = citations.findIndex((c, i) => isCitationActive(c, i, activeCitationId));
    if (matchedIndex !== -1) {
      const matchedCitation = citations[matchedIndex];
      // Switch filter tab to "all" if the matched card is currently filtered out
      if (activeTab !== "all" && matchedCitation.kind !== activeTab) {
        setActiveTab("all");
      }

      // Allow DOM to settle then smooth-scroll into center
      const timer = setTimeout(() => {
        const cardEl = cardRefs.current.get(matchedIndex);
        if (cardEl) {
          cardEl.scrollIntoView({
            behavior: "smooth",
            inline: "center",
            block: "nearest",
          });
        }
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [activeCitationId, citations, isExpanded, activeTab]);

  // When citations prop changes (e.g. new query or session switch), reset scroll position
  useEffect(() => {
    if (scrollTrackRef.current) {
      scrollTrackRef.current.scrollTo({ left: 0, behavior: "smooth" });
    }
    setActiveTab("all");
    updateScrollButtons();
  }, [citations, updateScrollButtons]);

  const handleScrollLeft = () => {
    scrollTrackRef.current?.scrollBy({ left: -260, behavior: "smooth" });
  };

  const handleScrollRight = () => {
    scrollTrackRef.current?.scrollBy({ left: 260, behavior: "smooth" });
  };

  const handleCopyExcerpt = (e: React.MouseEvent, citation: Citation, index: number) => {
    e.stopPropagation();
    const text = citation.sourceText || citation.excerpt || citation.title || "";
    if (!text) return;
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    });
  };

  return (
    <div className={styles.deckContainer} aria-label="Cited evidence sources">
      <div className={styles.deckHeader}>
        <div className={styles.deckHeaderLeft}>
          <button
            className={styles.deckTitleBtn}
            onClick={() => setIsExpanded(!isExpanded)}
            type="button"
            aria-expanded={isExpanded}
            title={isExpanded ? "Collapse evidence deck" : "Expand evidence deck"}
          >
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
              SOURCES <span className={styles.deckCountBadge}>{citations.length}</span>
            </span>
          </button>

          {/* Filter tabs if both PDF and Web sources are present */}
          {hasMixedKinds && isExpanded && (
            <div className={styles.filterTabs} role="tablist" aria-label="Filter evidence by kind">
              <button
                className={cn(styles.filterTab, activeTab === "all" && styles.filterTabActive)}
                onClick={() => setActiveTab("all")}
                type="button"
                role="tab"
                aria-selected={activeTab === "all"}
              >
                All ({citations.length})
              </button>
              <button
                className={cn(styles.filterTab, activeTab === "pdf" && styles.filterTabActive)}
                onClick={() => setActiveTab("pdf")}
                type="button"
                role="tab"
                aria-selected={activeTab === "pdf"}
              >
                PDFs ({pdfCount})
              </button>
              <button
                className={cn(styles.filterTab, activeTab === "web" && styles.filterTabActive)}
                onClick={() => setActiveTab("web")}
                type="button"
                role="tab"
                aria-selected={activeTab === "web"}
              >
                Web ({webCount})
              </button>
            </div>
          )}

          {!hasMixedKinds && (
            <span className={styles.deckTelemetry}>
              {pdfCount > 0 && `${pdfCount} PDF${pdfCount > 1 ? "s" : ""}`}
              {webCount > 0 && `${webCount} WEB`}
            </span>
          )}
        </div>

        <div className={styles.deckHeaderRight}>
          {isExpanded && (
            <div className={styles.carouselNavGroup}>
              <button
                className={styles.carouselNavBtn}
                onClick={handleScrollLeft}
                disabled={!canScrollLeft}
                aria-label="Scroll citations left"
                type="button"
                title="Previous sources"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <button
                className={styles.carouselNavBtn}
                onClick={handleScrollRight}
                disabled={!canScrollRight}
                aria-label="Scroll citations right"
                type="button"
                title="Next sources"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            </div>
          )}

          <button
            className={styles.expandToggleBtn}
            onClick={() => setIsExpanded(!isExpanded)}
            type="button"
            aria-expanded={isExpanded}
            title={isExpanded ? "Collapse" : "Expand"}
          >
            <span className={styles.expandLabel}>{isExpanded ? "Collapse" : "Expand"}</span>
            <svg
              className={cn(styles.chevronIcon, isExpanded && styles.chevronRotated)}
              width="11"
              height="11"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className={styles.trackOuterWrapper}>
          {canScrollLeft && <div className={styles.fadeIndicatorLeft} />}
          {canScrollRight && <div className={styles.fadeIndicatorRight} />}

          <div
            className={styles.deckScrollTrack}
            ref={scrollTrackRef}
            tabIndex={0}
            role="region"
            aria-label="Scrollable evidence cards"
          >
            {visibleCitationsWithIndex.map(({ citation, originalIndex }) => {
              const isTargeted = isCitationActive(citation, originalIndex, activeCitationId);
              const numStr = String(originalIndex + 1).padStart(2, "0");
              const isPdf = citation.kind === "pdf";
              const excerpt = getExcerptSnippet(citation);
              const title = isPdf
                ? citation.pdfName || "Indexed Document"
                : citation.title || getWebHostname(citation.url);
              const isCopied = copiedIndex === originalIndex;

              return (
                <div
                  key={citation.id || `cit-${originalIndex}`}
                  id={`evidence-card-${originalIndex}`}
                  ref={(el) => {
                    if (el) {
                      cardRefs.current.set(originalIndex, el);
                    } else {
                      cardRefs.current.delete(originalIndex);
                    }
                  }}
                  className={cn(
                    styles.sourceCard,
                    isTargeted && styles.sourceCardActive,
                    isPdf ? styles.cardPdf : styles.cardWeb,
                  )}
                  onMouseEnter={() => onCitationHover?.(citation.id || `idx-${originalIndex}`)}
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
                    <div className={styles.cardHeaderBadges}>
                      <span className={styles.cardIndexGlyph}>[{numStr}]</span>
                      <span className={isPdf ? styles.cardTypePdf : styles.cardTypeWeb}>
                        {isPdf ? "PDF" : "WEB"}
                      </span>
                      {isPdf && citation.page !== undefined && (
                        <span className={styles.cardPageTag}>
                          p. {citation.page}
                        </span>
                      )}
                      {!isPdf && citation.url && (
                        <span className={styles.cardHostTag} title={citation.url}>
                          {getWebHostname(citation.url)}
                        </span>
                      )}
                    </div>

                    <button
                      className={cn(styles.cardCopyBtn, isCopied && styles.cardCopyBtnSuccess)}
                      onClick={(e) => handleCopyExcerpt(e, citation, originalIndex)}
                      type="button"
                      title={isCopied ? "Excerpt copied!" : "Copy excerpt"}
                      aria-label="Copy excerpt"
                    >
                      {isCopied ? (
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
                          <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
                        </svg>
                      )}
                    </button>
                  </div>

                  <div className={styles.cardTitle} title={title}>
                    {title}
                  </div>

                  {excerpt && (
                    <div className={styles.cardExcerpt} title={excerpt}>
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
                          Inspect p.{citation.page ?? ""} ➔
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
        </div>
      )}
    </div>
  );
}

