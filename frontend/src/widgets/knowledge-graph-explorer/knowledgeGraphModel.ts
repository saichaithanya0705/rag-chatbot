import type { KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "@/shared/api/types";

export interface KnowledgeGraphSummary {
  topicCount: number;
  relationshipCount: number;
  documentCount: number;
  chunkCount: number;
  strongestRelationshipWeight: number;
  averageWeight: number;
  isolatedNodeCount: number;
  mostConnectedNode: { label: string; connections: number } | null;
}

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function nodeMatchesQuery(node: KnowledgeGraphNode, query: string) {
  const normalized = normalize(query);
  if (!normalized) return true;
  const haystack = [
    node.label,
    ...node.keywords,
    ...node.sourceDocuments,
    ...node.pageKeys,
  ].join(" ").toLowerCase();
  return haystack.includes(normalized);
}

export function buildKnowledgeGraphSummary(graph: KnowledgeGraph): KnowledgeGraphSummary {
  const documents = new Set<string>();
  let chunkCount = 0;

  for (const node of graph.nodes) {
    chunkCount += node.chunkCount;
    node.sourceDocuments.forEach((document) => documents.add(document));
  }

  const connectionCounts = new Map<string, number>();
  for (const edge of graph.edges) {
    connectionCounts.set(edge.source, (connectionCounts.get(edge.source) ?? 0) + 1);
    connectionCounts.set(edge.target, (connectionCounts.get(edge.target) ?? 0) + 1);
  }

  let mostConnectedNode: { label: string; connections: number } | null = null;
  let isolatedNodeCount = 0;
  for (const node of graph.nodes) {
    const connections = connectionCounts.get(node.id) ?? 0;
    if (connections === 0) isolatedNodeCount++;
    if (!mostConnectedNode || connections > mostConnectedNode.connections) {
      mostConnectedNode = { label: node.label, connections };
    }
  }

  const averageWeight = graph.edges.length > 0
    ? graph.edges.reduce((sum, edge) => sum + edge.weight, 0) / graph.edges.length
    : 0;

  return {
    topicCount: graph.nodes.length,
    relationshipCount: graph.edges.length,
    documentCount: documents.size,
    chunkCount,
    strongestRelationshipWeight: graph.edges.reduce((max, edge) => Math.max(max, edge.weight), 0),
    averageWeight,
    isolatedNodeCount,
    mostConnectedNode,
  };
}

export function filterKnowledgeGraph(graph: KnowledgeGraph, query: string): KnowledgeGraph {
  const normalized = normalize(query);
  if (!normalized) return graph;

  const nodes = graph.nodes.filter((node) => nodeMatchesQuery(node, normalized));
  const nodeIds = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)),
  };
}

export function getNodeDocuments(node: KnowledgeGraphNode | null) {
  return node?.sourceDocuments ?? [];
}

export function getNodeKeywords(node: KnowledgeGraphNode | null) {
  return node?.keywords ?? [];
}

export function getIncidentEdges(graph: KnowledgeGraph, nodeId: string | null) {
  if (!nodeId) return [];
  return graph.edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);
}

export function getOtherNodeId(edge: KnowledgeGraphEdge, nodeId: string) {
  return edge.source === nodeId ? edge.target : edge.source;
}

export function describeRelationshipReason(edge: KnowledgeGraphEdge | null) {
  return edge?.reason?.trim() || "Related by the knowledge graph scoring model.";
}

/** Get neighbor node IDs for a given node from an edge list */
export function getNeighborIds(nodeId: string, edges: KnowledgeGraphEdge[]): Set<string> {
  const ids = new Set<string>();
  for (const edge of edges) {
    if (edge.source === nodeId) ids.add(edge.target);
    if (edge.target === nodeId) ids.add(edge.source);
  }
  return ids;
}

/** BFS to find all nodes within N hops of a starting node */
export function getNodesWithinHops(
  graph: KnowledgeGraph,
  startNodeId: string,
  maxHops: number,
): Set<string> {
  const visited = new Set<string>();
  const queue: Array<{ id: string; depth: number }> = [{ id: startNodeId, depth: 0 }];

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (visited.has(current.id)) continue;
    visited.add(current.id);

    if (current.depth < maxHops) {
      for (const edge of graph.edges) {
        if (edge.source === current.id && !visited.has(edge.target)) {
          queue.push({ id: edge.target, depth: current.depth + 1 });
        }
        if (edge.target === current.id && !visited.has(edge.source)) {
          queue.push({ id: edge.source, depth: current.depth + 1 });
        }
      }
    }
  }

  return visited;
}
