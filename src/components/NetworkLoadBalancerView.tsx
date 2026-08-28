import React, { useState } from 'react';
import { QueueTask, DaemonLoadInfo } from '../types';

interface NetworkLoadBalancerViewProps {
  daemonLoads: DaemonLoadInfo[];
  queueTasks: QueueTask[];
  onOpenDeployModal: () => void;
  onAddQueueTask?: (task: QueueTask) => void;
}

export const NetworkLoadBalancerView: React.FC<NetworkLoadBalancerViewProps> = ({
  daemonLoads,
  queueTasks,
  onOpenDeployModal,
}) => {
  const [tasksList, setTasksList] = useState<QueueTask[]>(queueTasks);
  const [activeTab, setActiveTab] = useState<'overview' | 'regions'>('overview');

  const promoteTask = (id: string) => {
    setTasksList((prev) => {
      const idx = prev.findIndex((t) => t.id === id);
      if (idx <= 0) return prev;
      const copy = [...prev];
      const temp = copy[idx - 1];
      copy[idx - 1] = copy[idx];
      copy[idx] = temp;
      return copy;
    });
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl md:text-3xl font-light tracking-tight text-white">
              System Load Balancer
            </h1>
            <span className="font-code-sm text-xs px-2.5 py-0.5 rounded-full bg-[#4ADE80]/15 text-[#4ADE80] border border-[#4ADE80]/30 font-medium">
              HEALTHY
            </span>
          </div>
          <p className="font-code-sm text-xs text-white/40 mt-1">
            Core Engine v2.4.0-stable • Autonomous traffic distributor & mesh orchestrator.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onOpenDeployModal}
            className="px-4 py-2 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(201,168,106,0.25)] cursor-pointer"
          >
            <span className="material-symbols-outlined text-[16px]">add_circle</span>
            Deploy Agent
          </button>
        </div>
      </div>

      {/* Daemon Load Capacities Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {daemonLoads.map((d) => {
          const isHigh = d.loadPercent > 80;
          return (
            <div
              key={d.name}
              className="bg-[#111111] border border-white/10 p-5 rounded-3xl flex flex-col justify-between relative overflow-hidden"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: d.color, boxShadow: `0 0 8px ${d.color}` }}
                  ></span>
                  <span className="font-medium text-sm text-white">{d.name}</span>
                </div>
                <span className="font-code-sm text-xs text-white/40">{d.activeThreads} Threads</span>
              </div>

              <div>
                <div className="flex justify-between items-baseline mb-1.5 font-code-sm">
                  <span className="text-xs text-white/40">Load Capacity</span>
                  <span
                    className="text-base font-semibold"
                    style={{ color: isHigh ? '#E5A93C' : d.color }}
                  >
                    {d.loadPercent}%
                  </span>
                </div>
                <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${d.loadPercent}%`,
                      backgroundColor: isHigh ? '#E5A93C' : d.color,
                    }}
                  ></div>
                </div>
              </div>

              <div className="mt-3 pt-2.5 border-t border-white/5 flex justify-between font-code-sm text-[10px] text-white/40">
                <span>RAM: {d.memoryUsage}</span>
                <span className="text-[#4ADE80]">Status: Active</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Main Grid: Queue Management & Traffic Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Priority Queue (Spans 2 cols on lg) */}
        <div className="lg:col-span-2 bg-[#111111] border border-white/10 rounded-3xl flex flex-col overflow-hidden">
          <div className="p-5 border-b border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/80">
              <span className="material-symbols-outlined text-[18px] text-[#C9A86A]">reorder</span>
              <span>Priority Request Queue</span>
            </div>
            <span className="font-code-sm text-xs text-white/40">{tasksList.length} In-Flight</span>
          </div>

          <div className="p-5 flex-1 space-y-2.5">
            {tasksList.map((q, idx) => {
              const priColor =
                q.priority === 'CRITICAL'
                  ? 'text-[#E5A93C] border-[#E5A93C]/40 bg-[#E5A93C]/10'
                  : q.priority === 'HIGH'
                  ? 'text-[#C9A86A] border-[#C9A86A]/40 bg-[#C9A86A]/10'
                  : q.priority === 'NORMAL'
                  ? 'text-white border-white/20 bg-white/5'
                  : 'text-white/40 border-white/10 bg-white/[0.02]';

              return (
                <div
                  key={q.id}
                  className="p-3.5 bg-[#161616] border border-white/5 rounded-2xl flex items-center justify-between gap-3 text-xs font-code-sm hover:border-white/20 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-white/30 w-4">{idx + 1}</span>
                    <span className={`px-2 py-0.5 rounded-full border text-[9px] font-semibold ${priColor}`}>
                      {q.priority}
                    </span>
                    <span className="text-white/90 font-medium">{q.id}</span>
                  </div>

                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: q.daemonColor }}
                      ></span>
                      <span className="text-white/70">{q.targetDaemon}</span>
                    </div>

                    <span
                      className={`px-2 py-0.5 rounded-full text-[9px] font-medium ${
                        q.status === 'Processing'
                          ? 'bg-[#C9A86A]/15 text-[#C9A86A] animate-pulse'
                          : 'bg-white/10 text-white/40'
                      }`}
                    >
                      {q.status}
                    </span>

                    <span className="text-white/40 w-12 text-right">{q.estWait}</span>

                    <button
                      onClick={() => promoteTask(q.id)}
                      disabled={idx === 0}
                      className="p-1 hover:bg-white/10 text-white/40 hover:text-white rounded-full disabled:opacity-20 disabled:cursor-not-allowed cursor-pointer"
                      title="Promote Priority"
                    >
                      <span className="material-symbols-outlined text-[14px]">arrow_upward</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Traffic Distribution & Donut Metric */}
        <div className="space-y-4">
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-5 flex flex-col justify-between">
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium">
                Traffic Distribution
              </span>
              <span className="font-code-sm text-xs text-[#C9A86A]">1,204 Req/min</span>
            </div>

            {/* Donut representation */}
            <div className="relative flex items-center justify-center my-4">
              <div className="w-32 h-32 rounded-full border-8 border-[#C9A86A] flex items-center justify-center relative shadow-[0_0_15px_rgba(201,168,106,0.2)]">
                <div className="text-center font-code-sm">
                  <div className="text-xl font-light text-white">1.2k</div>
                  <div className="text-[9px] text-white/40 uppercase tracking-widest">RPS Blend</div>
                </div>
              </div>
            </div>

            <div className="space-y-2 font-code-sm text-xs">
              <div className="flex justify-between items-center text-white/80">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#C9A86A]"></span> Antigravity (45%)
                </span>
                <span className="font-medium">541 req/m</span>
              </div>
              <div className="flex justify-between items-center text-white/80">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-white"></span> Claude (30%)
                </span>
                <span className="font-medium">361 req/m</span>
              </div>
              <div className="flex justify-between items-center text-white/80">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-white/60"></span> Codex (18%)
                </span>
                <span className="font-medium">216 req/m</span>
              </div>
              <div className="flex justify-between items-center text-white/80">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#4ADE80]"></span> opencode (7%)
                </span>
                <span className="font-medium">86 req/m</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Latency Map Terminal */}
      <div className="bg-[#090909] border border-white/10 rounded-3xl p-5 crt-overlay">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10 relative z-10 font-code-sm">
          <span className="text-xs text-[#C9A86A] font-semibold uppercase tracking-wider flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[16px] animate-pulse">radar</span>
            LATENCY_MAP & Endpoint Topology
          </span>
          <span className="text-[11px] text-[#4ADE80]">Mesh Synced: 0.4ms</span>
        </div>

        {/* Heat Map Grid */}
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-2 mb-3 relative z-10">
          {[
            { region: 'us-east-1', lat: '12ms', color: '#4ADE80' },
            { region: 'us-west-2', lat: '34ms', color: '#4ADE80' },
            { region: 'eu-central-1', lat: '88ms', color: '#C9A86A' },
            { region: 'ap-northeast-1', lat: '142ms', color: '#E5A93C' },
            { region: 'sa-east-1', lat: '165ms', color: '#E5A93C' },
            { region: 'local-unix-sock', lat: '0.2ms', color: '#4ADE80' },
            { region: 'core-rpc-mesh', lat: '1.4ms', color: '#4ADE80' },
            { region: 'edge-cdn-proxy', lat: '18ms', color: '#4ADE80' },
          ].map((item) => (
            <div
              key={item.region}
              className="p-2.5 bg-[#161616] border border-white/5 rounded-xl font-code-sm text-center"
            >
              <div className="text-[10px] text-white/40 truncate">{item.region}</div>
              <div className="text-xs font-semibold mt-1" style={{ color: item.color }}>
                {item.lat}
              </div>
            </div>
          ))}
        </div>

        {/* Terminal Ping output */}
        <div className="font-code-sm text-xs text-white/40 space-y-1 relative z-10 bg-[#161616]/70 p-3 rounded-2xl border border-white/5">
          <div>PING us-east.gateway.internal (10.0.4.12): 56 data bytes</div>
          <div className="text-[#C9A86A]">64 bytes from 10.0.4.12: icmp_seq=0 ttl=64 time=0.412 ms</div>
          <div className="text-[#C9A86A]">64 bytes from 10.0.4.12: icmp_seq=1 ttl=64 time=0.389 ms</div>
          <div className="text-[#4ADE80]">--- us-east.gateway.internal ping statistics: 0.0% packet loss ---</div>
        </div>
      </div>
    </div>
  );
};
