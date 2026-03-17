from typing import Dict, Any, List, Optional
import logging
import time
from dataclasses import dataclass

from .tir_agents import (
    event_category_runnable,
    reliability_runnable,
    non_reliability_runnable,
    other_event_runnable,
    cause_runnable,
    bit_bite_runnable,
    maintenance_runnable,
    charge_runnable,
    assembler_runnable,
    technical_review_runnable,
    alignment_review_runnable,
    revision_runnable,
)
from ..services.storage_service import (
    download_tir_file_text,
    list_tir_files,
    upsert_structured_result,
)
from .chat_rag import _format_context_from_docs
from .retriever import FDSCHybridRetriever, get_fdsc_hybrid_retriever

logger = logging.getLogger(__name__)


@dataclass
class ScoreSingleTIRConfig:
    """
    Optional configuration for scoring a single TIR.

    Attributes:
        retriever: Optional retriever instance to reuse (avoids recreating per TIR).
        fdsc_doc_filter: Limit retrieved FDSC snippets to doc IDs/blob URIs starting with this value.
        persist_result: Whether to write results back to Cosmos immediately.
    """

    retriever: Optional[FDSCHybridRetriever] = None
    fdsc_doc_filter: Optional[str] = None
    persist_result: bool = True


def _run_scoring_agents(tir_text: str, fdsc_context: str) -> Dict[str, Any]:
    try:
        event_json = event_category_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})
        event_type = event_json.get("event_type", "Unknown")

        reliability_json = {"reliability_category": "NA"}
        non_reliability_json = {"non_reliability_category": "NA"}
        other_event_json = {"other_event_category": "NA"}
        bit_bite_json = {"bit_bite_scores": ["Not Applicable"]}
        maintenance_json = {"maintenance_demand": "Not Applicable"}
        charge_json = {"chargeability_codes": ["NA"]}

        if event_type == "Reliability Failure":
            reliability_json = reliability_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})
        elif event_type == "Non-Reliability Failure":
            non_reliability_json = non_reliability_runnable.invoke(
                {"tir_text": tir_text, "fdsc_context": fdsc_context}
            )
        elif event_type == "Other Event or Failure":
            other_event_json = other_event_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})

        cause_json = cause_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})
        bit_bite_json = bit_bite_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})
        maintenance_json = maintenance_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})
        charge_json = charge_runnable.invoke({"tir_text": tir_text, "fdsc_context": fdsc_context})

        assembled_json = assembler_runnable.invoke(
            {
                "tir_text": tir_text,
                "fdsc_context": fdsc_context,
                "event_category_json": event_json,
                "reliability_json": reliability_json,
                "non_reliability_json": non_reliability_json,
                "other_event_json": other_event_json,
                "cause_json": cause_json,
                "bit_bite_json": bit_bite_json,
                "maintenance_json": maintenance_json,
                "charge_json": charge_json,
            }
        )

        technical_review = technical_review_runnable.invoke(
            {"tir_text": tir_text, "fdsc_context": fdsc_context, "assembled_json": assembled_json}
        )

        alignment_review = alignment_review_runnable.invoke(
            {"tir_text": tir_text, "fdsc_context": fdsc_context, "assembled_json": assembled_json}
        )

        if technical_review.get("status") == "pass" and alignment_review.get("status") == "pass":
            final_rationale = assembled_json.get("rationale", "")
            final_table = assembled_json.get("markdown_table", "")
        else:
            revision_json = revision_runnable.invoke(
                {
                    "tir_text": tir_text,
                    "fdsc_context": fdsc_context,
                    "assembled_json": assembled_json,
                    "technical_review_json": technical_review,
                    "alignment_review_json": alignment_review,
                }
            )
            final_rationale = revision_json.get("final_rationale", assembled_json.get("rationale", ""))
            final_table = revision_json.get("final_markdown_table", assembled_json.get("markdown_table", ""))

        return {
            "event_json": event_json,
            "reliability_json": reliability_json,
            "non_reliability_json": non_reliability_json,
            "other_event_json": other_event_json,
            "cause_json": cause_json,
            "bit_bite_json": bit_bite_json,
            "maintenance_json": maintenance_json,
            "charge_json": charge_json,
            "rationale": final_rationale,
            "markdown_table": final_table,
            "technical_review": technical_review,
            "alignment_review": alignment_review,
        }
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Error scoring single TIR")
        fallback_message = "Error scoring this TIR"
        return {
            "event_json": {"event_type": "Unknown", "reasoning": fallback_message},
            "reliability_json": {"reliability_category": "NA", "reasoning": fallback_message},
            "non_reliability_json": {"non_reliability_category": "NA", "reasoning": fallback_message},
            "other_event_json": {"other_event_category": "NA", "reasoning": fallback_message},
            "cause_json": {"cause_categories": ["Unknown"], "reasoning": fallback_message},
            "bit_bite_json": {"bit_bite_scores": ["Not Applicable"], "reasoning": fallback_message},
            "maintenance_json": {"maintenance_demand": "Not Applicable", "reasoning": fallback_message},
            "charge_json": {"chargeability_codes": ["NA"], "reasoning": fallback_message},
            "rationale": fallback_message,
            "markdown_table": "| Field | Value |\n| --- | --- |\n| Status | Error scoring this TIR |",
            "technical_review": {"status": "fail", "issues": [fallback_message], "suggested_changes": ""},
            "alignment_review": {"status": "fail", "issues": [fallback_message], "suggested_changes": ""},
        }


