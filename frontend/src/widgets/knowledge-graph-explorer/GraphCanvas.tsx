import type { CSSProperties } from "react";
import type { KnowledgeGraphEdge } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { edgeKey, formatPercent, lerpColor, GRAPH_HEIGHT, GRAPH_WIDTH } from "./knowledgeGraphExplorerShared";
import styles from "./knowledge-graph-explorer.module.css";

export interface GraphLayoutNode {
  id: string;
  label: string;
  x: number;
  y: number;
  radius: number;
  chunkCount: number;
}

export interface GraphLayoutLink {
  source: string;
  target: string;
  sourceNode: GraphLayoutNode;
  targetNode: GraphLayoutNode;
  weight: number;
}

export interface GraphLayout {
  nodes: GraphLayoutNode[];
  links: GraphLayoutLink[];
}

interface GraphCanvasProps {
  containerRef: React.RefObject<HTMLElement | null>;
  svgRef: React.RefObject<SVGSVGElement | null>;
  layout: GraphLayout | null;
  isPanning: boolean;
  viewBox: string;
  zoom: number;
  panX: number;
  panY: number;
  selectedNodeId: string | null;
  selectedEdgeKey: string | null;
  hoveredEdgeKey: string | null;
  activeCollectionId: string;
  connectionCountByNode: Map<string, number>;
  selectedNeighborIds: Set<string>;
  mostConnectedNodeConnections: number;
  hasGraphData: boolean;
  onPointerDown: (e: React.PointerEvent<SVGSVGElement>) => void;
  onPointerMove: (e: React.PointerEvent<SVGSVGElement>) => void;
  onPointerUp: (e: React.PointerEvent<SVGSVGElement>) => void;
  onWheel: (e: React.WheelEvent<SVGSVGElement>) => void;
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edge: KnowledgeGraphEdge) => void;
  onHoveredEdgeKeyChange: (key: string | null) => void;
  onResetView: () => void;
  onAnimateCameraTo: (x: number, y: number, z: number) => void;
  visibleEdges: KnowledgeGraphEdge[];
}

