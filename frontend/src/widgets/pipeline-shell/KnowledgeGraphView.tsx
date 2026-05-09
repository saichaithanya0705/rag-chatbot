import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import styles from "./knowledge-graph.module.css";

/* ─── Constants ──────────────────────────────────────────────────── */
const GRAPH_WIDTH = 900;
const GRAPH_HEIGHT = 450;
const TOOLTIP_WIDTH = 240;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.12;

/* ─── Types ──────────────────────────────────────────────────────── */
interface PositionedNode extends KnowledgeGraphNode {
  radius: number;
  x: number;
  y: number;
}

interface SimLink {
  weight: number;
  source: string | PositionedNode;
  target: string | PositionedNode;
}

interface ResolvedLink {
  source: PositionedNode;
  target: PositionedNode;
  weight: number;
}

interface GraphLayout {
  nodes: PositionedNode[];
  links: ResolvedLink[];
}

interface KnowledgeGraphViewProps {
  activeCollectionId: string;
  graph: KnowledgeGraph;
  onSelectNode: (collectionId: string) => void;
}

/* ─── Helpers ────────────────────────────────────────────────────── */
function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function resolveNodeOverlap(nodes: PositionedNode[]) {
  const resolved = nodes.map((node) => ({ ...node }));
  for (let iteration = 0; iteration < 36; iteration += 1) {
    let moved = false;
    for (let i = 0; i < resolved.length; i += 1) {
      for (let j = i + 1; j < resolved.length; j += 1) {
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

function truncateLabel(value: string) {
  return value.length > 18 ? `${value.slice(0, 15)}…` : value;
}

function buildFallbackEdges(nodes: KnowledgeGraphNode[]): KnowledgeGraphEdge[] {
  if (nodes.length < 2) return [];
  return nodes.slice(1).map((node, idx) => ({
    source: nodes[idx].id,
    target: node.id,
    weight: 0.25,
  }));
}

/** Interpolate between two hex colors */
function lerpColor(startHex: string, endHex: string, t: number): string {
  const parse = (hex: string) => {
    const h = hex.replace("#", "");
    return [
      Number.parseInt(h.slice(0, 2), 16),
      Number.parseInt(h.slice(2, 4), 16),
      Number.parseInt(h.slice(4, 6), 16),
    ];
  };
  const [r1, g1, b1] = parse(startHex);
  const [r2, g2, b2] = parse(endHex);
  const mix = clamp(t, 0, 1);
  return `rgb(${Math.round(r1 + (r2 - r1) * mix)}, ${Math.round(g1 + (g2 - g1) * mix)}, ${Math.round(b1 + (b2 - b1) * mix)})`;
}

/** Get neighbor node IDs for a given node */
function getNeighborIds(nodeId: string, links: ResolvedLink[]): Set<string> {
  const ids = new Set<string>();
  for (const link of links) {
    if (link.source.id === nodeId) ids.add(link.target.id);
    if (link.target.id === nodeId) ids.add(link.source.id);
  }
  return ids;
}

/* ─── Sub-components ─────────────────────────────────────────────── */
function EmptyGraphIllustration() {
  return (
    <svg aria-hidden="true" className={styles.emptyIllustration} fill="none" viewBox="0 0 120 120" width="120">
      <circle cx="60" cy="60" r="39" stroke="currentColor" strokeDasharray="4 6" strokeWidth="1.5" />
      <circle cx="44" cy="49" fill="currentColor" r="4.5" />
      <circle cx="77" cy="52" fill="currentColor" r="4.5" />
      <circle cx="63" cy="76" fill="currentColor" r="4.5" />
      <path d="M47.5 51L73.5 53.5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
      <path d="M46 53.5L59.5 72" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
      <path d="M74 55L65.5 71" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg className={styles.graphSearchIcon} fill="none" viewBox="0 0 16 16">
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeLinecap="round" strokeWidth="1.3" />
    </svg>
  );
}

/* ─── Main Component ─────────────────────────────────────────────── */
export function KnowledgeGraphView({ activeCollectionId, graph, onSelectNode }: KnowledgeGraphViewProps) {
  const [layout, setLayout] = useState<GraphLayout | null>(null);
  const [tooltipNodeId, setTooltipNodeId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Pan & Zoom state
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isPanning, setIsPanning] = useState(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const svgRef = useRef<SVGSVGElement | null>(null);

  const isTouchMode = typeof window !== "undefined" && window.matchMedia("(hover: none)").matches;

  /* ── Layout calculation ──────────────────────────────────────── */
  useEffect(() => {
    if (graph.nodes.length === 0) {
      setLayout(null);
      setTooltipNodeId(null);
      return;
    }

    const simNodes = graph.nodes.map((node) => ({
      ...node,
      radius: Math.min(50, Math.max(20, 20 + Math.log2(node.chunkCount + 1) * 6)),
      x: GRAPH_WIDTH / 2,
      y: GRAPH_HEIGHT / 2,
    }));
    const simLinks: SimLink[] = (graph.edges.length > 0 ? graph.edges : buildFallbackEdges(graph.nodes)).map(
      (edge) => ({ ...edge, source: edge.source, target: edge.target }),
    );

    const sim = forceSimulation(simNodes)
      .force(
        "link",
        forceLink<PositionedNode, SimLink>(simLinks)
          .id((n) => n.id)
          .distance((l: { weight?: number }) => Math.max(72, 180 - (l.weight ?? 0) * 96))
          .strength((l: { weight?: number }) => Math.min(0.92, 0.28 + (l.weight ?? 0))),
      )
      .force("charge", forceManyBody().strength(-320))
      .force("center", forceCenter(GRAPH_WIDTH / 2, GRAPH_HEIGHT / 2))
      .force("collide", forceCollide<PositionedNode>().radius((n) => n.radius + 20))
      .stop();

    for (let i = 0; i < 240; i += 1) sim.tick();

    const clamped = simNodes.map((n) => ({
      ...n,
      x: clamp(n.x ?? GRAPH_WIDTH / 2, n.radius + 14, GRAPH_WIDTH - n.radius - 14),
      y: clamp(n.y ?? GRAPH_HEIGHT / 2, n.radius + 14, GRAPH_HEIGHT - n.radius - 14),
    }));
    const resolved = resolveNodeOverlap(clamped);
    const lookup = new Map<string, PositionedNode>();
    resolved.forEach((n) => lookup.set(n.id, n));

    const resolvedLinks = simLinks.flatMap((link) => {
      const sId = typeof link.source === "string" ? link.source : link.source.id;
      const tId = typeof link.target === "string" ? link.target : link.target.id;
      const s = lookup.get(sId);
      const t = lookup.get(tId);
      if (!s || !t) return [];
      return [{ source: s, target: t, weight: link.weight }];
    });

    setLayout({ nodes: resolved, links: resolvedLinks });
    // Reset view when graph data changes
    setZoom(1);
    setPanX(0);
    setPanY(0);

    return () => { sim.stop(); };
  }, [graph]);

  /* ── Pan handlers ────────────────────────────────────────────── */
  const handlePointerDown = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(`.${styles.graphNode}`)) return;
    setIsPanning(true);
    panStartRef.current = { x: e.clientX, y: e.clientY, panX, panY };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }, [panX, panY]);

  const handlePointerMove = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if (!isPanning) return;
    const dx = e.clientX - panStartRef.current.x;
    const dy = e.clientY - panStartRef.current.y;
    setPanX(panStartRef.current.panX + dx / zoom);
    setPanY(panStartRef.current.panY + dy / zoom);
  }, [isPanning, zoom]);

  const handlePointerUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    // Use proportional scaling (pow 0.999) for perfectly smooth trackpad and mouse wheel zooming
    const factor = Math.pow(0.999, e.deltaY);
    setZoom((z) => clamp(z * factor, MIN_ZOOM, MAX_ZOOM));
  }, []);

  const resetView = useCallback(() => {
    setZoom(1);
    setPanX(0);
    setPanY(0);
  }, []);

  /* ── Keyboard nav between neighbors ──────────────────────────── */
  const handleNodeKeyDown = useCallback((e: React.KeyboardEvent, nodeId: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setTooltipNodeId(nodeId);
      return;
    }
    if (!layout) return;
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    const neighborIds = getNeighborIds(nodeId, layout.links);
    if (neighborIds.size === 0) return;
    const currentNode = layout.nodes.find((n) => n.id === nodeId);
    if (!currentNode) return;
    const neighbors = layout.nodes.filter((n) => neighborIds.has(n.id));
    // Pick closest neighbor in the arrow direction
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
    setTooltipNodeId(target.id);
    // Focus the hit area of the target node
    const svg = svgRef.current;
    if (svg) {
      const el = svg.querySelector(`[data-node-id="${target.id}"]`) as HTMLElement | null;
      el?.focus();
    }
  }, [layout]);

  /* ── Escape from fullscreen ──────────────────────────────────── */
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setIsFullscreen(false); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  /* ── Search filtering ────────────────────────────────────────── */
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const searchMatchIds = useMemo(() => {
    if (!normalizedSearch || !layout) return null;
    const ids = new Set<string>();
    layout.nodes.forEach((n) => {
      if (n.label.toLowerCase().includes(normalizedSearch)) ids.add(n.id);
    });
    return ids.size > 0 ? ids : null;
  }, [normalizedSearch, layout]);

  /* ── Derived data ────────────────────────────────────────────── */
  if (!layout) {
    return (
      <div className={styles.graphEmpty}>
        <EmptyGraphIllustration />
        <div className={styles.graphEmptyTitle}>Knowledge graph is waiting on clustered topics</div>
        <div className={styles.graphEmptyText}>
          Upload and index a few PDFs, then re-cluster to see topic relationships appear here.
        </div>
      </div>
    );
  }

  const minChunk = Math.min(...layout.nodes.map((n) => n.chunkCount));
  const maxChunk = Math.max(...layout.nodes.map((n) => n.chunkCount));
  const tooltipNode = layout.nodes.find((n) => n.id === tooltipNodeId) ?? null;
  const detailNode = tooltipNode ?? layout.nodes.find((n) => n.id === activeCollectionId) ?? null;

  // Nodes connected to hovered node (for edge highlight)
  const hoveredNeighborIds = tooltipNodeId ? getNeighborIds(tooltipNodeId, layout.links) : null;

  const renderedNodes = [...layout.nodes].sort((a, b) => {
    const ap = a.id === tooltipNodeId || a.id === activeCollectionId ? 1 : 0;
    const bp = b.id === tooltipNodeId || b.id === activeCollectionId ? 1 : 0;
    return ap !== bp ? ap - bp : b.radius - a.radius;
  });

  const selectableNodes = [...layout.nodes].sort((a, b) =>
    b.chunkCount !== a.chunkCount ? b.chunkCount - a.chunkCount : a.label.localeCompare(b.label),
  );

  const viewBox = `${-panX} ${-panY} ${GRAPH_WIDTH / zoom} ${GRAPH_HEIGHT / zoom}`;
  const zoomPct = `${Math.round(zoom * 100)}%`;

  return (
    <div className={cn(styles.graphShell, isFullscreen && styles.graphShellFullscreen)}>
      {/* ── Toolbar ───────────────────────────────────────────── */}
      <div className={styles.graphToolbar}>
        <div className={styles.graphSearchWrap}>
          <SearchIcon />
          <input
            className={styles.graphSearchInput}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search topics…"
            type="text"
            value={searchQuery}
          />
          {searchQuery && (
            <button className={styles.graphSearchClear} onClick={() => setSearchQuery("")} type="button">
              ×
            </button>
          )}
        </div>
        <div className={styles.graphToolbarSpacer} />
        <span className={styles.graphZoomLabel}>{zoomPct}</span>
        <button
          aria-label="Reset view"
          className={styles.graphToolbarBtn}
          onClick={resetView}
          title="Reset view"
          type="button"
        >
          <svg fill="none" height="14" viewBox="0 0 16 16" width="14">
            <path d="M2 8a6 6 0 1 1 1.76 4.24" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
            <path d="M2 12V8h4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
          </svg>
        </button>
        <button
          aria-label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
          className={cn(styles.graphToolbarBtn, isFullscreen && styles.graphToolbarBtnActive)}
          onClick={() => setIsFullscreen((f) => !f)}
          title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
          type="button"
        >
          {isFullscreen ? (
            <svg fill="none" height="14" viewBox="0 0 16 16" width="14">
              <path d="M5 1v4H1M11 1v4h4M5 15v-4H1M11 15v-4h4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
            </svg>
          ) : (
            <svg fill="none" height="14" viewBox="0 0 16 16" width="14">
              <path d="M1 5V1h4M15 5V1h-4M1 11v4h4M15 11v4h-4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
            </svg>
          )}
        </button>
      </div>

      {/* ── SVG Graph ────────────────────────────────────────── */}
      <svg
        ref={svgRef}
        aria-label="Knowledge graph"
        className={cn(
          styles.graphSvg,
          isPanning ? styles.graphSvgGrabbing : styles.graphSvgDefault,
        )}
        onDoubleClick={resetView}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        role="img"
        viewBox={viewBox}
      >
        {/* Edges */}
        <g>
          {layout.links.map((link) => {
            const key = `${link.source.id}-${link.target.id}`;
            const isHighlighted = tooltipNodeId != null && (link.source.id === tooltipNodeId || link.target.id === tooltipNodeId);
            const isDimmed = tooltipNodeId != null && !isHighlighted;
            return (
              <line
                className={cn(
                  styles.graphLink,
                  isHighlighted && styles.graphLinkHighlighted,
                  isDimmed && styles.graphLinkDimmed,
                )}
                key={key}
                strokeWidth={isHighlighted ? 2 + link.weight * 5 : 1 + link.weight * 4}
                x1={link.source.x}
                x2={link.target.x}
                y1={link.source.y}
                y2={link.target.y}
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {renderedNodes.map((node, idx) => {
            const labelLines = node.label.split(" · ").slice(0, 2).map(truncateLabel);
            const fillRatio = maxChunk === minChunk ? 0.3 : (node.chunkCount - minChunk) / (maxChunk - minChunk);
            // Gradient from warm neutral to accent purple
            const nodeFill = lerpColor("#f0ede4", "#c4bfef", fillRatio);

            const isNodeDimmed =
              (tooltipNodeId != null && node.id !== tooltipNodeId && !(hoveredNeighborIds?.has(node.id))) ||
              (searchMatchIds != null && !searchMatchIds.has(node.id));
            const isSearchMatch = searchMatchIds != null && searchMatchIds.has(node.id);

            return (
              <g
                className={cn(
                  styles.graphNode,
                  styles.graphNodeEnter,
                  node.id === activeCollectionId && styles.graphNodeActive,
                  isNodeDimmed && styles.graphNodeDimmed,
                  isSearchMatch && styles.graphNodeSearchMatch,
                )}
                key={node.id}
                onMouseEnter={() => setTooltipNodeId(node.id)}
                onMouseLeave={() => {
                  if (!isTouchMode) setTooltipNodeId((c) => (c === node.id ? null : c));
                }}
                style={{ animationDelay: `${idx * 40}ms` } as CSSProperties}
              >
                <title>{node.label}</title>
                <circle
                  aria-label={`${node.label}, ${node.documentCount} documents, ${node.chunkCount} chunks`}
                  aria-pressed={node.id === activeCollectionId}
                  className={styles.graphNodeHitArea}
                  cx={node.x}
                  cy={node.y}
                  data-node-id={node.id}
                  focusable="true"
                  onClick={() => setTooltipNodeId(node.id)}
                  onKeyDown={(e) => handleNodeKeyDown(e, node.id)}
                  r={node.radius + 4}
                  role="button"
                  tabIndex={0}
                />
                <circle
                  className={styles.graphNodeCircle}
                  cx={node.x}
                  cy={node.y}
                  r={node.radius}
                  style={{ "--node-fill": nodeFill } as CSSProperties}
                />
                <text className={styles.graphNodeText} textAnchor="middle" x={node.x} y={node.y - 5}>
                  {labelLines.map((line, i) => (
                    <tspan dy={i === 0 ? 0 : 14} key={`${node.id}-${line}`} x={node.x}>
                      {line}
                    </tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </g>

        {/* Tooltip */}
        {tooltipNode ? (
          <foreignObject
            height={100}
            pointerEvents="none"
            width={TOOLTIP_WIDTH}
            x={clamp(tooltipNode.x - TOOLTIP_WIDTH / 2, 8 - panX, GRAPH_WIDTH / zoom - TOOLTIP_WIDTH - 8 - panX)}
            y={clamp(
              tooltipNode.y - tooltipNode.radius - 100 - 12 < 8
                ? tooltipNode.y + tooltipNode.radius + 10
                : tooltipNode.y - tooltipNode.radius - 100 - 12,
              8,
              GRAPH_HEIGHT / zoom - 108,
            )}
          >
            <div className={styles.tooltip}>
              <div className={styles.tooltipTitle}>{tooltipNode.label}</div>
              <div className={styles.tooltipDivider} />
              <div className={styles.tooltipMeta}>
                <svg className={styles.tooltipMetaIcon} fill="none" viewBox="0 0 16 16">
                  <rect height="14" rx="1.5" stroke="currentColor" strokeWidth="1.2" width="10" x="3" y="1" />
                </svg>
                {tooltipNode.documentCount} linked documents
              </div>
              <div className={styles.tooltipMeta}>
                <svg className={styles.tooltipMetaIcon} fill="none" viewBox="0 0 16 16">
                  <rect height="4" rx="1" stroke="currentColor" strokeWidth="1" width="12" x="2" y="2" />
                  <rect height="4" rx="1" stroke="currentColor" strokeWidth="1" width="12" x="2" y="10" />
                </svg>
                {tooltipNode.chunkCount} indexed chunks
              </div>
              <div className={styles.tooltipMeta}>
                <svg className={styles.tooltipMetaIcon} fill="none" viewBox="0 0 16 16">
                  <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M8 2v2M8 12v2M2 8h2M12 8h2" stroke="currentColor" strokeLinecap="round" strokeWidth="1" />
                </svg>
                {getNeighborIds(tooltipNode.id, layout.links).size} connected topics
              </div>
            </div>
          </foreignObject>
        ) : null}
      </svg>

      {/* ── Legend ────────────────────────────────────────────── */}
      {layout.nodes.length >= 2 && (
        <div className={styles.graphLegend}>
          <span className={styles.graphLegendItem}>
            <span className={styles.legendSizeDemo}>
              <span className={cn(styles.legendDot, styles.legendDotSm)} />
              <span className={cn(styles.legendDot, styles.legendDotMd)} />
              <span className={cn(styles.legendDot, styles.legendDotLg)} />
            </span>
            Node size = chunk count
          </span>
          <span className={styles.graphLegendItem}>
            <span className={styles.legendGradient} />
            Color = data density
          </span>
        </div>
      )}

      {/* ── Node Browser (pills) ─────────────────────────────── */}
      <div className={styles.graphNodeBrowser}>
        {selectableNodes.map((node) => (
          <button
            className={cn(
              styles.graphNodePill,
              node.id === detailNode?.id && styles.graphNodePillActive,
            )}
            key={`pill-${node.id}`}
            onClick={() => setTooltipNodeId(node.id)}
            type="button"
          >
            <span className={styles.graphNodePillLabel}>{node.label}</span>
            <span className={styles.graphNodePillMeta}>{node.chunkCount} chunks</span>
          </button>
        ))}
      </div>

      {/* ── Meta Panel ───────────────────────────────────────── */}
      {detailNode ? (
        <div className={styles.graphMetaPanel}>
          <div className={styles.graphMetaCopy}>
            <div className={styles.graphMetaTitle}>{detailNode.label}</div>
            <div className={styles.graphMetaText}>
              {detailNode.documentCount} linked documents · {detailNode.chunkCount} indexed chunks
              {hoveredNeighborIds ? ` · ${hoveredNeighborIds.size} connections` : ""}
            </div>
          </div>
          <button
            className={styles.graphMetaAction}
            onClick={() => onSelectNode(detailNode.id)}
            type="button"
          >
            Open in chat
          </button>
        </div>
      ) : null}

      {/* ── Hint ─────────────────────────────────────────────── */}
      <div className={styles.graphHint}>
        Drag to pan · Scroll to zoom · Double-click to reset · Arrow keys navigate between connected nodes
      </div>
    </div>
  );
}
