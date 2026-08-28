import React, { useState } from 'react';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

const DEFAULT_SPEC_CONTENT = `# Unified Component Architecture
**Spec ID:** \`spec-20260828-b4ef8d\`  
**Target Model:** Antigravity / Codex-5.6 Multi-Agent Mesh  
**Status:** In Review • Signed-off by Security Daemon  

## 1. Overview & Context
This specification outlines the unified UI tokens, design variables, and autonomous execution boundaries for all mission control clients.

### 1.1 Objectives
- **Zero Token Leakage:** Context memory buffers must be strictly sealed per daemon thread.
- **Micro-border Tokens:** Standardize container borders to 1px with deliberate alpha opacity (\`#27272A\`).
- **Telemetry Observability:** Real-time metrics streaming over WebSockets and SSE channels.

## 2. Interface Contract
\`\`\`typescript
export interface AutonomousTask {
  id: string;
  daemon_pid: number;
  max_token_ceiling: number;
  verification_hash: string;
}
\`\`\`

## 3. Truth Claims & Validation
- **CLAIM-01:** Token latency shall not exceed 850ms under peak 10k concurrent req/min.
- **CLAIM-02:** All state mutation logs are append-only and cryptographically verified.
`;

export const SpecsEditorView: React.FC = () => {
  useTrackComponentRender('SpecsEditorView');
  const [content, setContent] = useState(DEFAULT_SPEC_CONTENT);
  const [isPreview, setIsPreview] = useState(false);
  const [isSaved, setIsSaved] = useState(true);
  const [showSyncSuccess, setShowSyncSuccess] = useState(false);

  const handleSyncToGraph = () => {
    setShowSyncSuccess(true);
    setTimeout(() => setShowSyncSuccess(false), 3000);
  };

  const handlePublish = () => {
    setIsSaved(true);
    alert('Specification successfully signed and published to daemon mesh!');
  };

  return (
    <div className="space-y-4 pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-[#111111] border border-white/10 rounded-3xl">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-code-sm text-xs text-[#C9A86A] font-semibold">spec-20260828-b4ef8d</span>
            <span className="px-2.5 py-0.5 rounded-full bg-[#4ADE80]/15 text-[#4ADE80] font-code-sm text-[10px] font-semibold border border-[#4ADE80]/30">
              APPROVED
            </span>
          </div>
          <h1 className="text-lg md:text-xl font-light text-white mt-1">
            Unified Component Architecture
          </h1>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncToGraph}
            className="px-4 py-2 bg-[#161616] hover:bg-white/10 border border-white/10 text-white/80 rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">hub</span>
            Sync to Graph
          </button>

          <button
            onClick={handlePublish}
            className="px-5 py-2 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(201,168,106,0.25)] cursor-pointer"
          >
            <span className="material-symbols-outlined text-[16px]">publish</span>
            Publish Spec
          </button>
        </div>
      </div>

      {showSyncSuccess && (
        <div className="p-3 bg-[#4ADE80]/10 border border-[#4ADE80]/30 rounded-2xl text-xs font-code-sm text-[#4ADE80] flex items-center gap-2">
          <span className="material-symbols-outlined text-[16px]">check_circle</span>
          Knowledge Graph synchronized. 3 claims mapped to active pipeline.
        </div>
      )}

      {/* Main Split: 2/3 Markdown Editor, 1/3 Truth Mapping Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Editor (Spans 2 col on lg) */}
        <div className="lg:col-span-2 bg-[#111111] border border-white/10 rounded-3xl flex flex-col min-h-[520px] overflow-hidden">
          {/* Markdown Toolbar */}
          <div className="px-4 py-2.5 bg-[#161616] border-b border-white/10 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1 text-white/50">
              <button
                onClick={() => setContent((c) => c + '\n# New Section\n')}
                className="px-2 py-1 hover:text-white hover:bg-white/10 rounded-full font-bold text-xs cursor-pointer transition-colors"
                title="H1 Heading"
              >
                H1
              </button>
              <button
                onClick={() => setContent((c) => c + '\n## Subsection\n')}
                className="px-2 py-1 hover:text-white hover:bg-white/10 rounded-full font-bold text-xs cursor-pointer transition-colors"
                title="H2 Heading"
              >
                H2
              </button>
              <span className="w-[1px] h-4 bg-white/10 mx-1"></span>
              <button
                onClick={() => setContent((c) => c + ' **bold text** ')}
                className="p-1 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
                title="Bold"
              >
                <span className="material-symbols-outlined text-[16px]">format_bold</span>
              </button>
              <button
                onClick={() => setContent((c) => c + ' *italic text* ')}
                className="p-1 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
                title="Italic"
              >
                <span className="material-symbols-outlined text-[16px]">format_italic</span>
              </button>
              <button
                onClick={() => setContent((c) => c + '\n```typescript\n// code here\n```\n')}
                className="p-1 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
                title="Code Block"
              >
                <span className="material-symbols-outlined text-[16px]">code</span>
              </button>
              <button
                onClick={() => setContent((c) => c + '\n- List item\n')}
                className="p-1 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
                title="Bullet List"
              >
                <span className="material-symbols-outlined text-[16px]">format_list_bulleted</span>
              </button>
            </div>

            {/* Edit / Preview Toggle */}
            <div className="flex items-center gap-1 bg-[#111111] border border-white/10 p-0.5 rounded-full font-code-sm text-xs">
              <button
                onClick={() => setIsPreview(false)}
                className={`px-3 py-1 rounded-full transition-all cursor-pointer ${
                  !isPreview ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]' : 'text-white/40 hover:text-white'
                }`}
              >
                Edit
              </button>
              <button
                onClick={() => setIsPreview(true)}
                className={`px-3 py-1 rounded-full transition-all cursor-pointer ${
                  isPreview ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]' : 'text-white/40 hover:text-white'
                }`}
              >
                Preview
              </button>
            </div>
          </div>

          {/* Editor Textarea / Preview Canvas */}
          <div className="flex-1 p-5 font-mono text-xs">
            {!isPreview ? (
              <textarea
                value={content}
                onChange={(e) => {
                  setContent(e.target.value);
                  setIsSaved(false);
                }}
                className="w-full h-full min-h-[420px] bg-transparent text-white/90 resize-none focus:outline-none leading-relaxed font-mono"
                placeholder="Write specification markdown here..."
              />
            ) : (
              <div className="prose prose-invert max-w-none text-xs space-y-3 font-sans leading-relaxed text-white/70">
                <h1 className="text-xl font-light text-white border-b border-white/10 pb-2">
                  Unified Component Architecture
                </h1>
                <p className="font-code-sm text-xs text-[#C9A86A]">
                  Spec ID: <code>spec-20260828-b4ef8d</code> • Target Model: Antigravity / Codex-5.6
                </p>
                <h2 className="text-base font-medium text-white mt-4">1. Overview & Context</h2>
                <p>This specification outlines the unified UI tokens, design variables, and autonomous execution boundaries.</p>
                <div className="p-4 bg-[#090909] border border-white/10 rounded-2xl font-code-sm text-xs text-[#C9A86A]">
                  {`export interface AutonomousTask { id: string; daemon_pid: number; max_token_ceiling: number; }`}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Context & Truth Mapping Rail */}
        <div className="space-y-4">
          {/* Truth Mapping */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-5">
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[16px] text-[#4ADE80]">verified</span>
                Truth Mapping
              </span>
              <span className="font-code-sm text-xs text-[#4ADE80]">3 Verified</span>
            </div>

            <div className="space-y-2.5 font-code-sm text-xs">
              <div className="p-3 bg-[#161616] border border-white/5 rounded-2xl">
                <div className="text-white/40 text-[9px] uppercase tracking-wider">Claim</div>
                <div className="text-white font-medium mt-0.5">Identity Model Partitioning</div>
                <div className="text-[#4ADE80] text-[10px] mt-1.5 flex items-center gap-1">
                  <span className="material-symbols-outlined text-[12px]">check</span> Verified in DB
                </div>
              </div>

              <div className="p-3 bg-[#161616] border border-white/5 rounded-2xl">
                <div className="text-white/40 text-[9px] uppercase tracking-wider">Task Link</div>
                <div className="text-white font-medium mt-0.5">t-20260828-676466 (UI Kit)</div>
                <div className="text-[#C9A86A] text-[10px] mt-1.5 flex items-center gap-1">
                  <span className="material-symbols-outlined text-[12px]">schedule</span> Running
                </div>
              </div>

              <div className="p-3 bg-[#161616] border border-white/5 rounded-2xl">
                <div className="text-white/40 text-[9px] uppercase tracking-wider">Graph Node</div>
                <div className="text-white font-medium mt-0.5">spec-02 (Unified UI Kit)</div>
                <div className="text-white/60 text-[10px] mt-1.5 flex items-center gap-1">
                  <span className="material-symbols-outlined text-[12px]">hub</span> Mapped
                </div>
              </div>
            </div>
          </div>

          {/* Upstream Dependencies */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-5">
            <div className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium mb-3 flex items-center gap-1.5">
              <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">call_split</span>
              Upstream Dependencies
            </div>

            <div className="p-3 bg-[#161616] border border-white/5 rounded-2xl font-code-sm text-xs">
              <div className="text-[#C9A86A] font-semibold">REQ-Alpha-V2</div>
              <div className="text-white/40 text-[11px] mt-1">Core System Architecture Spec</div>
            </div>
          </div>

          {/* Version History */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-5">
            <div className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium mb-3">
              Version History
            </div>

            <div className="space-y-2.5 font-code-sm text-xs">
              <div className="border-l-2 border-[#C9A86A] pl-3 py-0.5">
                <div className="text-white font-medium">Codex Agent (v1.4)</div>
                <div className="text-white/40 text-[10px] mt-0.5">5m ago • Refactored AST token schemas</div>
              </div>
              <div className="border-l-2 border-white/10 pl-3 py-0.5">
                <div className="text-white/70">Admin User (v1.3)</div>
                <div className="text-white/40 text-[10px] mt-0.5">2h ago • Signed off security model</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
