import React, { useCallback, useEffect, useState } from "react";
import api, { extractApiError } from "../api/client";

interface FDSCDocument {
  id: string;
  doc_id: string;
  doc_namespace?: string;
  source_file?: string;
  chunk_count?: number;
  updated_at?: string;
  blob_uri?: string;
  index_name: string;
  semantic_chunking?: boolean;
  ingestion_status?: "processing" | "indexed" | "failed";
}

const FDSCDocumentManager: React.FC = () => {
  const [indexName, setIndexName] = useState("fdsc-index");
  const [docId, setDocId] = useState("");
  const [namespace, setNamespace] = useState("default");
  const [useSemantic, setUseSemantic] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [documents, setDocuments] = useState<FDSCDocument[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadDocuments = useCallback(async () => {
    if (!indexName) return;
    try {
      const resp = await api.get("/fdsc/docs", { params: { fdsc_index_name: indexName } });
      const docs = (resp.data?.documents as FDSCDocument[]) || [];
      docs.sort((a, b) => {
        if (!a.updated_at || !b.updated_at) return 0;
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      });
      setDocuments(docs);
    } catch (err) {
      console.error(err);
      setStatus(extractApiError(err, "Failed to load FDSC documents."));
    }
  }, [indexName]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleUpload = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file || !docId) {
      setStatus("Provide a document id and choose a file.");
      return;
    }
    setLoading(true);
    setStatus(null);
    try {
      const formData = new FormData();
      formData.append("fdsc_index_name", indexName);
      formData.append("doc_id", docId);
      formData.append("doc_namespace", namespace);
      formData.append("use_semantic_chunking", String(useSemantic));
      formData.append("file", file);
      await api.post("/fdsc/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      setStatus("Upload complete. Document indexed and ready for scoring.");
      await loadDocuments();
    } catch (err) {
      console.error(err);
      setStatus(extractApiError(err, "Upload failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fdsc-doc-manager">
      <h2>FDSC Document Manager</h2>
      <form className="fdsc-upload-form" onSubmit={handleUpload}>
        <div className="form-row">
          <label>FDSC Index</label>
          <input value={indexName} onChange={(e) => setIndexName(e.target.value)} />
        </div>
        <div className="form-row">
          <label>Document ID</label>
          <input value={docId} onChange={(e) => setDocId(e.target.value)} />
        </div>
        <div className="form-row">
          <label>Namespace</label>
          <input value={namespace} onChange={(e) => setNamespace(e.target.value)} />
        </div>
        <div className="form-row">
          <label>File</label>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </div>
        <div className="form-row checkbox-row">
          <label>
            <input
              type="checkbox"
              checked={useSemantic}
              onChange={(e) => setUseSemantic(e.target.checked)}
            />
            Semantic chunking
          </label>
        </div>
        <button type="submit" disabled={loading}>
          {loading ? "Uploading..." : "Upload & Ingest"}
        </button>
      </form>
      {status && <p className="status-text">{status}</p>}
      <div className="fdsc-doc-table">
        <h3>Indexed Documents</h3>
        {documents.length === 0 ? (
          <p className="empty-state">No documents have been ingested yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Doc ID</th>
                <th>Namespace</th>
                <th>Chunks</th>
                <th>Semantic</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>{doc.doc_id}</td>
                  <td>{doc.doc_namespace || "default"}</td>
                  <td>{doc.chunk_count ?? "—"}</td>
                  <td>{doc.semantic_chunking ? "Yes" : "No"}</td>
                  <td>{doc.ingestion_status || "indexed"}</td>
                  <td>{doc.updated_at ? new Date(doc.updated_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default FDSCDocumentManager;
