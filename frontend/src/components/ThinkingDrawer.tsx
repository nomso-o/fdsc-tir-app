import React from "react";

interface ThinkingDrawerProps {
  open: boolean;
  onClose: () => void;
  result: any | null;
}

const ThinkingDrawer: React.FC<ThinkingDrawerProps> = ({ open, onClose, result }) => {
  if (!open || !result) return null;

  return (
    <div className="thinking-overlay" onClick={onClose}>
      <div className="thinking-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="thinking-header">
          <h3>Agent Thinking / Reviews</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <div className="thinking-content">
          <h4>Technical Review</h4>
          <pre>{JSON.stringify(result.technical_review, null, 2)}</pre>
          <h4>FDSC Alignment Review</h4>
          <pre>{JSON.stringify(result.alignment_review, null, 2)}</pre>
          <h4>Structured Output</h4>
          <pre>{JSON.stringify(result.raw_structured, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
};

export default ThinkingDrawer;
