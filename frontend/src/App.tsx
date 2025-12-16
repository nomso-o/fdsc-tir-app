import React, { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import TIRAnalysisPanel from "./components/TIRAnalysisPanel";

const App: React.FC = () => {
  const [sessionId] = useState(() => crypto.randomUUID());

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>FDSC RAG & TIR Scoring</h1>
      </header>
      <main className="app-main">
        <section className="main-left">
          <TIRAnalysisPanel sessionId={sessionId} />
        </section>
        <section className="main-right">
          <ChatPanel sessionId={sessionId} />
        </section>
      </main>
    </div>
  );
};

export default App;
