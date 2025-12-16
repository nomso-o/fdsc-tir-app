import React from "react";

interface ExportButtonsProps {
  sessionId: string;
}

const ExportButtons: React.FC<ExportButtonsProps> = ({ sessionId }) => {
  const exportDocx = () => {
    window.open(`/api/tir/export/docx?session_id=${encodeURIComponent(sessionId)}`, "_blank");
  };

  const exportPdf = () => {
    window.open(`/api/tir/export/pdf?session_id=${encodeURIComponent(sessionId)}`, "_blank");
  };

  return (
    <div className="export-buttons">
      <button onClick={exportDocx}>Export DOCX</button>
      <button onClick={exportPdf}>Export PDF</button>
    </div>
  );
};

export default ExportButtons;