export function GraphCanvas({
  containerRef,
  svgRef,
  layout,
  isPanning,
  viewBox,
  zoom,
  panX,
  panY,
  selectedNodeId,
  selectedEdgeKey,
  hoveredEdgeKey,
  activeCollectionId,
  connectionCountByNode,
  selectedNeighborIds,
  mostConnectedNodeConnections,
  hasGraphData,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onWheel,
  onSelectNode,
  onSelectEdge,
  onHoveredEdgeKeyChange,
  onResetView,
  onAnimateCameraTo,
  visibleEdges,
}: GraphCanvasProps) {
  return (
    <section aria-label="Knowledge graph canvas" className={styles.canvasPanel} ref={containerRef}>
      {layout ? (
        <svg
          aria-label="Knowledge graph topic map"
          className={cn(styles.canvas, isPanning && styles.canvasPanning)}
          onDoubleClick={onResetView}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onWheel={onWheel}
          ref={svgRef}
          role="img"
          viewBox={viewBox}
        >
          <g>
            {layout.links.map((edge) => {
              const key = edgeKey(edge);
              const selected = selectedEdgeKey === key;
              const dimmed =
                selectedNodeId != null && edge.source !== selectedNodeId && edge.target !== selectedNodeId;
              return (
                <g key={key}>
                  <line
                    className={cn(styles.edge, selected && styles.edgeSelected, dimmed && styles.dimmed)}
                    strokeWidth={1 + edge.weight * 5}
                    x1={edge.sourceNode.x}
                    x2={edge.targetNode.x}
                    y1={edge.sourceNode.y}
                    y2={edge.targetNode.y}
                  />
                  <line
                    aria-label={`${edge.sourceNode.label} to ${edge.targetNode.label}`}
                    className={styles.edgeHit}
                    onClick={() => onSelectEdge(edge)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectEdge(edge);
                      }
                    }}
                    onMouseEnter={() => onHoveredEdgeKeyChange(key)}
                    onMouseLeave={() => onHoveredEdgeKeyChange(null)}
                    role="button"
                    strokeWidth={14}
                    tabIndex={0}
                    x1={edge.sourceNode.x}
                    x2={edge.targetNode.x}
                    y1={edge.sourceNode.y}
                    y2={edge.targetNode.y}
                  />
                </g>
              );
            })}
          </g>
          <g>
            {layout.nodes.map((node) => {
              const selected = selectedNodeId === node.id || activeCollectionId === node.id;
              const connected = selectedNeighborIds.has(node.id);
              const dimmed = selectedNodeId != null && !selected && !connected;
              const connections = connectionCountByNode.get(node.id) ?? 0;
              const connectionRatio = connections / (mostConnectedNodeConnections || 1);
              const fill = lerpColor("#e6e4dc", "#c4bfef", connectionRatio);
              const isOrphan = connections === 0;

              return (
                <g
                  className={cn(styles.node, styles.nodeEnter, dimmed && styles.dimmed)}
                  key={node.id}
                  style={{ animationDelay: `${Math.random() * 200}ms` } as CSSProperties}
                >
                  <circle
                    aria-label={`${node.label}, ${node.chunkCount} chunks`}
                    aria-pressed={selected}
                    className={styles.nodeButton}
                    cx={node.x}
                    cy={node.y}
                    onClick={() => onSelectNode(node.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectNode(node.id);
                      }
                    }}
                    r={node.radius + 5}
                    role="button"
                    tabIndex={0}
                  />
                  <circle
                    className={cn(
                      styles.nodeCircle,
                      selected && styles.nodeSelected,
                      isOrphan && styles.nodeOrphan,
                    )}
                    cx={node.x}
                    cy={node.y}
                    r={node.radius}
                    style={{ "--node-fill": fill } as CSSProperties}
                  />
                  <text className={styles.nodeLabel} textAnchor="middle" x={node.x} y={node.y + 4}>
                    {node.label.length > 20 ? `${node.label.slice(0, 18)}...` : node.label}
                  </text>
                </g>
              );
            })}
          </g>
          <g>
            {layout.links.map((edge) => {
              const key = edgeKey(edge);
              const cx = (edge.sourceNode.x + edge.targetNode.x) / 2;
              const cy = (edge.sourceNode.y + edge.targetNode.y) / 2;
              const isHovered = hoveredEdgeKey === key;
              const isSelected = selectedEdgeKey === key;
              if (!isHovered && !isSelected) return null;
              return (
                <text
                  className={cn(styles.edgeLabel, (isHovered || isSelected) && styles.edgeLabelVisible)}
                  key={`label-${key}`}
                  textAnchor="middle"
                  x={cx}
                  y={cy}
                >
                  {formatPercent(edge.weight)} match
                </text>
              );
            })}
          </g>
        </svg>
      ) : (
        <div className={styles.emptyCanvas}>
          <h2>{hasGraphData ? "No topics match this view" : "No topics yet"}</h2>
          <p>
            {hasGraphData
              ? "Clear the search or lower the strength filter to bring topics back into the map."
              : "Re-cluster indexed PDFs to build the relationship map."}
          </p>
        </div>
      )}

      {layout && (
        <div
          className={styles.minimap}
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const x = (event.clientX - rect.left) / rect.width;
            const y = (event.clientY - rect.top) / rect.height;
            onAnimateCameraTo(GRAPH_WIDTH / 2 - x * GRAPH_WIDTH, GRAPH_HEIGHT / 2 - y * GRAPH_HEIGHT, zoom);
          }}
        >
          <svg
            className={styles.minimapSvg}
            viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
            preserveAspectRatio="xMidYMid meet"
          >
            <g>
              {layout.links.map((edge) => (
                <line
                  key={edgeKey(edge)}
                  className={styles.minimapEdge}
                  x1={edge.sourceNode.x}
                  x2={edge.targetNode.x}
                  y1={edge.sourceNode.y}
                  y2={edge.targetNode.y}
                />
              ))}
            </g>
            <g>
              {layout.nodes.map((node) => (
                <circle
                  key={node.id}
                  className={styles.minimapNode}
                  cx={node.x}
                  cy={node.y}
                  r={Math.max(node.radius, 12)}
                  fill={selectedNodeId === node.id ? "var(--accent)" : "var(--border-strong)"}
                />
              ))}
            </g>
            <rect
              className={styles.minimapViewport}
              x={-panX}
              y={-panY}
              width={GRAPH_WIDTH / zoom}
              height={GRAPH_HEIGHT / zoom}
            />
          </svg>
        </div>
      )}

      <div className={styles.legend}>
        <div className={styles.legendItem}>
          <span className={styles.legendGradient}></span>
          <span>Connections</span>
        </div>
        <div className={styles.legendItem}>
          <div className={styles.legendSizeDemo}>
            <span className={cn(styles.legendDot, styles.legendDotSm)}></span>
            <span className={cn(styles.legendDot, styles.legendDotMd)}></span>
            <span className={cn(styles.legendDot, styles.legendDotLg)}></span>
          </div>
          <span>Chunks</span>
        </div>
        <div className={styles.legendItem}>
          <span className={styles.legendOrphanDemo}></span>
          <span>Isolated topic</span>
        </div>
      </div>

      <div className={styles.graphHint}>Scroll to zoom, drag to pan</div>
    </section>
  );
}
