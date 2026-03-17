import React, { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import TIRAnalysisPanel from "./components/TIRAnalysisPanel";
import FDSCDocumentManager from "./components/FDSCDocumentManager";

const App: React.FC = () => {
  const [chatSessionId] = useState(() => crypto.randomUUID());

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>FDSC RAG & TIR Scoring</h1>
      </header>
      <main className="app-main">
        <section className="main-left">
          <FDSCDocumentManager />
          <TIRAnalysisPanel />
        </section>
        <section className="main-right">
          <ChatPanel sessionId={chatSessionId} />
        </section>
      </main>
    </div>
  );
};

export default App;
