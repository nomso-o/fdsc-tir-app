from typing import List
import logging

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

from ..azure_clients import cosmos_client
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CosmosDBChatMessageHistory(BaseChatMessageHistory):
    """
    Chat history backed by Cosmos DB.
    Uses max_messages to provide short-term memory for RAG.
    """

    def __init__(self, session_id: str, container_name: str = "chat_history", max_messages: int = 20):
        self.session_id = session_id
        self.max_messages = max_messages
        db = cosmos_client.get_database_client(settings.AZURE_COSMOSDB_NAME)
        self.container = db.get_container_client(container_name)

    @property
    def messages(self) -> List[BaseMessage]:
        query = """
        SELECT * FROM c
        WHERE c.session_id = @sid
        ORDER BY c._ts
        """
        items = list(
            self.container.query_items(
                query=query,
                parameters=[{"name": "@sid", "value": self.session_id}],
                enable_cross_partition_query=True,
            )
        )
        items = items[-self.max_messages :]
        dict_msgs = [item["message"] for item in items]
        return messages_from_dict(dict_msgs)

    def add_message(self, message: BaseMessage) -> None:
        doc = {
            "id": f"{self.session_id}-{message.type}-{message.id or ''}-{str(message.content)[:32]}",
            "session_id": self.session_id,
            "message": messages_to_dict([message])[0],
        }
        self.container.upsert_item(doc)

    def clear(self) -> None:
        query = "SELECT c.id FROM c WHERE c.session_id = @sid"
        items = list(
            self.container.query_items(
                query=query,
                parameters=[{"name": "@sid", "value": self.session_id}],
                enable_cross_partition_query=True,
            )
        )
        for item in items:
            self.container.delete_item(item["id"], partition_key=self.session_id)
