import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from "d3-force";
import type { KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "@/shared/api/types";

export const GRAPH_WIDTH = 1040;
export const GRAPH_HEIGHT = 620;
export const MIN_ZOOM = 0.3;
export const MAX_ZOOM = 3.5;
export const CAMERA_ANIM_MS = 380;

export interface ExplorerNode extends KnowledgeGraphNode {
  radius: number;
  x: number;
  y: number;
}

interface SimLink {
  source: string | ExplorerNode;
  target: string | ExplorerNode;
  weight: number;
}

export interface ExplorerLink extends KnowledgeGraphEdge {
  sourceNode: ExplorerNode;
  targetNode: ExplorerNode;
}

export interface GraphLayout {
  nodes: ExplorerNode[];
  links: ExplorerLink[];
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function edgeKey(edge: Pick<KnowledgeGraphEdge, "source" | "target">) {
  return [edge.source, edge.target].sort().join("::");
}

export function formatPercent(value: number | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

export function uniqueDocuments(graph: KnowledgeGraph) {
  const documents = new Set<string>();
  graph.nodes.forEach((node) => node.sourceDocuments.forEach((document) => documents.add(document)));
  return [...documents].sort((a, b) => a.localeCompare(b));
}

export function compactPageLabel(pageKey: string) {
  const [document, page] = pageKey.split(":");
  return page ? `${document}, p. ${page}` : pageKey;
}

export function lerpColor(startHex: string, endHex: string, t: number): string {
  const parse = (hex: string) => {
    const h = hex.replace("#", "");
    return [Number.parseInt(h.slice(0, 2), 16), Number.parseInt(h.slice(2, 4), 16), Number.parseInt(h.slice(4, 6), 16)];
  };
  const [r1, g1, b1] = parse(startHex);
  const [r2, g2, b2] = parse(endHex);
  const m = clamp(t, 0, 1);
  return `rgb(${Math.round(r1 + (r2 - r1) * m)}, ${Math.round(g1 + (g2 - g1) * m)}, ${Math.round(b1 + (b2 - b1) * m)})`;
}

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

export function buildGraphLayout(visibleGraph: KnowledgeGraph): GraphLayout | null {
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
}
