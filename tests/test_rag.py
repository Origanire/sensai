# Ces tests vérifient le découpage, le stockage et la recherche documentaire.

import unittest

from src.core.ingestion import chunk_markdown, chunk_text
from src.core.search import NO_DOCUMENT, ask_documents, search
from src.core.storage import DOCUMENTS, STREAMS, count_chunks, init_db, list_sources, save_chunks
from tests.fakes import FakeClient


class ChunkingTest(unittest.TestCase):
    def test_chunks_respect_size_and_do_not_cut_words(self):
        text = " ".join(f"mot{i}" for i in range(300))
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        words = set(text.split())
        for chunk in chunks:
            self.assertTrue(set(chunk.split()) <= words, chunk)

    def test_chunks_cover_the_whole_text(self):
        text = "abc " * 200
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        self.assertEqual(chunks[-1].split()[-1], "abc")

    def test_markdown_is_split_by_section_with_heading_path(self):
        text = "# FAQ\nintro\n## Setup\nRTX 4070\n## Règles\npas de spoil"
        chunks = chunk_markdown(text)
        self.assertEqual(chunks, ["FAQ\nintro", "FAQ > Setup\nRTX 4070", "FAQ > Règles\npas de spoil"])


class StorageAndSearchTest(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        save_chunks(self.conn, "faq.md", [
            {"text": "planning lundi", "embedding": [1.0, 0.0, 0.0]},
            {"text": "setup rtx", "embedding": [0.0, 1.0, 0.0]},
        ])
        save_chunks(self.conn, "stream1.json", [{"text": "stream passé", "embedding": [1.0, 0.0, 0.0]}],
                    collection=STREAMS)
        self.client = FakeClient(vectors={"planning": [0.9, 0.1, 0.0]})

    def test_reingesting_a_source_replaces_its_chunks(self):
        save_chunks(self.conn, "faq.md", [{"text": "nouveau", "embedding": [1.0, 0.0, 0.0]}])
        self.assertEqual(list_sources(self.conn), [("faq.md", 1)])

    def test_collections_are_separated(self):
        self.assertEqual(count_chunks(self.conn, DOCUMENTS), 2)
        self.assertEqual(count_chunks(self.conn, STREAMS), 1)
        results = search("planning ?", self.client, self.conn, top_k=5)
        self.assertNotIn("stream passé", [chunk["text"] for _, chunk in results])

    def test_results_are_sorted_and_filtered_by_min_score(self):
        results = search("planning ?", self.client, self.conn, top_k=5, min_score=0.5)
        self.assertEqual([chunk["text"] for _, chunk in results], ["planning lundi"])

    def test_no_relevant_chunk_means_no_model_call(self):
        client = FakeClient(texts=["ne doit pas servir"])
        settings = {"top_k": 3, "min_score": 0.5}
        self.assertEqual(ask_documents("météo ?", client, self.conn, settings), NO_DOCUMENT)
        self.assertEqual(client.requests, [])


if __name__ == "__main__":
    unittest.main()
