import React, { useState } from "react";
import api from "../api/client";
import ExportButtons from "./ExportButtons";
import ThinkingDrawer from "./ThinkingDrawer";

interface TIRAnalysisPanelProps {
  sessionId: string;
}

interface TIRSingleResult {
  tir_blob_path: string;
  rationale: string;
  markdown_table: string;
  raw_structured: any;
  technical_review: any;
  alignment_review: any;
}

const TIRAnalysisPanel: React.FC<TIRAnalysisPanelProps> = ({ sessionId }) => {
  const [fdscIndexName, setFdscIndexName] = useState("fdsc-index");
  const [datasetPrefix, setDatasetPrefix] = useState("");
  const [results, setResults] = useState<TIRSingleResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [editedMarkdown, setEditedMarkdown] = useState("");
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runScoring = async () => {
    if (!datasetPrefix) {
      setError("Please enter a dataset prefix.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const resp = await api.post("/tir/score", {
        session_id: sessionId,
        fdsc_index_name: fdscIndexName,
        dataset_prefix: datasetPrefix
      });
      const res = resp.data.results as TIRSingleResult[];
      setResults(res);
      if (res.length > 0) {
        setSelectedIndex(0);
        setEditedMarkdown(res[0].markdown_table);
      } else {
        setSelectedIndex(null);
        setEditedMarkdown("");
      }
    } catch (err) {
      console.error(err);
      setError("Error scoring incident reports. Check backend logs.");
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = (idx: number) => {
    setSelectedIndex(idx);
    setEditedMarkdown(results[idx].markdown_table);
  };

  const saveEdited = async () => {
    if (selectedIndex === null) return;
    const tir = results[selectedIndex];
    try {
      await api.post("/tir/save", {
        session_id: sessionId,
        tir_id: encodeURIComponent(tir.tir_blob_path),
        edited_markdown: editedMarkdown
      });
      const updated = [...results];
      updated[selectedIndex] = { ...tir, markdown_table: editedMarkdown };
      setResults(updated);
    } catch (err) {
      console.error(err);
      setError("Error saving edited markdown.");
    }
  };

  const selectedResult = selectedIndex !== null ? results[selectedIndex] : null;

  return (
    <div className="tir-panel">
      <h2>Test Incident Report Analysis</h2>
      <div className="tir-config-row">
        <div>
          <label>FDSC Index:</label>
          <input
            value={fdscIndexName}
            onChange={(e) => setFdscIndexName(e.target.value)}
          />
        </div>
        <div>
          <label>TIR Dataset Prefix:</label>
          <input
            value={datasetPrefix}
            onChange={(e) => setDatasetPrefix(e.target.value)}
            placeholder="e.g. dataset-2025/"
          />
        </div>
        <button onClick={runScoring} disabled={loading}>
          {loading ? "Scoring..." : "Score Incident Reports"}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="tir-main">
        <div className="tir-list">
          <h3>Incidents</h3>
          {results.length === 0 ? (
            <p className="empty-state">No results yet. Run scoring to see incidents.</p>
          ) : (
            <ul>
              {results.map((r, idx) => (
                <li
                  key={idx}
                  className={selectedIndex === idx ? "selected" : ""}
                  onClick={() => handleSelect(idx)}
                >
                  {r.tir_blob_path}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="tir-detail">
          {selectedResult ? (
            <>
              <h3>Rationale</h3>
              <p>{selectedResult.rationale}</p>
              <h3>Score Table (Markdown)</h3>
              <textarea
                className="markdown-editor"
                value={editedMarkdown}
                onChange={(e) => setEditedMarkdown(e.target.value)}
              />
              <div className="tir-actions">
                <button onClick={saveEdited}>Save</button>
                <button onClick={() => setThinkingOpen(true)}>Thinking</button>
                <ExportButtons sessionId={sessionId} />
              </div>
            </>
          ) : (
            <p className="empty-state">No TIR selected. Run scoring and choose an incident to view details.</p>
          )}
        </div>
      </div>

      <ThinkingDrawer
        open={thinkingOpen}
        onClose={() => setThinkingOpen(false)}
        result={selectedResult}
      />
    </div>
  );
};

export default TIRAnalysisPanel;
