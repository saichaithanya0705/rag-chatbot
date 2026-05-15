import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildKnowledgeGraphSummary,
  describeRelationshipReason,
  filterKnowledgeGraph,
} from "../src/widgets/knowledge-graph-explorer/knowledgeGraphModel";
import type { KnowledgeGraph } from "../src/shared/api/types";

const graph: KnowledgeGraph = {
  nodes: [
    {
      id: "topic__scheduling",
      label: "CPU Scheduling",
      chunkCount: 8,
      documentCount: 2,
      keywords: ["round robin", "fcfs"],
      sourceDocuments: ["OS Notes.pdf", "Exam Guide.pdf"],
      pageKeys: ["OS Notes.pdf:2", "Exam Guide.pdf:4"],
    },
    {
      id: "topic__deadlocks",
      label: "Deadlocks",
      chunkCount: 4,
      documentCount: 1,
      keywords: ["wait graph"],
      sourceDocuments: ["OS Notes.pdf"],
      pageKeys: ["OS Notes.pdf:3"],
    },
  ],
  edges: [
    {
      source: "topic__scheduling",
      target: "topic__deadlocks",
      weight: 0.82,
      directed: false,
      semanticScore: 0.9,
      pageOverlapScore: 0.5,
      documentOverlapScore: 1,
      sharedPages: ["OS Notes.pdf:3"],
      sharedDocuments: ["OS Notes.pdf"],
      reason: "Strong semantic similarity; 1 shared page; 1 shared document.",
    },
  ],
};

test("summarizes graph evidence for the dedicated explorer shell", () => {
  assert.deepEqual(buildKnowledgeGraphSummary(graph), {
    topicCount: 2,
    relationshipCount: 1,
    documentCount: 2,
    chunkCount: 12,
    strongestRelationshipWeight: 0.82,
    averageWeight: 0.82,
    isolatedNodeCount: 0,
    mostConnectedNode: {
      label: "CPU Scheduling",
      connections: 1,
    },
  });
});

test("filters nodes by topic labels, keywords, and source documents", () => {
  assert.deepEqual(filterKnowledgeGraph(graph, "wait").nodes.map((node) => node.id), ["topic__deadlocks"]);
  assert.deepEqual(filterKnowledgeGraph(graph, "exam").nodes.map((node) => node.id), ["topic__scheduling"]);
  assert.deepEqual(filterKnowledgeGraph(graph, "").edges.length, 1);
});

test("formats relationship explanations from backend evidence", () => {
  assert.equal(
    describeRelationshipReason(graph.edges[0]),
    "Strong semantic similarity; 1 shared page; 1 shared document.",
  );
  assert.equal(
    describeRelationshipReason({ source: "a", target: "b", weight: 0.4 }),
    "Related by the knowledge graph scoring model.",
  );
});
