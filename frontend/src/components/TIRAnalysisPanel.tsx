import React, { useEffect, useState } from "react";
import api, { extractApiError } from "../api/client";
import ExportButtons from "./ExportButtons";
import ThinkingDrawer from "./ThinkingDrawer";

interface PrefixOption {
  value: string;
  label: string;
}

interface TIRSingleResult {
  tir_id: string;
  dataset_prefix: string;
  tir_blob_path: string;
  rationale: string;
  markdown_table: string;
  raw_structured: any;
  technical_review: any;
  alignment_review: any;
}

const TIRAnalysisPanel: React.FC = () => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [fdscIndexName, setFdscIndexName] = useState("fdsc-index");
  const [datasetPrefix, setDatasetPrefix] = useState("");
  const [datasetOptions, setDatasetOptions] = useState<PrefixOption[]>([]);
  const [fdscDocs, setFdscDocs] = useState<PrefixOption[]>([]);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [results, setResults] = useState<TIRSingleResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [editedMarkdown, setEditedMarkdown] = useState("");
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [datasetLoading, setDatasetLoading] = useState(false);
  const [docsLoading, setDocsLoading] = useState(false);

  useEffect(() => {
    const loadPrefixes = async () => {
      setDatasetLoading(true);
      try {
        const resp = await api.get("/tir/prefixes");
        const prefixes = (resp.data?.prefixes as PrefixOption[]) || [];
        setDatasetOptions(prefixes);
        setDatasetPrefix((prev) => (prev ? prev : prefixes[0]?.value ?? ""));
        if (prefixes.length === 0) {
          setError("No TIR datasets found. Upload datasets to Azure Blob first.");
        }
      } catch (err) {
        console.error(err);
        setError(extractApiError(err, "Failed to load available TIR datasets."));
      } finally {
        setDatasetLoading(false);
      }
    };
    loadPrefixes();
  }, []);

  useEffect(() => {
    const loadDocs = async () => {
      if (!fdscIndexName) return;
      setDocsLoading(true);
      try {
        const resp = await api.get("/fdsc/prefixes", {
          params: { fdsc_index_name: fdscIndexName }
        });
        const docs = (resp.data?.prefixes as PrefixOption[]) || [];
        setFdscDocs(docs);
        setSelectedDocId((prev) => {
          if (!docs.length) {
            return "";
          }
          const exists = docs.find((doc) => doc.value === prev);
          return exists ? prev : docs[0].value;
        });
      } catch (err) {
        console.error(err);
        setError(extractApiError(err, "Failed to load FDSC documents."));
      } finally {
        setDocsLoading(false);
      }
    };
    loadDocs();
  }, [fdscIndexName]);

  const runScoring = async () => {
    if (!datasetPrefix) {
      setError("Please select a dataset to score.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const payload: Record<string, any> = {
        fdsc_index_name: fdscIndexName,
        dataset_prefix: datasetPrefix
      };
      if (sessionId && sessionToken) {
        payload.session_id = sessionId;
        payload.session_token = sessionToken;
      }
      if (selectedDocId) {
        payload.fdsc_doc_id = selectedDocId;
      }
      const resp = await api.post("/tir/score", payload);
      const resolvedSessionId = resp.data.session_id as string;
      const resolvedSessionToken = resp.data.session_token as string;
      setSessionId(resolvedSessionId);
      setSessionToken(resolvedSessionToken);
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
      setError(extractApiError(err, "Error scoring incident reports."));
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
    if (!sessionId || !sessionToken) {
      setError("No active scoring session. Run scoring first.");
      return;
    }
    const tir = results[selectedIndex];
    try {
      await api.post("/tir/save", {
        session_id: sessionId,
        session_token: sessionToken,
        tir_id: encodeURIComponent(tir.tir_blob_path),
        edited_markdown: editedMarkdown
      });
      const updated = [...results];
      updated[selectedIndex] = { ...tir, markdown_table: editedMarkdown };
      setResults(updated);
    } catch (err) {
      console.error(err);
      setError(extractApiError(err, "Error saving edited markdown."));
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
        <div className="doc-select">
          <label>FDSC Document:</label>
          <select
            value={selectedDocId}
            onChange={(e) => setSelectedDocId(e.target.value)}
            disabled={docsLoading || fdscDocs.length === 0}
          >
            <option value="">All Documents</option>
            {fdscDocs.map((doc) => (
              <option key={doc.value} value={doc.value}>
                {doc.label}
              </option>
            ))}
          </select>
        </div>
        <div className="dataset-select">
          <label>TIR Dataset:</label>
          <select
            value={datasetPrefix}
            onChange={(e) => setDatasetPrefix(e.target.value)}
            disabled={datasetLoading || datasetOptions.length === 0}
          >
            {datasetOptions.length === 0 ? (
              <option value="">No datasets available</option>
            ) : (
              datasetOptions.map((prefix) => (
                <option key={prefix.value} value={prefix.value}>
                  {prefix.label}
                </option>
              ))
            )}
          </select>
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
                  key={r.tir_id}
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
                <ExportButtons sessionId={sessionId} sessionToken={sessionToken} />
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
