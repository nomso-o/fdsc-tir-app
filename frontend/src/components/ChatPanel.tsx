import React, { useState } from "react";
import api from "../api/client";

interface ChatPanelProps {
  sessionId: string;
}

interface Citation {
  source_id?: string;
  page?: number;
  blob_uri?: string;
  snippet?: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

const ChatPanel: React.FC<ChatPanelProps> = ({ sessionId }) => {
  const [fdscIndexName, setFdscIndexName] = useState("fdsc-index");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg: ChatMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const resp = await api.post("/chat/message", {
        message: userMsg.content,
        session_id: sessionId,
        fdsc_index_name: fdscIndexName
      });
      const answer = resp.data.answer as string;
      const citations = resp.data.citations as Citation[];
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: answer,
        citations
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setError("Error contacting chat service. Please try again.");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Error: unable to get response." }
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-panel">
      <h2>Chat (FDSC RAG)</h2>
      <div className="chat-kb-selector">
        <label>FDSC Index:</label>
        <input
          value={fdscIndexName}
          onChange={(e) => setFdscIndexName(e.target.value)}
        />
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="chat-history">
        {messages.length === 0 && (
          <p className="empty-state">Ask a question about the FDSC to get started.</p>
        )}
        {messages.map((m, idx) => (
          <div key={idx} className={`chat-message ${m.role}`}>
            <div className="chat-role">{m.role === "user" ? "You" : "Assistant"}</div>
            <div className="chat-content">{m.content}</div>
            {m.citations && m.citations.length > 0 && (
              <div className="chat-citations">
                {m.citations.map((c, i) => (
                  <div key={i} className="citation-item">
                    <span>
                      {c.blob_uri ? (
                        <a href={c.blob_uri} target="_blank" rel="noreferrer">
                          Source {i + 1}
                        </a>
                      ) : (
                        <>Source {i + 1}</>
                      )}
                    </span>
                    {typeof c.page === "number" && <span> (p. {c.page})</span>}
                    {c.snippet && <p className="citation-snippet">{c.snippet}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="chat-input-row">
        <textarea
          placeholder="Ask about FDSC..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button onClick={sendMessage} disabled={loading}>
          {loading ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
};

export default ChatPanel;
