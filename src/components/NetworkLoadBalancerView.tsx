import React, { useState, useEffect } from 'react';
import { QueueTask, DaemonLoadInfo } from '../types';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface NetworkLoadBalancerViewProps {
  daemonLoads: DaemonLoadInfo[];
  queueTasks: QueueTask[];
  onOpenDeployModal: () => void;
  onAddQueueTask?: (task: QueueTask) => void;
}

const hexToRgba = (hex: string, alpha: number) => {
  const cleanHex = (hex || '#C9A86A').replace('#', '');
  const r = parseInt(cleanHex.substring(0, 2), 16) || 201;
  const g = parseInt(cleanHex.substring(2, 4), 16) || 168;
  const b = parseInt(cleanHex.substring(4, 6), 16) || 106;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

export const NetworkLoadBalancerView: React.FC<NetworkLoadBalancerViewProps> = ({
  daemonLoads,
  queueTasks,
  onOpenDeployModal,
}) => {
  useTrackComponentRender('NetworkLoadBalancerView');
  const [tasksList, setTasksList] = useState<QueueTask[]>(queueTasks);
  const [activeTab, setActiveTab] = useState<'overview' | 'regions'>('overview');
  const [liveLoads, setLiveLoads] = useState<DaemonLoadInfo[]>(daemonLoads);

  useEffect(() => {
    setLiveLoads(daemonLoads);
  }, [daemonLoads]);

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

  const adjustThreads = (daemonName: string, delta: number) => {
    setLiveLoads((prev) =>
      prev.map((d) => {
        if (d.name === daemonName) {
          const newThreads = Math.max(0, Math.min(16, d.activeThreads + delta));
          const calculatedLoad = Math.min(100, Math.max(10, Math.round(newThreads * 11 + 5)));
          return {
            ...d,
            activeThreads: newThreads,
            loadPercent: calculatedLoad,
          };
        }
        return d;
      })
    );
  };

  const simulateBurst = () => {
    setLiveLoads((prev) =>
      prev.map((d) => {
        const boost = Math.floor(Math.random() * 4) + 2;
        const newThreads = Math.min(15, d.activeThreads + boost);
        return {
          ...d,
          activeThreads: newThreads,
          loadPercent: Math.min(98, Math.round(newThreads * 9 + 15)),
        };
      })
    );
  };

  const resetLoads = () => {
    setLiveLoads(daemonLoads);
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
            Core Engine v2.4.0-stable • Autonomous traffic distributor & dynamic thread telemetry.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={simulateBurst}
            className="px-3.5 py-2 bg-white/5 hover:bg-white/10 text-white/80 hover:text-white border border-white/10 rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all cursor-pointer"
            title="Simulate load burst to see pulse acceleration"
          >
            <span className="material-symbols-outlined text-[15px] text-[#E5A93C]">bolt</span>
            Simulate Traffic Spike
          </button>
          <button
            onClick={resetLoads}
            className="p-2 bg-white/5 hover:bg-white/10 text-white/60 hover:text-white border border-white/10 rounded-full font-code-sm text-xs transition-all cursor-pointer"
            title="Reset to baseline loads"
          >
            <span className="material-symbols-outlined text-[15px]">restart_alt</span>
          </button>
          <button
            onClick={onOpenDeployModal}
            className="px-4 py-2 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(201,168,106,0.25)] cursor-pointer"
          >
            <span className="material-symbols-outlined text-[16px]">add_circle</span>
            Deploy Agent
          </button>
        </div>
      </div>

      {/* Daemon Load Capacities Cards with Dynamic Visual Pulse Animation */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {liveLoads.map((d) => {
          const isHigh = d.loadPercent > 80;
          const threads = Math.max(0, d.activeThreads);
          
          // Dynamic pulse speed calculation:
          // Lower thread count -> slower pulse (e.g. 3.2s)
          // Higher thread count -> faster pulse (e.g. 0.55s)
          const pulseDuration = Math.max(0.5, 3.2 - Math.min(threads, 12) * 0.24);
          
          // Dynamic color intensity & glow calculation:
          const loadIntensity = Math.min(1, Math.max(0.2, (threads / 8) * 0.75 + (d.loadPercent / 100) * 0.25));
          const colorHex = d.color || '#C9A86A';
          
          const glowIdle = hexToRgba(colorHex, 0.04 + loadIntensity * 0.08);
          const glowActive = hexToRgba(colorHex, 0.25 + loadIntensity * 0.55);
          const borderIdle = hexToRgba(colorHex, 0.12 + loadIntensity * 0.18);
          const borderActive = hexToRgba(colorHex, 0.4 + loadIntensity * 0.5);
          const glowBlurMax = Math.round(10 + loadIntensity * 26);
          const frequencyHz = (1 / pulseDuration).toFixed(1);

          return (
            <div
              key={d.name}
              style={{
                animation: `daemon-card-pulse ${pulseDuration.toFixed(2)}s ease-in-out infinite`,
                ['--daemon-border-idle' as string]: borderIdle,
                ['--daemon-border-pulse' as string]: borderActive,
                ['--daemon-pulse-color-idle' as string]: glowIdle,
                ['--daemon-pulse-color-active' as string]: glowActive,
                ['--daemon-glow-blur-idle' as string]: '4px',
                ['--daemon-glow-blur-pulse' as string]: `${glowBlurMax}px`,
                ['--daemon-bg-idle' as string]: '#111111',
                ['--daemon-bg-pulse' as string]: '#151518',
              } as React.CSSProperties}
              className="relative p-5 rounded-3xl flex flex-col justify-between overflow-hidden group transition-all"
            >
              {/* Radial ambient glow backdrop that pulsates with active load intensity */}
              <div
                className="absolute -top-10 -right-10 w-36 h-36 rounded-full pointer-events-none blur-2xl transition-all duration-700"
                style={{
                  background: `radial-gradient(circle, ${glowActive} 0%, transparent 70%)`,
                  opacity: 0.25 + loadIntensity * 0.5,
                }}
              />

              <div>
                <div className="flex items-center justify-between mb-3 relative z-10">
                  <div className="flex items-center gap-2.5">
                    {/* Live Beacon Indicator with dynamic pulse speed */}
                    <div className="relative flex items-center justify-center w-3 h-3">
                      <span
                        className="absolute inline-flex h-full w-full rounded-full opacity-75"
                        style={{
                          backgroundColor: d.color,
                          animation: `daemon-beacon-ring ${pulseDuration.toFixed(2)}s cubic-bezier(0, 0, 0.2, 1) infinite`,
                        }}
                      />
                      <span
                        className="relative inline-flex rounded-full h-2 w-2"
                        style={{
                          backgroundColor: d.color,
                          boxShadow: `0 0 ${Math.round(6 + loadIntensity * 10)}px ${d.color}`,
                        }}
                      />
                    </div>
                    <span className="font-medium text-sm text-white">{d.name}</span>
                  </div>

                  {/* Thread Activity Metric & Live Adjust Controls */}
                  <div className="flex items-center gap-1.5">
                    <div className="flex items-center gap-1 font-code-sm text-xs text-white/60">
                      {/* Thread activity spark bars */}
                      <div className="flex items-end gap-0.5 h-3 mr-1">
                        {[0.4, 0.9, 0.6, 1.0].map((multiplier, barIdx) => (
                          <div
                            key={barIdx}
                            className="w-0.5 rounded-full"
                            style={{
                              backgroundColor: d.color,
                              height: `${Math.max(25, Math.min(100, (threads / 6) * 100 * multiplier))}%`,
                              animation: `daemon-thread-spark ${pulseDuration.toFixed(2)}s ease-in-out infinite`,
                              animationDelay: `${barIdx * 0.12}s`,
                            }}
                          />
                        ))}
                      </div>
                      <span>{threads} Th</span>
                    </div>

                    {/* Interactive Thread Controls */}
                    <div className="flex items-center gap-0.5 ml-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => adjustThreads(d.name, -1)}
                        className="w-4 h-4 rounded-full bg-white/10 hover:bg-white/20 text-white/70 hover:text-white flex items-center justify-center text-[10px] cursor-pointer"
                        title="Reduce thread"
                      >
                        -
                      </button>
                      <button
                        onClick={() => adjustThreads(d.name, 1)}
                        className="w-4 h-4 rounded-full bg-white/10 hover:bg-white/20 text-white/70 hover:text-white flex items-center justify-center text-[10px] cursor-pointer"
                        title="Add thread"
                      >
                        +
                      </button>
                    </div>
                  </div>
                </div>

                <div className="relative z-10">
                  <div className="flex justify-between items-baseline mb-1.5 font-code-sm">
                    <span className="text-xs text-white/40">Load Capacity</span>
                    <div className="flex items-baseline gap-1.5">
                      <span
                        className="text-base font-semibold"
                        style={{ color: isHigh ? '#E5A93C' : d.color }}
                      >
                        {d.loadPercent}%
                      </span>
                    </div>
                  </div>
                  <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${d.loadPercent}%`,
                        backgroundColor: isHigh ? '#E5A93C' : d.color,
                        boxShadow: `0 0 ${Math.round(4 + loadIntensity * 8)}px ${isHigh ? '#E5A93C' : d.color}`,
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Card Footer: RAM and Dynamic Pulse Telemetry */}
              <div className="mt-3 pt-2.5 border-t border-white/5 flex justify-between items-center font-code-sm text-[10px] text-white/40 relative z-10">
                <span>RAM: {d.memoryUsage}</span>
                <span className="flex items-center gap-1">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: d.color }}
                  />
                  <span style={{ color: d.color }}>{frequencyHz} Hz • {pulseDuration.toFixed(2)}s</span>
                </span>
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
