from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnableWithMessageHistory
from langchain_core.output_parsers import StrOutputParser

from ..azure_clients import llm
from .retriever import get_fdsc_hybrid_retriever
from .history import CosmosDBChatMessageHistory


# ---- Query refine prompt ----
_query_refine_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a precise assistant that rewrites user questions into standalone, "
            "clear queries using the Failure Definition and Scoring Criteria (FDSC) context. "
            "Use the chat history only to remove ambiguity, not to add new information.",
        ),
        MessagesPlaceholder("chat_history"),
        (
            "human",
            "User question:\n{question}\n\n"
            "Rewrite the question as a standalone, context-independent query that would be "
            "understandable to someone who has not seen the previous messages.\n\n"
            "Refined question ONLY:",
        ),
    ]
)

_query_refine_chain = _query_refine_prompt | llm | StrOutputParser()


def _add_refined_question(inputs: Dict[str, Any]) -> Dict[str, Any]:
    refined = _query_refine_chain.invoke(
        {"question": inputs["question"], "chat_history": inputs.get("chat_history", [])}
    )
    return {**inputs, "refined_question": refined}


def _format_context_from_docs(docs) -> str:
    return "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(docs))


def _add_docs_and_context(retriever):
    def _inner(inputs: Dict[str, Any]) -> Dict[str, Any]:
        refined_q = inputs["refined_question"]
        docs = retriever.invoke(refined_q)
        ctx = _format_context_from_docs(docs)
        return {**inputs, "documents": docs, "context": ctx}

    return RunnableLambda(_inner)


# ---- Answer prompt ----
_answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a precise expert Reliability Test Engineer/Analyst AI assistant. "
            "Answer ONLY from the provided FDSC context. If the answer is not in the context, say you don't know.\n"
            "Provide clear, concise answers and reference source snippet numbers when relevant.",
        ),
        MessagesPlaceholder("chat_history"),
        (
            "human",
            "Original user question:\n{question}\n\n"
            "Refined question:\n{refined_question}\n\n"
            "FDSC Context snippets (numbered):\n{context}\n\n"
            "Using ONLY the context snippets above, answer the refined question. "
            "If the answer is not contained in the context, respond with "
            "\"I don't know based on the FDSC provided.\"",
        ),
    ]
)

_answer_chain = _answer_prompt | llm


def build_fdsc_chat_runnable(index_name: str) -> RunnableWithMessageHistory:
    retriever = get_fdsc_hybrid_retriever(index_name)

    add_refined_runnable = RunnableLambda(_add_refined_question)
    add_docs_runnable = _add_docs_and_context(retriever)

    def _answer_only(inputs: Dict[str, Any]):
        return _answer_chain.invoke(
            {
                "question": inputs["question"],
                "refined_question": inputs["refined_question"],
                "chat_history": inputs.get("chat_history", []),
                "context": inputs["context"],
            }
        )

    answer_runnable = RunnableLambda(_answer_only)

    qa_with_sources = (
        add_refined_runnable
        | add_docs_runnable
        | RunnableParallel(
            answer=answer_runnable,
            source_documents=RunnableLambda(lambda x: x["documents"]),
        )
    )

    def get_history(session_id: str) -> CosmosDBChatMessageHistory:
        return CosmosDBChatMessageHistory(session_id=session_id)

    chat_runnable = RunnableWithMessageHistory(
        qa_with_sources,
        get_history,
        input_messages_key="question",
        history_messages_key="chat_history",
    )
    return chat_runnable
