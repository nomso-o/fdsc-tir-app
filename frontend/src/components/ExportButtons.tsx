import React from "react";

interface ExportButtonsProps {
  sessionId: string | null;
  sessionToken: string | null;
}

const ExportButtons: React.FC<ExportButtonsProps> = ({ sessionId, sessionToken }) => {
  const exportDocx = () => {
    if (!sessionId || !sessionToken) return;
    window.open(
      `/api/tir/export/docx?session_id=${encodeURIComponent(sessionId)}&session_token=${encodeURIComponent(sessionToken)}`,
      "_blank"
    );
  };

  const exportPdf = () => {
    if (!sessionId || !sessionToken) return;
    window.open(
      `/api/tir/export/pdf?session_id=${encodeURIComponent(sessionId)}&session_token=${encodeURIComponent(sessionToken)}`,
      "_blank"
    );
  };

  return (
    <div className="export-buttons">
      <button onClick={exportDocx} disabled={!sessionId || !sessionToken}>
        Export DOCX
      </button>
      <button onClick={exportPdf} disabled={!sessionId || !sessionToken}>
        Export PDF
      </button>
    </div>
  );
};

export default ExportButtons;
