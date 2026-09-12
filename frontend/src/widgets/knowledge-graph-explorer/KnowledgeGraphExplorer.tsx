import { useEffect, useMemo, useRef, useState } from "react";
import type { KnowledgeGraph } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import {
  buildKnowledgeGraphSummary,
  filterKnowledgeGraph,
  getIncidentEdges,
  getNodesWithinHops,
  getOtherNodeId,
} from "./knowledgeGraphModel";
import { EdgeInspector, NodeInspector, SummaryInspector } from "./knowledgeGraphExplorerInspectors";
import { buildGraphLayout, edgeKey, uniqueDocuments } from "./knowledgeGraphExplorerShared";
import styles from "./knowledge-graph-explorer.module.css";
import { useKnowledgeGraphCamera } from "./useKnowledgeGraphCamera";
import { useGraphFilters } from "./useGraphFilters";
import { useGraphSelection } from "./useGraphSelection";
import { GraphToolbar } from "./GraphToolbar";
import { GraphCanvas } from "./GraphCanvas";
import { Graph3DCanvas, type Graph3DControls } from "./Graph3DCanvas";
import { GraphGuideModal } from "./GraphGuideModal";
import { AppNavTabs } from "@/shared/ui/app-nav/AppNavTabs";

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
  const graph3dRef = useRef<Graph3DControls>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [viewMode, setViewMode] = useState<"3d" | "2d">("3d");
  const [isGuideOpen, setIsGuideOpen] = useState(false);
  const {
    searchQuery,
    setSearchQuery,
    documentFilter,
    setDocumentFilter,
    minWeight,
    setMinWeight,
    hopDepth,
    setHopDepth,
  } = useGraphFilters();

  const {
    selectedNodeId,
    setSelectedNodeId,
    selectedEdgeKey,
    setSelectedEdgeKey,
    hoveredEdgeKey,
    setHoveredEdgeKey,
    selectNode: selectNodeImpl,
    selectEdge,
    clearSelection,
  } = useGraphSelection(graph);

  const {
    zoom,
    panX,
    panY,
    isPanning,
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

  const neighborhoodRootId = hopDepth > 0 ? selectedNodeId : null;
  const visibleGraph = useMemo(() => {
    let searched = filterKnowledgeGraph(graph, searchQuery);

    if (neighborhoodRootId) {
      const allowedNodes = getNodesWithinHops(searched, neighborhoodRootId, hopDepth);
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
  }, [documentFilter, graph, hopDepth, minWeight, searchQuery, neighborhoodRootId]);

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
    if (selectedNodeId && !visibleGraph.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
    if (selectedEdgeKey && !visibleGraph.edges.some((edge) => edgeKey(edge) === selectedEdgeKey)) {
      setSelectedEdgeKey(null);
    }
  }, [selectedEdgeKey, selectedNodeId, visibleGraph.edges, visibleGraph.nodes, setSelectedNodeId, setSelectedEdgeKey]);

  function selectNode(nodeId: string) {
    selectNodeImpl(nodeId);
    const node = layout?.nodes.find((n) => n.id === nodeId);
    if (node) centerOnNode(node);
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
            aria-label="3D Navigation and Knowledge Graph Guide"
            className={styles.iconButton}
            onClick={() => setIsGuideOpen(true)}
            title="Open 3D Navigation Guide"
            type="button"
          >
            <span style={{ fontSize: 16 }}>💡</span>
          </button>
          <button
            aria-label="Export as PNG"
            className={styles.iconButton}
            onClick={() => viewMode === "3d" ? graph3dRef.current?.exportPng() : exportAsPng()}
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
          <AppNavTabs />
        </div>
      </header>

      <GraphToolbar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        documentFilter={documentFilter}
        onDocumentFilterChange={setDocumentFilter}
        documents={documents}
        minWeight={minWeight}
        onMinWeightChange={setMinWeight}
        hopDepth={hopDepth}
        onHopDepthChange={setHopDepth}
        onFitToView={() => viewMode === "3d" ? graph3dRef.current?.fit() : fitToView(layout)}
        onResetView={() => viewMode === "3d" ? graph3dRef.current?.fit() : resetView()}
        onClearSelection={clearSelection}
        onOpenGuide={() => setIsGuideOpen(true)}
      />

      {hasGraphData && summary.relationshipCount === 0 && (
        <div className={styles.sparseBanner}>
          <div className={styles.sparseBannerContent}>
            <span className={styles.sparseBannerIcon}>💡</span>
            <span className={styles.sparseBannerText}>
              <strong>No relationships found yet:</strong> Re-cluster topics in the PDF Pipeline to compute semantic links across documents.
            </span>
          </div>
          <button className={styles.sparseBannerButton} onClick={onOpenPipeline} type="button">
            Go to Pipeline &amp; Re-cluster ➔
          </button>
        </div>
      )}

      <div className={styles.workspace}>
        {viewMode === "3d" ? (
          <Graph3DCanvas
            controlsRef={graph3dRef}
            activeCollectionId={activeCollectionId}
            connectionCountByNode={connectionCountByNode}
            hasGraphData={hasGraphData}
            layout={layout}
            onOpenGuide={() => setIsGuideOpen(true)}
            onSelectEdge={selectEdge}
            onSelectNode={selectNode}
            onViewModeChange={setViewMode}
            selectedEdgeKey={selectedEdgeKey}
            selectedNeighborIds={selectedNeighborIds}
            selectedNodeId={selectedNodeId}
            viewMode={viewMode}
          />
        ) : (
          <GraphCanvas
            activeCollectionId={activeCollectionId}
            connectionCountByNode={connectionCountByNode}
            containerRef={containerRef}
            hasGraphData={hasGraphData}
            hoveredEdgeKey={hoveredEdgeKey}
            isPanning={isPanning}
            layout={layout}
            mostConnectedNodeConnections={summary.mostConnectedNode?.connections || 1}
            onAnimateCameraTo={animateCameraTo}
            onHoveredEdgeKeyChange={setHoveredEdgeKey}
            onOpenGuide={() => setIsGuideOpen(true)}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onResetView={resetView}
            onSelectEdge={selectEdge}
            onSelectNode={selectNode}
            onViewModeChange={setViewMode}
            onWheel={handleWheel}
            panX={panX}
            panY={panY}
            selectedEdgeKey={selectedEdgeKey}
            selectedNeighborIds={selectedNeighborIds}
            selectedNodeId={selectedNodeId}
            svgRef={svgRef}
            viewBox={viewBox}
            viewMode={viewMode}
            visibleEdges={visibleGraph.edges}
            zoom={zoom}
          />
        )}

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

      <GraphGuideModal isOpen={isGuideOpen} onClose={() => setIsGuideOpen(false)} />
    </div>
  );
}
