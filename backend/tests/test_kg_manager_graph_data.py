from __future__ import annotations

import unittest

from app.services.kg_manager import KgManager, TopicNodeRecord


class KgManagerGraphDataTest(unittest.TestCase):
    def test_graph_data_exposes_node_and_edge_evidence(self) -> None:
        with self.subTest("build graph"):
            temp_dir = self.enterContext(__import__("tempfile").TemporaryDirectory())
            manager = KgManager(__import__("pathlib").Path(temp_dir) / "kg.pkl")
            manager.rebuild(
                "user-a",
                [
                    TopicNodeRecord(
                        collection_id="topic__scheduling",
                        display_name="CPU Scheduling",
                        centroid=[1.0, 0.0],
                        chunk_ids=["doc-1:0", "doc-1:1"],
                        pdf_sources=["OS Notes.pdf"],
                        keyword_summary=["round robin", "fcfs"],
                        page_keys=["OS Notes.pdf:1", "OS Notes.pdf:2"],
                    ),
                    TopicNodeRecord(
                        collection_id="topic__deadlocks",
                        display_name="Deadlocks",
                        centroid=[1.0, 0.0],
                        chunk_ids=["doc-1:2", "doc-1:3", "doc-1:4"],
                        pdf_sources=["OS Notes.pdf"],
                        keyword_summary=["deadlock", "wait graph"],
                        page_keys=["OS Notes.pdf:2", "OS Notes.pdf:3"],
                    ),
                ],
            )

        graph = manager.graph_data("user-a")

        self.assertEqual(
            graph["nodes"],
            [
                {
                    "id": "topic__scheduling",
                    "label": "CPU Scheduling",
                    "chunkCount": 2,
                    "documentCount": 1,
                    "keywords": ["round robin", "fcfs"],
                    "sourceDocuments": ["OS Notes.pdf"],
                    "pageKeys": ["OS Notes.pdf:1", "OS Notes.pdf:2"],
                },
                {
                    "id": "topic__deadlocks",
                    "label": "Deadlocks",
                    "chunkCount": 3,
                    "documentCount": 1,
                    "keywords": ["deadlock", "wait graph"],
                    "sourceDocuments": ["OS Notes.pdf"],
                    "pageKeys": ["OS Notes.pdf:2", "OS Notes.pdf:3"],
                },
            ],
        )

        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual(edge["source"], "topic__deadlocks")
        self.assertEqual(edge["target"], "topic__scheduling")
        self.assertAlmostEqual(edge["weight"], 0.825)
        self.assertAlmostEqual(edge["semanticScore"], 1.0)
        self.assertAlmostEqual(edge["pageOverlapScore"], 0.5)
        self.assertAlmostEqual(edge["documentOverlapScore"], 1.0)
        self.assertEqual(edge["sharedPages"], ["OS Notes.pdf:2"])
        self.assertEqual(edge["sharedDocuments"], ["OS Notes.pdf"])
        self.assertIn("1 shared page", edge["reason"])
        self.assertIn("1 shared document", edge["reason"])


if __name__ == "__main__":
    unittest.main()