def _build_fallback_result(tir_blob_path: str, reason: str) -> Dict[str, Any]:
    dataset_prefix = tir_blob_path.rsplit("/", 1)[0] if "/" in tir_blob_path else tir_blob_path
    return {
        "tir_id": f"tir::{tir_blob_path}",
        "dataset_prefix": dataset_prefix,
        "tir_blob_path": tir_blob_path,
        "event_json": {"event_type": "Unknown", "reasoning": reason},
        "reliability_json": {"reliability_category": "NA", "reasoning": reason},
        "non_reliability_json": {"non_reliability_category": "NA", "reasoning": reason},
        "other_event_json": {"other_event_category": "NA", "reasoning": reason},
        "cause_json": {"cause_categories": ["Unknown"], "reasoning": reason},
        "bit_bite_json": {"bit_bite_scores": ["Not Applicable"], "reasoning": reason},
        "maintenance_json": {"maintenance_demand": "Not Applicable", "reasoning": reason},
        "charge_json": {"chargeability_codes": ["NA"], "reasoning": reason},
        "rationale": reason,
        "markdown_table": "| Field | Value |\n| --- | --- |\n| Status | %s |" % reason,
        "technical_review": {"status": "fail", "issues": [reason], "suggested_changes": ""},
        "alignment_review": {"status": "fail", "issues": [reason], "suggested_changes": ""},
    }


def _filter_fdsc_docs(docs, doc_filter: Optional[str]):
    if not doc_filter:
        return docs
    expected = doc_filter.lower()
    filtered = []
    for doc in docs:
        doc_id = str(doc.metadata.get("doc_id", "") or "").lower()
        if doc_id == expected:
            filtered.append(doc)
    return filtered


def score_single_tir(
    session_id: str,
    fdsc_index_name: str,
    tir_blob_path: str,
    config: Optional[ScoreSingleTIRConfig] = None,
) -> Dict[str, Any]:
    """
    Score a single TIR document end-to-end (load, retrieve, score, persist).
    """
    cfg = config or ScoreSingleTIRConfig()
    retriever = cfg.retriever or get_fdsc_hybrid_retriever(fdsc_index_name)

    start_time = time.perf_counter()
    logger.info(
        "Starting TIR scoring",
        extra={
            "session_id": session_id,
            "tir_blob_path": tir_blob_path,
            "fdsc_index": fdsc_index_name,
            "fdsc_doc_filter": cfg.fdsc_doc_filter,
        },
    )

    try:
        tir_text = download_tir_file_text(tir_blob_path)
        docs = retriever.invoke(tir_text, doc_filter=cfg.fdsc_doc_filter)
        if cfg.fdsc_doc_filter:
            docs = _filter_fdsc_docs(docs, cfg.fdsc_doc_filter)
        logger.info(
            "Retrieved %d FDSC docs for %s",
            len(docs),
            tir_blob_path,
            extra={"fdsc_doc_filter": cfg.fdsc_doc_filter},
        )
        fdsc_context = _format_context_from_docs(docs)

        single = _run_scoring_agents(tir_text, fdsc_context)
        retrieval_mode = "unknown"
        if docs:
            first_mode = docs[0].metadata.get("retrieval_mode")
            if first_mode:
                retrieval_mode = first_mode
        single["retrieval_mode_used"] = retrieval_mode
        single["fdsc_doc_filter"] = cfg.fdsc_doc_filter or ""
        single["tir_id"] = f"tir::{tir_blob_path}"
        single["dataset_prefix"] = tir_blob_path.rsplit("/", 1)[0] if "/" in tir_blob_path else tir_blob_path
        single["tir_blob_path"] = tir_blob_path
        logger.info(
            "TIR retrieval summary",
            extra={
                "session_id": session_id,
                "tir_blob_path": tir_blob_path,
                "fdsc_doc_filter": cfg.fdsc_doc_filter,
                "retrieved_doc_count": len(docs),
                "retrieval_mode_used": retrieval_mode,
            },
        )
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Error scoring TIR %s", tir_blob_path)
        single = _build_fallback_result(tir_blob_path, "Error scoring this TIR")
        if cfg.persist_result:
            upsert_structured_result(session_id, single)
        elapsed = time.perf_counter() - start_time
        logger.info(
            "Completed TIR scoring with errors",
            extra={"session_id": session_id, "tir_blob_path": tir_blob_path, "elapsed": f"{elapsed:.2f}s"},
        )
        return single

    if cfg.persist_result:
        upsert_structured_result(session_id, single)
        logger.info(
            "Persisted TIR score",
            extra={"session_id": session_id, "tir_blob_path": tir_blob_path},
        )

    elapsed = time.perf_counter() - start_time
    logger.info(
        "Completed TIR scoring",
        extra={"session_id": session_id, "tir_blob_path": tir_blob_path, "elapsed": f"{elapsed:.2f}s"},
    )
    return single


def score_tir_dataset(
    session_id: str,
    fdsc_index_name: str,
    dataset_blob_prefix: str,
    fdsc_doc_filter: Optional[str] = None,
    tir_blob_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Iterate all TIR files in the dataset and score them via the single-TIR primitive.
    Optionally restrict retrieval to a specific FDSC document id.
    """
    retriever = get_fdsc_hybrid_retriever(fdsc_index_name)
    results = []

    tir_files = list_tir_files(dataset_blob_prefix)
    if tir_blob_path:
        tir_files = [name for name in tir_files if name == tir_blob_path]
    logger.info("Scoring %d TIR files for session %s", len(tir_files), session_id)
    cfg = ScoreSingleTIRConfig(retriever=retriever, persist_result=True, fdsc_doc_filter=fdsc_doc_filter)
    for blob_name in tir_files:
        result = score_single_tir(
            session_id=session_id,
            fdsc_index_name=fdsc_index_name,
            tir_blob_path=blob_name,
            config=cfg,
        )
        results.append(result)
    return results
