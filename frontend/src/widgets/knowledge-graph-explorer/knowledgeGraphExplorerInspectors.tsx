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
  const isHub = edges.length >= 3 || (Boolean(summary.mostConnectedNode) && summary.mostConnectedNode?.label === node.label && edges.length >= 2);
  const isConnected = edges.length > 0 && !isHub;
  const isStandalone = edges.length === 0;

  return (
    <div className={styles.inspectorSection}>
      <h2>{node.label}</h2>

      {isHub && (
        <div className={styles.hubBadge}>
          <svg fill="none" height="12" viewBox="0 0 24 24" width="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
          </svg>
          Core Hub ({edges.length} links)
        </div>
      )}

      {isConnected && (
        <div className={styles.connectedBadge}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
          Connected Topic ({edges.length} links)
        </div>
      )}

      {isStandalone && (
        <div className={styles.isolatedBadge}>
          📌 Standalone Topic
        </div>
      )}

      <div className={styles.metaLine}>
        {node.documentCount} {node.documentCount === 1 ? "PDF" : "PDFs"} · {node.chunkCount} chunks · {edges.length} links
      </div>

      <button className={styles.primaryAction} onClick={() => onOpenTopic(node.id)} type="button">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        {active ? "Currently scoped in chat" : "Ask chat about this topic ➔"}
      </button>

      {isStandalone && (
        <div className={styles.standaloneTip}>
          <span>💡</span>
          <div>
            <strong>Standalone concept:</strong> No cross-document links formed yet. Uploading complementary PDFs or lowering the minimum strength slider connects related topics.
          </div>
        </div>
      )}

      <EvidenceList title="Key Concept Keywords" values={getNodeKeywords(node)} />
      <EvidenceList title="Source PDF Documents" values={getNodeDocuments(node)} />
      <EvidenceList title="Cited Page References" values={node.pageKeys.map(compactPageLabel)} limit={8} />

      <div className={styles.relationshipList}>
        <h3>Connected topics ({edges.length})</h3>
        {edges.length === 0 ? (
          <p className={styles.helpText}>No connected topics match the current filter.</p>
        ) : (
          edges.map((edge) => {
            const otherNode = nodeLookup.get(getOtherNodeId(edge, node.id));
            const percent = Math.round(edge.weight * 100);
            return (
              <button className={styles.relationshipButton} key={edgeKey(edge)} onClick={() => onSelectEdge(edge)} type="button">
                <div className={styles.relButtonMain}>
                  <span className={styles.relButtonTitle}>{otherNode?.label ?? getOtherNodeId(edge, node.id)}</span>
                  <div className={styles.strengthMeter}>
                    <div className={styles.strengthTrack}>
                      <div className={styles.strengthFill} style={{ width: `${percent}%` }} />
                    </div>
                    <span className={styles.strengthLabel}>{percent}%</span>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

export function EdgeInspector({ edge }: { edge: ExplorerLink }) {
  const scores = [
    { label: "Overall Correlation", value: edge.weight },
    { label: "Semantic Similarity", value: edge.semanticScore },
    { label: "Page Overlap", value: edge.pageOverlapScore },
    { label: "Document Overlap", value: edge.documentOverlapScore },
  ];

  return (
    <div className={styles.inspectorSection}>
      <h2>Relationship Evidence</h2>
      <div className={styles.metaLine}>
        {edge.sourceNode.label} ⟷ {edge.targetNode.label}
      </div>
      <p className={styles.reason}>{describeRelationshipReason(edge)}</p>

      <div className={styles.edgeScoreBars}>
        {scores.map((score) => (
          <div className={styles.edgeScoreRow} key={score.label}>
            <div className={styles.edgeScoreHeader}>
              <span className={styles.edgeScoreLabel}>{score.label}</span>
              <span className={styles.edgeScoreVal}>{formatPercent(score.value)}</span>
            </div>
            <div className={styles.edgeScoreTrack}>
              <div
                className={styles.edgeScoreFill}
                style={{ width: `${Math.round((score.value ?? 0) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <EvidenceList title="Shared PDF Documents" values={edge.sharedDocuments ?? []} />
      <EvidenceList title="Shared Document Pages" values={(edge.sharedPages ?? []).map(compactPageLabel)} />
    </div>
  );
}

function EvidenceList({ limit = 8, title, values }: { limit?: number; title: string; values: string[] }) {
  const visibleValues = values.slice(0, limit);
  return (
    <div className={styles.evidenceGroup}>
      <h3>{title}</h3>
      {visibleValues.length === 0 ? (
        <p className={styles.helpText}>No evidence recorded.</p>
      ) : (
        <div className={styles.chipList}>
          {visibleValues.map((value) => (
            <span className={styles.chip} key={value} title={value}>
              {value}
            </span>
          ))}
        </div>
      )}
      {values.length > visibleValues.length ? (
        <div className={styles.moreText}>+{values.length - visibleValues.length} more</div>
      ) : null}
    </div>
  );
}
