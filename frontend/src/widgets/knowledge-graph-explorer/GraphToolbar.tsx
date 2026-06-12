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
}: GraphToolbarProps) {
  return (
    <div className={styles.toolbar}>
      <label className={styles.field}>
        <span>Search</span>
        <input
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Topic, keyword, or PDF"
          type="search"
          value={searchQuery}
        />
      </label>
      <label className={styles.field}>
        <span>Document</span>
        <select onChange={(event) => onDocumentFilterChange(event.target.value)} value={documentFilter}>
          <option value="all">All documents</option>
          {documents.map((document) => (
            <option key={document} value={document}>
              {document}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.sliderField}>
        <span>Minimum strength {formatPercent(minWeight)}</span>
        <input
          max="1"
          min="0"
          onChange={(event) => onMinWeightChange(Number(event.target.value))}
          step="0.05"
          type="range"
          value={minWeight}
        />
      </label>
      <label className={styles.sliderField}>
        <span>Hop depth {hopDepth === 0 ? "All" : hopDepth}</span>
        <input
          max="4"
          min="0"
          onChange={(event) => onHopDepthChange(Number(event.target.value))}
          step="1"
          type="range"
          value={hopDepth}
        />
      </label>
      <button className={styles.toolbarButton} onClick={onFitToView} type="button">
        Fit to view
      </button>
      <button className={styles.toolbarButton} onClick={onResetView} type="button">
        Reset zoom
      </button>
      <button className={styles.toolbarButton} onClick={onClearSelection} type="button">
        Clear selection
      </button>
    </div>
  );
}
