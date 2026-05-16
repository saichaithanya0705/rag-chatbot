import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useSearchParams } from "react-router-dom";
import type { KnowledgeGraph, KnowledgeGraphEdge } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import {
  buildKnowledgeGraphSummary,
  filterKnowledgeGraph,
  getIncidentEdges,
  getNodesWithinHops,
  getOtherNodeId,
} from "./knowledgeGraphModel";
import { EdgeInspector, NodeInspector, SummaryInspector } from "./knowledgeGraphExplorerInspectors";
import {
  GRAPH_HEIGHT,
  GRAPH_WIDTH,
  buildGraphLayout,
  edgeKey,
  formatPercent,
  lerpColor,
  uniqueDocuments,
} from "./knowledgeGraphExplorerShared";
import styles from "./knowledge-graph-explorer.module.css";
import { useKnowledgeGraphCamera } from "./useKnowledgeGraphCamera";

interface KnowledgeGraphExplorerProps {
  activeCollectionId: string;
  graph: KnowledgeGraph;
  onOpenTopic: (collectionId: string) => void;
  onOpenPipeline: () => void;
}

export function KnowledgeGraphExplorer({
  activeCollectionId,
  graph,
  onOpenPipeline,
  onOpenTopic,
}: KnowledgeGraphExplorerProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState("");
  const [documentFilter, setDocumentFilter] = useState("all");
  const [minWeight, setMinWeight] = useState(0);
  const [hopDepth, setHopDepth] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [hoveredEdgeKey, setHoveredEdgeKey] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const {
    zoom,
    panX,
    panY,
    isPanning,
    containerSize,
    svgRef,
    containerRef,
    viewBox,
    animateCameraTo,
    centerOnNode,
    resetView,
    fitToView,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
    handleWheel,
    exportAsPng,
  } = useKnowledgeGraphCamera({
    interactiveSelector: `.${styles.nodeButton}, .${styles.edgeHit}`,
  });

  const summary = useMemo(() => buildKnowledgeGraphSummary(graph), [graph]);
  const documents = useMemo(() => uniqueDocuments(graph), [graph]);

  const visibleGraph = useMemo(() => {
    let searched = filterKnowledgeGraph(graph, searchQuery);

    if (selectedNodeId && hopDepth > 0) {
      const allowedNodes = getNodesWithinHops(searched, selectedNodeId, hopDepth);
      searched = {
        nodes: searched.nodes.filter((n) => allowedNodes.has(n.id)),
        edges: searched.edges.filter((e) => allowedNodes.has(e.source) && allowedNodes.has(e.target)),
      };
    }

    const nodes = searched.nodes.filter((node) =>
      documentFilter === "all" ? true : node.sourceDocuments.includes(documentFilter),
    );
    const nodeIds = new Set(nodes.map((node) => node.id));
    return {
      nodes,
      edges: searched.edges.filter(
        (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) && edge.weight >= minWeight,
      ),
    };
  }, [documentFilter, graph, hopDepth, minWeight, searchQuery, selectedNodeId]);

  const layout = useMemo(() => buildGraphLayout(visibleGraph), [visibleGraph]);
  const selectedNode = layout?.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = layout?.links.find((edge) => edgeKey(edge) === selectedEdgeKey) ?? null;
  const incidentEdges = useMemo(
    () => getIncidentEdges(visibleGraph, selectedNodeId),
    [selectedNodeId, visibleGraph],
  );
  const nodeLookup = useMemo(
    () => new Map(visibleGraph.nodes.map((node) => [node.id, node])),
    [visibleGraph.nodes],
  );
  const connectionCountByNode = useMemo(() => {
    const counts = new Map<string, number>();
    visibleGraph.edges.forEach((edge) => {
      counts.set(edge.source, (counts.get(edge.source) ?? 0) + 1);
      counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1);
    });
    return counts;
  }, [visibleGraph.edges]);

  useEffect(() => {
    const topicParam = searchParams.get("topic");
    const edgeParam = searchParams.get("edge");
    if (topicParam && graph.nodes.some((node) => node.id === topicParam)) {
      setSelectedNodeId(topicParam);
      setSelectedEdgeKey(null);
      return;
    }
    if (edgeParam && graph.edges.some((edge) => edgeKey(edge) === edgeParam)) {
      setSelectedEdgeKey(edgeParam);
      setSelectedNodeId(null);
    }
  }, [graph.edges, graph.nodes, searchParams]);

  useEffect(() => {
    if (selectedNodeId && !visibleGraph.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
    if (selectedEdgeKey && !visibleGraph.edges.some((edge) => edgeKey(edge) === selectedEdgeKey)) {
      setSelectedEdgeKey(null);
    }
  }, [selectedEdgeKey, selectedNodeId, visibleGraph.edges, visibleGraph.nodes]);

  function selectNode(nodeId: string) {
    setSelectedNodeId(nodeId);
    setSelectedEdgeKey(null);
    setSearchParams({ topic: nodeId });
    const node = layout?.nodes.find((n) => n.id === nodeId);
    if (node) centerOnNode(node);
  }

  function selectEdge(edge: KnowledgeGraphEdge) {
    const key = edgeKey(edge);
    setSelectedEdgeKey(key);
    setSelectedNodeId(null);
    setSearchParams({ edge: key });
  }

  function clearSelection() {
    setSelectedNodeId(null);
    setSelectedEdgeKey(null);
    setHoveredEdgeKey(null);
    setSearchParams({});
  }

  useEffect(() => {
    if (layout && layout.nodes.length > 0) {
      const raf = requestAnimationFrame(() => {
        fitToView(layout);
      });
      return () => cancelAnimationFrame(raf);
    }
  }, [fitToView, layout]);

  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsFullscreen(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  const selectedNeighborIds = new Set(
    incidentEdges.map((edge) => (selectedNodeId ? getOtherNodeId(edge, selectedNodeId) : "")),
  );
  const hasGraphData = graph.nodes.length > 0;

  return (
    <div className={cn(styles.explorer, isFullscreen && styles.explorerFullscreen)}>
      <header className={styles.header}>
        <button className={styles.backButton} onClick={onOpenPipeline} type="button">
          <svg aria-hidden="true" fill="none" height="16" viewBox="0 0 16 16" width="16">
            <path d="M10 3L5 8L10 13" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
          </svg>
          Pipeline
        </button>
        <div className={styles.titleBlock}>
          <h1 className={styles.title}>Knowledge graph</h1>
          <p className={styles.subhead}>Explore topic relationships and inspect the evidence behind each connection.</p>
        </div>
        <div className={styles.headerRight}>
          <div className={styles.headerStats}>
            <span>{summary.topicCount} topics</span>
            <span>{summary.relationshipCount} links</span>
            <span>{summary.documentCount} PDFs</span>
          </div>
          <button
            aria-label="Export as PNG"
            className={styles.iconButton}
            onClick={exportAsPng}
            title="Export as PNG"
            type="button"
          >
            <svg fill="none" height="18" viewBox="0 0 24 24" width="18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </button>
          <button
            aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
            className={cn(styles.iconButton, isFullscreen && styles.iconButtonActive)}
            onClick={() => setIsFullscreen(!isFullscreen)}
            title="Toggle fullscreen"
            type="button"
          >
            {isFullscreen ? (
              <svg fill="none" height="18" viewBox="0 0 24 24" width="18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path>
              </svg>
            ) : (
              <svg fill="none" height="18" viewBox="0 0 24 24" width="18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>
              </svg>
            )}
          </button>
        </div>
      </header>

      <div className={styles.toolbar}>
        <label className={styles.field}>
          <span>Search</span>
          <input
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Topic, keyword, or PDF"
            type="search"
            value={searchQuery}
          />
        </label>
        <label className={styles.field}>
          <span>Document</span>
          <select onChange={(event) => setDocumentFilter(event.target.value)} value={documentFilter}>
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
            onChange={(event) => setMinWeight(Number(event.target.value))}
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
            onChange={(event) => setHopDepth(Number(event.target.value))}
            step="1"
            type="range"
            value={hopDepth}
          />
        </label>
        <button className={styles.toolbarButton} onClick={() => fitToView(layout)} type="button">
          Fit to view
        </button>
        <button className={styles.toolbarButton} onClick={resetView} type="button">
          Reset zoom
        </button>
        <button className={styles.toolbarButton} onClick={clearSelection} type="button">
          Clear selection
        </button>
      </div>

      <div className={styles.workspace}>
        <section aria-label="Knowledge graph canvas" className={styles.canvasPanel} ref={containerRef}>
          {layout ? (
            <svg
              aria-label="Knowledge graph topic map"
              className={cn(styles.canvas, isPanning && styles.canvasPanning)}
              onDoubleClick={resetView}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onWheel={handleWheel}
              ref={svgRef}
              role="img"
              viewBox={viewBox}
            >
              <g>
                {layout.links.map((edge) => {
                  const key = edgeKey(edge);
                  const selected = selectedEdgeKey === key;
                  const dimmed =
                    selectedNodeId != null &&
                    edge.source !== selectedNodeId &&
                    edge.target !== selectedNodeId;
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
                        onClick={() => selectEdge(edge)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            selectEdge(edge);
                          }
                        }}
                        onMouseEnter={() => setHoveredEdgeKey(key)}
                        onMouseLeave={() => setHoveredEdgeKey(null)}
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
                  const maxConnections = summary.mostConnectedNode?.connections || 1;
                  const connectionRatio = connections / maxConnections;
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
                        onClick={() => selectNode(node.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            selectNode(node.id);
                          }
                        }}
                        r={node.radius + 5}
                        role="button"
                        tabIndex={0}
                      />
                      <circle
                        className={cn(styles.nodeCircle, selected && styles.nodeSelected, isOrphan && styles.nodeOrphan)}
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
                animateCameraTo(GRAPH_WIDTH / 2 - x * GRAPH_WIDTH, GRAPH_HEIGHT / 2 - y * GRAPH_HEIGHT, zoom);
              }}
            >
              <svg className={styles.minimapSvg} viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`} preserveAspectRatio="xMidYMid meet">
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

        <aside className={styles.inspector} aria-label="Knowledge graph details">
          {selectedEdge ? (
            <EdgeInspector edge={selectedEdge} />
          ) : selectedNode ? (
            <NodeInspector
              active={selectedNode.id === activeCollectionId}
              edges={incidentEdges}
              node={selectedNode}
              nodeLookup={nodeLookup}
              onOpenTopic={onOpenTopic}
              onSelectEdge={selectEdge}
              summary={summary}
            />
          ) : (
            <SummaryInspector summary={summary} />
          )}
        </aside>
      </div>
    </div>
  );
}
