import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { KnowledgeGraph, KnowledgeGraphEdge } from "@/shared/api/types";
import { edgeKey } from "./knowledgeGraphExplorerShared";

export function useGraphSelection(graph: KnowledgeGraph) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [hoveredEdgeKey, setHoveredEdgeKey] = useState<string | null>(null);

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

  function selectNode(nodeId: string) {
    setSelectedNodeId(nodeId);
    setSelectedEdgeKey(null);
    setSearchParams({ topic: nodeId });
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

  return {
    selectedNodeId,
    setSelectedNodeId,
    selectedEdgeKey,
    setSelectedEdgeKey,
    hoveredEdgeKey,
    setHoveredEdgeKey,
    selectNode,
    selectEdge,
    clearSelection,
  };
}
