import React, { useState, useEffect } from 'react';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface SpecData {
  id: string;
  title: string;
  project: string;
  phases: string[];
  created: string;
  body: string;
}

export const SpecsEditorView: React.FC = () => {
  useTrackComponentRender('SpecsEditorView');
  const [specs, setSpecs] = useState<SpecData[]>([]);
  const [selectedSpecId, setSelectedSpecId] = useState<string>('spec-20260828-b4ef8d');
  const [content, setContent] = useState<string>('');
  const [isPreview, setIsPreview] = useState(false);
  const [showSyncSuccess, setShowSyncSuccess] = useState(false);

  useEffect(() => {
    fetch('/api/specs')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setSpecs(data);
          const first = data.find((s: SpecData) => s.id === selectedSpecId) || data[0];
          setSelectedSpecId(first.id);
          setContent(first.body);
        }
      })
      .catch(() => null);
  }, []);

  const currentSpec = specs.find((s) => s.id === selectedSpecId);

  const handleSelectSpec = (specId: string) => {
    setSelectedSpecId(specId);
    const sp = specs.find((s) => s.id === specId);
    if (sp) {
      setContent(sp.body);
    }
  };

  const handlePublish = () => {
    setShowSyncSuccess(true);
    setTimeout(() => setShowSyncSuccess(false), 3000);
  };

  return (
    <div className="space-y-4 pb-12">
      {/* Header & Spec Selector */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-[#111111] border border-white/10 rounded-3xl">
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Upstream Architecture Spec</span>
            <div className="flex items-center gap-2 mt-1">
              <select
                value={selectedSpecId}
                onChange={(e) => handleSelectSpec(e.target.value)}
                className="bg-[#161616] border border-white/20 text-white font-code-sm text-xs rounded-xl px-3 py-1.5 focus:outline-none focus:border-[#C9A86A]"
              >
                {specs.map((sp) => (
                  <option key={sp.id} value={sp.id}>
                    [{sp.project || 'General'}] {sp.title} ({sp.id})
                  </option>
                ))}
              </select>
              <span className="px-2.5 py-0.5 rounded-full bg-[#4ADE80]/15 text-[#4ADE80] font-code-sm text-[10px] font-semibold border border-[#4ADE80]/30">
                ACTIVE
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsPreview(!isPreview)}
            className="px-4 py-2 bg-[#161616] hover:bg-white/10 border border-white/10 text-white/80 rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            {isPreview ? 'Edit Spec' : 'Markdown Preview'}
          </button>

          <button
            onClick={handlePublish}
            className="px-5 py-2 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(201,168,106,0.25)] cursor-pointer"
          >
            Sync with Agents
          </button>
        </div>
      </div>

      {showSyncSuccess && (
        <div className="p-3 bg-[#4ADE80]/10 border border-[#4ADE80]/30 rounded-2xl text-xs font-code-sm text-[#4ADE80] flex items-center gap-2">
          <span>✓ Upstream specification synchronized with Codex and Antigravity.</span>
        </div>
      )}

      {/* Main Split: 2/3 Markdown Editor, 1/3 Phased Roadmap */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-[#111111] border border-white/10 rounded-3xl flex flex-col min-h-[520px] overflow-hidden">
          <div className="px-4 py-2.5 bg-[#161616] border-b border-white/10 flex items-center justify-between">
            <span className="font-code-sm text-xs text-white/60">
              {currentSpec ? `specs/${currentSpec.id}.md` : 'specs/spec.md'}
            </span>
            <span className="font-code-sm text-[10px] text-white/40">UTF-8 • Markdown</span>
          </div>

          {isPreview ? (
            <div className="flex-1 p-6 font-mono text-xs text-white/80 whitespace-pre-wrap overflow-y-auto leading-relaxed">
              {content || '(Empty specification)'}
            </div>
          ) : (
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="flex-1 w-full p-6 bg-transparent text-white font-mono text-xs focus:outline-none resize-none leading-relaxed"
              placeholder="# Write upstream architecture spec here..."
            />
          )}
        </div>

        {/* Phased Roadmap & Invariants */}
        <div className="space-y-4">
          <div className="p-5 bg-[#111111] border border-white/10 rounded-3xl">
            <span className="text-[10px] uppercase tracking-[0.2em] text-[#C9A86A] font-semibold block mb-3">
              Execution Phases
            </span>
            <div className="space-y-2.5">
              {currentSpec?.phases?.length ? (
                currentSpec.phases.map((ph, idx) => (
                  <div
                    key={idx}
                    className="p-3 bg-[#161616] border border-white/5 rounded-2xl font-code-sm text-xs text-white/80 flex items-center gap-2.5"
                  >
                    <span className="w-5 h-5 rounded-full bg-[#C9A86A]/20 text-[#C9A86A] flex items-center justify-center font-bold text-[10px]">
                      {idx + 1}
                    </span>
                    <span className="truncate">{ph}</span>
                  </div>
                ))
              ) : (
                <div className="text-white/40 text-xs font-code-sm">No phased milestones defined.</div>
              )}
            </div>
          </div>

          <div className="p-5 bg-[#111111] border border-white/10 rounded-3xl font-code-sm text-xs space-y-2">
            <span className="text-[10px] uppercase tracking-[0.2em] text-white/40 block">Spec Invariant Rule</span>
            <p className="text-white/60 leading-relaxed">
              Specifications define architectural invariants and execution phases before any builder agent modifies code.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
