import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent, type WheelEvent } from "react";
import { useSearchParams } from "react-router-dom";
import type { KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import {
  buildKnowledgeGraphSummary,
  describeRelationshipReason,
  filterKnowledgeGraph,
  getIncidentEdges,
  getNeighborIds,
  getNodeDocuments,
  getNodeKeywords,
  getNodesWithinHops,
  getOtherNodeId,
} from "./knowledgeGraphModel";
import styles from "./knowledge-graph-explorer.module.css";

const GRAPH_WIDTH = 1040;
const GRAPH_HEIGHT = 620;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 3.5;
const CAMERA_ANIM_MS = 380;

interface ExplorerNode extends KnowledgeGraphNode {
  radius: number;
  x: number;
  y: number;
}

interface SimLink {
  source: string | ExplorerNode;
  target: string | ExplorerNode;
  weight: number;
}

interface ExplorerLink extends KnowledgeGraphEdge {
  sourceNode: ExplorerNode;
  targetNode: ExplorerNode;
}

interface GraphLayout {
  nodes: ExplorerNode[];
  links: ExplorerLink[];
}

interface KnowledgeGraphExplorerProps {
  activeCollectionId: string;
  graph: KnowledgeGraph;
  onOpenTopic: (collectionId: string) => void;
  onOpenPipeline: () => void;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function edgeKey(edge: Pick<KnowledgeGraphEdge, "source" | "target">) {
  return [edge.source, edge.target].sort().join("::");
}

function formatPercent(value: number | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function uniqueDocuments(graph: KnowledgeGraph) {
  const documents = new Set<string>();
  graph.nodes.forEach((node) => node.sourceDocuments.forEach((document) => documents.add(document)));
  return [...documents].sort((a, b) => a.localeCompare(b));
}

function compactPageLabel(pageKey: string) {
  const [document, page] = pageKey.split(":");
  return page ? `${document}, p. ${page}` : pageKey;
}

/** Interpolate between two hex colors */
function lerpColor(startHex: string, endHex: string, t: number): string {
  const parse = (hex: string) => {
    const h = hex.replace("#", "");
    return [Number.parseInt(h.slice(0, 2), 16), Number.parseInt(h.slice(2, 4), 16), Number.parseInt(h.slice(4, 6), 16)];
  };
  const [r1, g1, b1] = parse(startHex);
  const [r2, g2, b2] = parse(endHex);
  const m = clamp(t, 0, 1);
  return `rgb(${Math.round(r1 + (r2 - r1) * m)}, ${Math.round(g1 + (g2 - g1) * m)}, ${Math.round(b1 + (b2 - b1) * m)})`;
}

/** Push apart overlapping nodes after d3 simulation */
function resolveNodeOverlap(nodes: ExplorerNode[]) {
  const resolved = nodes.map((n) => ({ ...n }));
  for (let iteration = 0; iteration < 36; iteration++) {
    let moved = false;
    for (let i = 0; i < resolved.length; i++) {
      for (let j = i + 1; j < resolved.length; j++) {
        const a = resolved[i];
        const b = resolved[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.hypot(dx, dy) || 0.001;
        const minDist = a.radius + b.radius + 24;
        if (dist >= minDist) continue;
        const overlap = (minDist - dist) / 2;
        const ux = dx / dist;
        const uy = dy / dist;
        a.x = clamp(a.x - ux * overlap, a.radius + 14, GRAPH_WIDTH - a.radius - 14);
        a.y = clamp(a.y - uy * overlap, a.radius + 14, GRAPH_HEIGHT - a.radius - 14);
        b.x = clamp(b.x + ux * overlap, b.radius + 14, GRAPH_WIDTH - b.radius - 14);
        b.y = clamp(b.y + uy * overlap, b.radius + 14, GRAPH_HEIGHT - b.radius - 14);
        moved = true;
      }
    }
    if (!moved) break;
  }
  return resolved;
}

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3);
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
  const [hopDepth, setHopDepth] = useState(0); // 0 means show all
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [hoveredEdgeKey, setHoveredEdgeKey] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isPanning, setIsPanning] = useState(false);
  const [containerSize, setContainerSize] = useState({ width: GRAPH_WIDTH, height: GRAPH_HEIGHT });
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLElement | null>(null);
  const animRef = useRef<number>(0);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

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
  }, [documentFilter, graph, minWeight, searchQuery, hopDepth, selectedNodeId]);

  const layout = useMemo<GraphLayout | null>(() => {
    if (visibleGraph.nodes.length === 0) return null;

    const maxChunk = Math.max(...visibleGraph.nodes.map((node) => node.chunkCount), 1);
    const simNodes: ExplorerNode[] = visibleGraph.nodes.map((node) => ({
      ...node,
      radius: 18 + Math.sqrt(node.chunkCount / maxChunk) * 28,
      x: GRAPH_WIDTH / 2,
      y: GRAPH_HEIGHT / 2,
    }));
    const simLinks: SimLink[] = visibleGraph.edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      weight: edge.weight,
    }));

    const sim = forceSimulation(simNodes)
      .force(
        "link",
        forceLink<ExplorerNode, SimLink>(simLinks)
          .id((node) => node.id)
          .distance((link) => Math.max(80, 190 - link.weight * 100))
          .strength((link) => Math.min(0.88, 0.22 + link.weight)),
      )
      .force("charge", forceManyBody().strength(-360))
      .force("center", forceCenter(GRAPH_WIDTH / 2, GRAPH_HEIGHT / 2))
      .force("collide", forceCollide<ExplorerNode>().radius((node) => node.radius + 16))
      .stop();

    for (let i = 0; i < 260; i += 1) sim.tick();
    sim.stop();

    const clamped = simNodes.map((node) => ({
      ...node,
      x: clamp(node.x, node.radius + 18, GRAPH_WIDTH - node.radius - 18),
      y: clamp(node.y, node.radius + 18, GRAPH_HEIGHT - node.radius - 18),
    }));
    const nodes = resolveNodeOverlap(clamped);
    const nodeLookupMap = new Map(nodes.map((node) => [node.id, node]));
    const links = visibleGraph.edges.flatMap((edge) => {
      const sourceNode = nodeLookupMap.get(edge.source);
      const targetNode = nodeLookupMap.get(edge.target);
      return sourceNode && targetNode ? [{ ...edge, sourceNode, targetNode }] : [];
    });
    return { nodes, links };
  }, [visibleGraph]);

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

  /* ── Camera animation ─────────────────────────────────────────── */
  const animateCameraTo = useCallback((targetPanX: number, targetPanY: number, targetZoom: number) => {
    cancelAnimationFrame(animRef.current);
    const startPanX = panX;
    const startPanY = panY;
    const startZoom = zoom;
    const startTime = performance.now();
    function step(now: number) {
      const t = Math.min((now - startTime) / CAMERA_ANIM_MS, 1);
      const e = easeOutCubic(t);
      setPanX(startPanX + (targetPanX - startPanX) * e);
      setPanY(startPanY + (targetPanY - startPanY) * e);
      setZoom(startZoom + (targetZoom - startZoom) * e);
      if (t < 1) animRef.current = requestAnimationFrame(step);
    }
    animRef.current = requestAnimationFrame(step);
  }, [panX, panY, zoom]);

  function centerOnNode(node: ExplorerNode) {
    const targetZoom = Math.max(zoom, 1.2);
    const targetPanX = (containerSize.width / targetZoom) / 2 - node.x;
    const targetPanY = (containerSize.height / targetZoom) / 2 - node.y;
    animateCameraTo(targetPanX, targetPanY, targetZoom);
  }

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

  function resetView() {
    animateCameraTo(0, 0, 1);
  }

  function fitToView() {
    if (!layout) return;
    const pad = 60;
    const minX = Math.min(...layout.nodes.map((n) => n.x - n.radius)) - pad;
    const minY = Math.min(...layout.nodes.map((n) => n.y - n.radius)) - pad;
    const maxX = Math.max(...layout.nodes.map((n) => n.x + n.radius)) + pad;
    const maxY = Math.max(...layout.nodes.map((n) => n.y + n.radius)) + pad;
    const gW = maxX - minX;
    const gH = maxY - minY;
    // Fallback bounds
    if (gW < 10 || gH < 10) {
      animateCameraTo(0, 0, 1);
      return;
    }
    const targetZoom = clamp(Math.min(containerSize.width / gW, containerSize.height / gH) * 0.9, MIN_ZOOM, MAX_ZOOM);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    animateCameraTo((containerSize.width / targetZoom) / 2 - cx, (containerSize.height / targetZoom) / 2 - cy, targetZoom);
  }

  // Auto fit to view on initial layout
  useEffect(() => {
    if (layout && layout.nodes.length > 0) {
      // Use requestAnimationFrame to ensure containerSize is calculated
      const raf = requestAnimationFrame(() => {
        fitToView();
      });
      return () => cancelAnimationFrame(raf);
    }
  }, [layout]); // deliberately omitted containerSize to avoid re-triggering on resize

  function exportAsPng() {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svgData = new XMLSerializer().serializeToString(svgEl);
    const canvas = document.createElement("canvas");
    canvas.width = containerSize.width * 2;
    canvas.height = containerSize.height * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const link = document.createElement("a");
      link.download = "knowledge-graph.png";
      link.href = canvas.toDataURL("image/png");
      link.click();
    };
    img.src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svgData)))}`;
  }

  /* ── Keyboard neighbor navigation ────────────────────────────── */
  const handleNodeKeyDown = useCallback((e: React.KeyboardEvent, nodeId: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      selectNode(nodeId);
      return;
    }
    if (!layout) return;
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    const neighborIds = getNeighborIds(nodeId, visibleGraph.edges);
    if (neighborIds.size === 0) return;
    const currentNode = layout.nodes.find((n) => n.id === nodeId);
    if (!currentNode) return;
    const neighbors = layout.nodes.filter((n) => neighborIds.has(n.id));
    const scored = neighbors.map((n) => {
      const dx = n.x - currentNode.x;
      const dy = n.y - currentNode.y;
      let score = Infinity;
      if (e.key === "ArrowRight" && dx > 0) score = dx;
      if (e.key === "ArrowLeft" && dx < 0) score = -dx;
      if (e.key === "ArrowDown" && dy > 0) score = dy;
      if (e.key === "ArrowUp" && dy < 0) score = -dy;
      return { node: n, score };
    }).filter((s) => s.score < Infinity);
    if (scored.length === 0) return;
    scored.sort((a, b) => a.score - b.score);
    const target = scored[0].node;
    selectNode(target.id);
    const svg = svgRef.current;
    if (svg) {
      const el = svg.querySelector(`[data-node-id="${target.id}"]`) as HTMLElement | null;
      el?.focus();
    }
  }, [layout, visibleGraph.edges]);

  /* ── Escape fullscreen ───────────────────────────────────────── */
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setIsFullscreen(false); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  useEffect(() => {
    return () => cancelAnimationFrame(animRef.current);
  }, []);

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    if ((event.target as Element).closest(`.${styles.nodeButton}, .${styles.edgeHit}`)) return;
    setIsPanning(true);
    panStartRef.current = { x: event.clientX, y: event.clientY, panX, panY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!isPanning) return;
    setPanX(panStartRef.current.panX + (event.clientX - panStartRef.current.x) / zoom);
    setPanY(panStartRef.current.panY + (event.clientY - panStartRef.current.y) / zoom);
  }

  function handleWheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault();
    setZoom((current) => clamp(current * Math.pow(0.999, event.deltaY), MIN_ZOOM, MAX_ZOOM));
  }

  const selectedNeighborIds = new Set(
    incidentEdges.map((edge) => (selectedNodeId ? getOtherNodeId(edge, selectedNodeId) : "")),
  );
  const viewBox = `${-panX} ${-panY} ${containerSize.width / zoom} ${containerSize.height / zoom}`;
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
        <button className={styles.toolbarButton} onClick={fitToView} type="button">
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
        <section aria-label="Knowledge graph canvas" className={styles.canvasPanel}>
          {layout ? (
            <svg
              aria-label="Knowledge graph topic map"
              className={cn(styles.canvas, isPanning && styles.canvasPanning)}
              onDoubleClick={resetView}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={() => setIsPanning(false)}
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
                  const connections = incidentEdges.filter(e => e.source === node.id || e.target === node.id).length;
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

          {/* Minimap */}
          {layout && (
            <div 
              className={styles.minimap} 
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const x = (e.clientX - rect.left) / rect.width;
                const y = (e.clientY - rect.top) / rect.height;
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

          {/* Legend */}
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

function SummaryInspector({ summary }: { summary: ReturnType<typeof buildKnowledgeGraphSummary> }) {
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
        <div className={styles.hubBadge} style={{ marginTop: '16px' }}>
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

function NodeInspector({
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

function EdgeInspector({ edge }: { edge: ExplorerLink }) {
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
