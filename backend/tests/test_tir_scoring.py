import types
import unittest
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

try:
    from backend.app.rag.tir_scoring import ScoreSingleTIRConfig, score_single_tir, score_tir_dataset

    BACKEND_READY = True
except ModuleNotFoundError:
    BACKEND_READY = False
    ScoreSingleTIRConfig = None  # type: ignore
    score_single_tir = None  # type: ignore
    score_tir_dataset = None  # type: ignore


def _fake_agent_response(*_, **__):
    return {
        "event_json": {"event_type": "Reliability Failure"},
        "reliability_json": {"reliability_category": "CatA"},
        "non_reliability_json": {"non_reliability_category": "NA"},
        "other_event_json": {"other_event_category": "NA"},
        "cause_json": {"cause_categories": ["CauseA"]},
        "bit_bite_json": {"bit_bite_scores": ["Medium"]},
        "maintenance_json": {"maintenance_demand": "Low"},
        "charge_json": {"chargeability_codes": ["X1"]},
        "rationale": "ok",
        "markdown_table": "| Field | Value |",
        "technical_review": {"status": "pass", "issues": [], "suggested_changes": ""},
        "alignment_review": {"status": "pass", "issues": [], "suggested_changes": ""},
    }


@unittest.skipUnless(BACKEND_READY, "LangChain dependencies not installed")
class ScoreSingleVsBatchTest(unittest.TestCase):
    @patch("backend.app.rag.tir_scoring.upsert_structured_result")
    @patch("backend.app.rag.tir_scoring.list_tir_files")
    @patch("backend.app.rag.tir_scoring.download_tir_file_text", return_value="TIR TEXT")
    @patch("backend.app.rag.tir_scoring.get_fdsc_hybrid_retriever")
    @patch("backend.app.rag.tir_scoring._run_scoring_agents", side_effect=_fake_agent_response)
    def test_single_equals_batch(
        self,
        mock_run_agents: MagicMock,
        mock_get_retriever: MagicMock,
        mock_download: MagicMock,  # pylint: disable=unused-argument
        mock_list_files: MagicMock,
        mock_upsert: MagicMock,
    ):
        session_id = "session-test"
        fdsc_index = "fdsc-index"
        tir_blob = "dataset/sample_tir.txt"

        mock_list_files.return_value = [tir_blob]

        fake_retriever = MagicMock()
        fake_doc = types.SimpleNamespace(page_content="ctx", metadata={"id": "doc1", "blob_uri": "doc1"})
        fake_retriever.invoke.return_value = [fake_doc]
        mock_get_retriever.return_value = fake_retriever

        single_config = ScoreSingleTIRConfig(retriever=fake_retriever, persist_result=False)
        single_result = score_single_tir(session_id, fdsc_index, tir_blob, config=single_config)

        batch_results = score_tir_dataset(session_id, fdsc_index, "dataset", None)

        self.assertEqual(len(batch_results), 1)
        self.assertEqual(single_result, batch_results[0])

        mock_run_agents.assert_called()
        mock_upsert.assert_called_once_with(session_id, batch_results[0])


@unittest.skipUnless(BACKEND_READY, "LangChain dependencies not installed")
class RetrievalFilterTest(unittest.TestCase):
    @patch("backend.app.rag.tir_scoring.upsert_structured_result")
    @patch("backend.app.rag.tir_scoring.download_tir_file_text", return_value="TIR TEXT")
    def test_filter_blocks_other_docs(self, mock_download: MagicMock, mock_upsert: MagicMock):  # pylint: disable=unused-argument
        from backend.app.rag.tir_scoring import score_single_tir, ScoreSingleTIRConfig
        from langchain_core.documents import Document

        class StubRetriever:
            def invoke(self, query: str, doc_filter=None):  # pylint: disable=unused-argument
                return [
                    Document(
                        page_content="allowed",
                        metadata={"doc_id": "doc-123", "doc_namespace": "default", "retrieval_mode": "vector"},
                    ),
                    Document(
                        page_content="blocked",
                        metadata={"doc_id": "other-doc", "doc_namespace": "default", "retrieval_mode": "lexical"},
                    ),
                ]

        config = ScoreSingleTIRConfig(retriever=StubRetriever(), fdsc_doc_filter="doc-123", persist_result=False)
        result = score_single_tir("session", "fdsc-index", "tir.txt", config=config)
        self.assertEqual(result["retrieval_mode_used"], "vector")
        mock_upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
