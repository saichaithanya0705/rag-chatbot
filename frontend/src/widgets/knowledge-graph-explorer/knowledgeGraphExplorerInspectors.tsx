import type { KnowledgeGraphEdge, KnowledgeGraphNode } from "@/shared/api/types";
import {
  buildKnowledgeGraphSummary,
  describeRelationshipReason,
  getNodeDocuments,
  getNodeKeywords,
  getOtherNodeId,
} from "./knowledgeGraphModel";
import { compactPageLabel, edgeKey, formatPercent, type ExplorerLink } from "./knowledgeGraphExplorerShared";
import styles from "./knowledge-graph-explorer.module.css";

export function SummaryInspector({ summary }: { summary: ReturnType<typeof buildKnowledgeGraphSummary> }) {
  return (
    <div className={styles.inspectorSection}>
      <h2>Graph summary</h2>
      <dl className={styles.metricGrid}>
        <div><dt>Topics</dt><dd>{summary.topicCount}</dd></div>
        <div><dt>Relationships</dt><dd>{summary.relationshipCount}</dd></div>
        <div><dt>Documents</dt><dd>{summary.documentCount}</dd></div>
        <div><dt>Isolated Topics</dt><dd>{summary.isolatedNodeCount}</dd></div>
      </dl>
      {summary.mostConnectedNode && (
        <div className={styles.hubBadge} style={{ marginTop: "16px" }}>
          <svg fill="none" height="14" viewBox="0 0 24 24" width="14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
          </svg>
          Largest hub: {summary.mostConnectedNode.label} ({summary.mostConnectedNode.connections} links)
        </div>
      )}
      <p className={styles.helpText}>
        Select a topic for source documents and keywords. Select a line to see why two topics are linked.
      </p>
    </div>
  );
}

export function NodeInspector({
  active,
  edges,
  node,
  nodeLookup,
  onOpenTopic,
  onSelectEdge,
  summary,
}: {
  active: boolean;
  edges: KnowledgeGraphEdge[];
  node: KnowledgeGraphNode;
  nodeLookup: Map<string, KnowledgeGraphNode>;
  onOpenTopic: (collectionId: string) => void;
  onSelectEdge: (edge: KnowledgeGraphEdge) => void;
  summary: ReturnType<typeof buildKnowledgeGraphSummary>;
}) {
  const isHub = summary.mostConnectedNode?.label === node.label;
  const isIsolated = edges.length === 0;

  return (
    <div className={styles.inspectorSection}>
      <h2>{node.label}</h2>

      {isHub && (
        <div className={styles.hubBadge}>
          <svg fill="none" height="12" viewBox="0 0 24 24" width="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
          </svg>
          Primary Hub
        </div>
      )}

      {isIsolated && (
        <div className={styles.isolatedBadge}>
          Isolated topic
        </div>
      )}

      <div className={styles.metaLine}>
        {node.documentCount} PDFs · {node.chunkCount} chunks · {edges.length} links
      </div>
      <button className={styles.primaryAction} onClick={() => onOpenTopic(node.id)} type="button">
        {active ? "Open current chat scope" : "Open in chat"}
      </button>
      <EvidenceList title="Keywords" values={getNodeKeywords(node)} />
      <EvidenceList title="Source PDFs" values={getNodeDocuments(node)} />
      <EvidenceList title="Pages" values={node.pageKeys.map(compactPageLabel)} limit={8} />
      <div className={styles.relationshipList}>
        <h3>Connected topics</h3>
        {edges.length === 0 ? (
          <p className={styles.helpText}>No visible relationships match the current filters.</p>
        ) : (
          edges.map((edge) => {
            const otherNode = nodeLookup.get(getOtherNodeId(edge, node.id));
            return (
              <button className={styles.relationshipButton} key={edgeKey(edge)} onClick={() => onSelectEdge(edge)} type="button">
                <span>{otherNode?.label ?? getOtherNodeId(edge, node.id)}</span>
                <strong>{formatPercent(edge.weight)}</strong>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

export function EdgeInspector({ edge }: { edge: ExplorerLink }) {
  return (
    <div className={styles.inspectorSection}>
      <h2>Relationship evidence</h2>
      <div className={styles.metaLine}>
        {edge.sourceNode.label} → {edge.targetNode.label}
      </div>
      <p className={styles.reason}>{describeRelationshipReason(edge)}</p>
      <dl className={styles.scoreList}>
        <div><dt>Strength</dt><dd>{formatPercent(edge.weight)}</dd></div>
        <div><dt>Semantic</dt><dd>{formatPercent(edge.semanticScore)}</dd></div>
        <div><dt>Page overlap</dt><dd>{formatPercent(edge.pageOverlapScore)}</dd></div>
        <div><dt>Document overlap</dt><dd>{formatPercent(edge.documentOverlapScore)}</dd></div>
      </dl>
      <EvidenceList title="Shared PDFs" values={edge.sharedDocuments ?? []} />
      <EvidenceList title="Shared pages" values={(edge.sharedPages ?? []).map(compactPageLabel)} />
    </div>
  );
}

function EvidenceList({ limit = 6, title, values }: { limit?: number; title: string; values: string[] }) {
  const visibleValues = values.slice(0, limit);
  return (
    <div className={styles.evidenceGroup}>
      <h3>{title}</h3>
      {visibleValues.length === 0 ? (
        <p className={styles.helpText}>No evidence recorded.</p>
      ) : (
        <ul>
          {visibleValues.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      )}
      {values.length > visibleValues.length ? (
        <div className={styles.moreText}>{values.length - visibleValues.length} more</div>
      ) : null}
    </div>
  );
}
