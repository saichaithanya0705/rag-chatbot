import type { CSSProperties } from "react";
import { formatPercent } from "./knowledgeGraphExplorerShared";
import styles from "./knowledge-graph-explorer.module.css";

interface GraphToolbarProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  documentFilter: string;
  onDocumentFilterChange: (filter: string) => void;
  documents: string[];
  minWeight: number;
  onMinWeightChange: (weight: number) => void;
  hopDepth: number;
  onHopDepthChange: (depth: number) => void;
  onFitToView: () => void;
  onResetView: () => void;
  onClearSelection: () => void;
  onOpenGuide?: () => void;
}

export function GraphToolbar({
  searchQuery,
  onSearchChange,
  documentFilter,
  onDocumentFilterChange,
  documents,
  minWeight,
  onMinWeightChange,
  hopDepth,
  onHopDepthChange,
  onFitToView,
  onResetView,
  onClearSelection,
  onOpenGuide,
}: GraphToolbarProps) {
  return (
    <div className={styles.toolbar}>
      {/* Zone 1: Left - Search & Document Scope */}
      <div className={styles.toolbarLeft}>
        <div className={styles.searchFieldWrapper}>
          <svg className={styles.searchIconSvg} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            aria-label="Search topics or keywords"
            className={styles.searchInput}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search topics, keywords..."
            type="search"
            value={searchQuery}
          />
        </div>

        <div className={styles.selectFieldWrapper}>
          <select
            aria-label="Filter by document"
            className={styles.documentSelect}
            onChange={(event) => onDocumentFilterChange(event.target.value)}
            value={documentFilter}
          >
            <option value="all">All documents</option>
            {documents.map((document) => (
              <option key={document} value={document}>
                {document}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Zone 2: Center - Interactive Sliders with Live Badges */}
      <div className={styles.toolbarCenter}>
        <div className={styles.sliderGroup}>
          <div className={styles.sliderHeader}>
            <span className={styles.sliderLabel}>Strength</span>
            <span className={styles.sliderBadge}>{formatPercent(minWeight)}</span>
          </div>
          <input
            aria-label={`Minimum strength ${formatPercent(minWeight)}`}
            className={styles.rangeInput}
            max="1"
            min="0"
            onChange={(event) => onMinWeightChange(Number(event.target.value))}
            step="0.05"
            type="range"
            value={minWeight}
          />
        </div>

        <div className={styles.sliderGroup}>
          <div className={styles.sliderHeader}>
            <span className={styles.sliderLabel}>Hops</span>
            <span className={styles.sliderBadge}>{hopDepth === 0 ? "All" : `${hopDepth} ${hopDepth === 1 ? "hop" : "hops"}`}</span>
          </div>
          <input
            aria-label={`Hop depth ${hopDepth === 0 ? "All" : hopDepth}`}
            className={styles.rangeInput}
            max="4"
            min="0"
            onChange={(event) => onHopDepthChange(Number(event.target.value))}
            step="1"
            type="range"
            value={hopDepth}
          />
        </div>
      </div>

      {/* Zone 3: Right - Camera & Selection Actions */}
      <div className={styles.toolbarRight}>
        <button className={styles.toolbarButton} onClick={onFitToView} title="Fit entire graph in view" type="button">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
          Fit view
        </button>
        <button className={styles.toolbarButton} onClick={onResetView} title="Reset camera zoom" type="button">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          Reset
        </button>
        <button className={styles.toolbarButton} onClick={onClearSelection} title="Clear selected node or edge" type="button">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          Clear
        </button>
        {onOpenGuide && (
          <button className={styles.toolbarButton} onClick={onOpenGuide} title="Open 3D Navigation Guide" type="button">
            💡 Guide
          </button>
        )}
      </div>
    </div>
  );
}
