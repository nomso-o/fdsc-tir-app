from typing import Dict, Any, List
import logging

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
from ..services.storage_service import download_tir_file_text, list_tir_files, save_structured_results
from .chat_rag import _format_context_from_docs
from .retriever import get_fdsc_hybrid_retriever

logger = logging.getLogger(__name__)


def score_single_tir(tir_text: str, fdsc_context: str) -> Dict[str, Any]:
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


def score_tir_dataset(
    session_id: str,
    fdsc_index_name: str,
    dataset_blob_prefix: str,
) -> List[Dict[str, Any]]:
    """
    Iterate all TIR files in the dataset and score them.
    """
    retriever = get_fdsc_hybrid_retriever(fdsc_index_name)
    results = []

    tir_files = list_tir_files(dataset_blob_prefix)
    logger.info("Scoring %d TIR files for session %s", len(tir_files), session_id)
    for blob_name in tir_files:
        try:
            tir_text = download_tir_file_text(blob_name)
            docs = retriever.invoke(tir_text)
            fdsc_context = _format_context_from_docs(docs)

            single = score_single_tir(tir_text, fdsc_context)
            single["tir_blob_path"] = blob_name
            results.append(single)
        except Exception as ex:  # pylint: disable=broad-except
            logger.exception("Error scoring blob %s", blob_name)
            fallback = {
                "tir_blob_path": blob_name,
                "event_json": {"event_type": "Unknown", "reasoning": "Error scoring this TIR"},
                "reliability_json": {"reliability_category": "NA", "reasoning": "Error scoring this TIR"},
                "non_reliability_json": {"non_reliability_category": "NA", "reasoning": "Error scoring this TIR"},
                "other_event_json": {"other_event_category": "NA", "reasoning": "Error scoring this TIR"},
                "cause_json": {"cause_categories": ["Unknown"], "reasoning": "Error scoring this TIR"},
                "bit_bite_json": {"bit_bite_scores": ["Not Applicable"], "reasoning": "Error scoring this TIR"},
                "maintenance_json": {"maintenance_demand": "Not Applicable", "reasoning": "Error scoring this TIR"},
                "charge_json": {"chargeability_codes": ["NA"], "reasoning": "Error scoring this TIR"},
                "rationale": "Error scoring this TIR",
                "markdown_table": "| Field | Value |\n| --- | --- |\n| Status | Error scoring this TIR |",
                "technical_review": {"status": "fail", "issues": ["Error scoring this TIR"], "suggested_changes": ""},
                "alignment_review": {"status": "fail", "issues": ["Error scoring this TIR"], "suggested_changes": ""},
            }
            results.append(fallback)

    save_structured_results(session_id, results)
    return results
