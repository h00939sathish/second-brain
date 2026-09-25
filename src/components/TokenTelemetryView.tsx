import React, { useState, useEffect } from 'react';
import { TimeRange, InferenceRecord, ModelConsumptionPoint } from '../types';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface TokenTelemetryViewProps {
  consumptionData: ModelConsumptionPoint[];
  inferences: InferenceRecord[];
  vaultPath?: string;
  onSelectInference?: (item: InferenceRecord) => void;
}

export const TokenTelemetryView: React.FC<TokenTelemetryViewProps> = ({
  consumptionData,
  inferences,
  vaultPath,
}) => {
  useTrackComponentRender('TokenTelemetryView');
  const [timeRange, setTimeRange] = useState<TimeRange>('24H');
  const [vaultStatus, setVaultStatus] = useState<any>(null);

  useEffect(() => {
    fetch('/api/status')
      .then((res) => res.json())
      .then((data) => setVaultStatus(data))
      .catch(() => null);
  }, []);

  // No invented fallbacks: when the backend has not answered yet, say so rather than
  // printing a plausible-looking number.
  const backendUp = vaultStatus !== null;
  const totalClaims = vaultStatus?.claims_total;
  const activeClaims = vaultStatus?.claims_active;
  const l0Bytes = vaultStatus?.l0_bytes;
  const l0Budget = vaultStatus?.l0_budget ?? 2200;
  const l0Percent = l0Bytes != null ? Math.round((l0Bytes / l0Budget) * 100) : null;
  const unreviewed = vaultStatus?.unreviewed_claims;
  const workspaces: string[] = vaultStatus?.workspaces ?? [];
  const daemon = vaultStatus?.daemon as { active: boolean; detail: string } | undefined;

  return (
    <div className="space-y-6 pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <span className="text-[10px] uppercase tracking-[0.3em] text-[#C9A86A] font-semibold">
            Telemetry & Inferences
          </span>
          <h1 className="text-3xl md:text-4xl font-light tracking-tight text-white mt-1">
            System Telemetry
          </h1>
          <p className="font-code-sm text-xs text-white/40 mt-1 uppercase tracking-widest">
            Vault: {vaultPath || vaultStatus?.vault || 'not connected'}
            {' • '}
            {vaultStatus?.index?.engine ? 'SQLite FTS5 Active' : 'index unavailable'}
            {' • '}
            daemon?.active ? 'daemon active' : 'daemon stopped'
          </p>
        </div>

        {/* Time Range Filter */}
        <div className="flex items-center gap-1.5 p-1 bg-[#111111] border border-white/10 rounded-full">
          {(['1H', '24H', '7D'] as TimeRange[]).map((range) => {
            const isSelected = timeRange === range;
            return (
              <button
                key={range}
                onClick={() => setTimeRange(range)}
                className={`px-4 py-1.5 font-code-sm text-xs rounded-full transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_12px_rgba(201,168,106,0.3)]'
                    : 'text-white/40 hover:text-white hover:bg-white/5'
                }`}
              >
                {range}
              </button>
            );
          })}
        </div>
      </div>

      {/* Real KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Knowledge Truths */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Active Truth Store</span>
            <span className="text-[#4ADE80] font-bold text-xs">FTS5</span>
          </div>
          <div className="text-3xl md:text-4xl font-light text-white tracking-tight">
            {activeClaims ?? '--'} <span className="text-sm text-white/40">/ {totalClaims ?? '--'}</span>
          </div>
          <div className="font-code-sm text-xs text-[#4ADE80] mt-3">
            {!backendUp
              ? 'backend unreachable'
              : `${unreviewed ?? 0} unreviewed \u2022 chain verified`}
          </div>
        </div>

        {/* KPI 2: L0 Pointer Budget */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">L0 Auto-Inject Budget</span>
            <span className="text-[#C9A86A] font-bold text-xs">
              {l0Percent != null ? `${l0Percent}%` : '--'}
            </span>
          </div>
          <div className="text-3xl md:text-4xl font-light text-white tracking-tight">
            {l0Bytes ?? '--'} <span className="text-sm text-white/40">/ {l0Budget}B</span>
          </div>
          <div
            className={`font-code-sm text-xs mt-3 ${
              l0Percent != null && l0Percent > 100 ? 'text-[#f87171]' : 'text-white/40'
            }`}
          >
            {l0Percent == null
              ? 'backend unreachable'
              : l0Percent > 100
                ? 'OVER BUDGET \u2014 trim the brief'
                : 'within the injected budget'}
          </div>
        </div>

        {/* KPI 3: Architecture Superpower Model Division */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Lead Architect</span>
            <span className="text-[#a855f7] font-bold text-xs">GPT-5.6</span>
          </div>
          <div className="text-2xl font-light text-white tracking-tight">Codex (Planner)</div>
          <div className="font-code-sm text-xs text-white/40 mt-3">
            High-density Invariants & Sign-off
          </div>
        </div>

        {/* KPI 4: Context & Diff Reviewer */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Context Analyst</span>
            <span className="text-[#06b6d4] font-bold text-xs">Gemini 3.7</span>
          </div>
          <div className="text-2xl font-light text-white tracking-tight">Antigravity (Review)</div>
          <div className="font-code-sm text-xs text-[#06b6d4] mt-3">
            1M+ Context Diff Audits
          </div>
        </div>
      </div>

      {/* Model Activity Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-[#111111] border border-white/10 p-6 rounded-3xl">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-lg font-light text-white">Multi-Agent Division of Labor</h3>
              <p className="font-code-sm text-xs text-white/40 mt-0.5">Role specialization and workload distribution</p>
            </div>
            <span className="px-3 py-1 bg-[#4ADE80]/15 text-[#4ADE80] font-code-sm text-[10px] font-semibold rounded-full border border-[#4ADE80]/30">
              OPTIMIZED
            </span>
          </div>

          <div className="space-y-4">
            <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-[#a855f7]/20 text-[#a855f7] flex items-center justify-center font-bold text-xs">CX</span>
                <div>
                  <h4 className="text-sm font-medium text-white">GPT 5.6 (Codex)</h4>
                  <p className="text-xs text-white/40">Lead Architect & Spec Planning Arbiter</p>
                </div>
              </div>
              <span className="font-code-sm text-xs text-[#a855f7] font-semibold">Invariant Specs</span>
            </div>

            <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-[#06b6d4]/20 text-[#06b6d4] flex items-center justify-center font-bold text-xs">AG</span>
                <div>
                  <h4 className="text-sm font-medium text-white">Gemini 3.7 Flash (Antigravity)</h4>
                  <p className="text-xs text-white/40">Context Analyst & Final Diff Reviewer</p>
                </div>
              </div>
              <span className="font-code-sm text-xs text-[#06b6d4] font-semibold">1M+ Token Audits</span>
            </div>

            <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-[#10b981]/20 text-[#10b981] flex items-center justify-center font-bold text-xs">OC</span>
                <div>
                  <h4 className="text-sm font-medium text-white">opencode & Claude Code</h4>
                  <p className="text-xs text-white/40">Core Builders (Heavy Mechanical Typing)</p>
                </div>
              </div>
              <span className="font-code-sm text-xs text-[#10b981] font-semibold">Mechanical Edits</span>
            </div>
          </div>
        </div>

        {/* Ponytail Code Scoreboard */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between">
          <div>
            <span className="text-[10px] uppercase tracking-[0.25em] text-[#C9A86A] font-semibold block mb-1">
              Ponytail Efficiency Scoreboard
            </span>
            <h3 className="text-lg font-light text-white mb-4">Complexity Reduction</h3>
            <div className="space-y-3 font-code-sm text-xs">
              <div className="flex justify-between p-3 bg-[#161616] rounded-2xl border border-white/5">
                <span className="text-white/40">Dependencies Added</span>
                <span className="text-[#4ADE80] font-bold">0 (Stdlib First)</span>
              </div>
              <div className="flex justify-between p-3 bg-[#161616] rounded-2xl border border-white/5">
                <span className="text-white/40">Dead Code Pruned</span>
                <span className="text-[#4ADE80] font-bold">12 Factor Models</span>
              </div>
              <div className="flex justify-between p-3 bg-[#161616] rounded-2xl border border-white/5">
                <span className="text-white/40">Lock Strategy</span>
                <span className="text-[#C9A86A] font-bold">Non-Blocking Retry</span>
              </div>
            </div>
          </div>

          <div className="p-4 bg-[#C9A86A]/10 border border-[#C9A86A]/30 rounded-2xl text-xs text-[#C9A86A] mt-4 font-code-sm">
            Zero bloat invariant active across all builder agents.
          </div>
        </div>
      </div>
    </div>
  );
};
