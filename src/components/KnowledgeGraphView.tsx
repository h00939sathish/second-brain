import React, { useState } from 'react';
import { GraphNode } from '../types';

interface KnowledgeGraphViewProps {
  nodes: GraphNode[];
  onSelectNode?: (node: GraphNode) => void;
}

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({
  nodes,
  onSelectNode,
}) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>('spec-01');
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [filterType, setFilterType] = useState<string>('ALL');

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);

  const filteredNodes = nodes.filter((n) => {
    if (filterType === 'ALL') return true;
    return n.type === filterType.toLowerCase();
  });

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-light tracking-tight text-white">
            Knowledge Graph & Truth Mapping
          </h1>
          <p className="font-code-sm text-xs text-white/40 mt-1">
            Topological graph connecting specs, autonomous tasks, and verifiable claims.
          </p>
        </div>

        {/* Graph Legend & Filter */}
        <div className="flex flex-wrap items-center gap-1.5 bg-[#111111] border border-white/10 p-1.5 rounded-full font-code-sm text-xs">
          <button
            onClick={() => setFilterType('ALL')}
            className={`px-3 py-1 rounded-full transition-all cursor-pointer ${
              filterType === 'ALL'
                ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            All ({nodes.length})
          </button>
          <button
            onClick={() => setFilterType('spec')}
            className={`px-3 py-1 rounded-full flex items-center gap-1.5 transition-all cursor-pointer ${
              filterType === 'spec'
                ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-[#C9A86A]"></span>
            Specs
          </button>
          <button
            onClick={() => setFilterType('task')}
            className={`px-3 py-1 rounded-full flex items-center gap-1.5 transition-all cursor-pointer ${
              filterType === 'task'
                ? 'bg-white text-black font-semibold shadow-[0_0_8px_rgba(255,255,255,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-white"></span>
            Tasks
          </button>
          <button
            onClick={() => setFilterType('claim')}
            className={`px-3 py-1 rounded-full flex items-center gap-1.5 transition-all cursor-pointer ${
              filterType === 'claim'
                ? 'bg-[#4ADE80] text-black font-semibold shadow-[0_0_8px_rgba(74,222,128,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-[#4ADE80]"></span>
            Claims
          </button>
        </div>
      </div>

      {/* Main Grid: 2/3 Graph Canvas, 1/3 Phased Roadmap & Info */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Graph Canvas (Spans 2 cols on xl) */}
        <div className="xl:col-span-2 bg-[#090909] border border-white/10 rounded-3xl relative min-h-[520px] flex flex-col overflow-hidden bg-grid-pattern">
          {/* Canvas Floating Controls */}
          <div className="absolute top-4 left-4 z-20 flex items-center gap-2 bg-[#111111]/90 backdrop-blur border border-white/10 rounded-full px-3 py-1.5 text-xs font-code-sm">
            <span className="text-[#C9A86A] font-medium">Topology:</span>
            <span className="text-white/70">{nodes.length} Nodes</span>
          </div>

          <div className="absolute top-4 right-4 z-20 flex items-center gap-1 bg-[#111111]/90 backdrop-blur border border-white/10 rounded-full p-1">
            <button
              onClick={() => setZoomLevel((z) => Math.min(z + 0.15, 1.6))}
              className="p-1.5 text-white/60 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
              title="Zoom In"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
            </button>
            <button
              onClick={() => setZoomLevel(1)}
              className="px-2 text-xs font-code-sm text-white/40 hover:text-white cursor-pointer"
            >
              {Math.round(zoomLevel * 100)}%
            </button>
            <button
              onClick={() => setZoomLevel((z) => Math.max(z - 0.15, 0.6))}
              className="p-1.5 text-white/60 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
              title="Zoom Out"
            >
              <span className="material-symbols-outlined text-[16px]">remove</span>
            </button>
          </div>

          {/* Interactive SVG Canvas */}
          <div className="flex-1 w-full h-full relative overflow-auto p-4 flex items-center justify-center">
            <svg
              className="w-[800px] h-[550px] transition-transform duration-200"
              style={{ transform: `scale(${zoomLevel})` }}
            >
              {/* Render Connection Lines */}
              {nodes.map((node) =>
                node.connections.map((targetId) => {
                  const target = nodes.find((n) => n.id === targetId);
                  if (!target) return null;
                  const isHighlighted =
                    selectedNodeId === node.id || selectedNodeId === targetId;

                  return (
                    <line
                      key={`${node.id}-${targetId}`}
                      x1={node.x}
                      y1={node.y}
                      x2={target.x}
                      y2={target.y}
                      stroke={isHighlighted ? '#C9A86A' : 'rgba(255,255,255,0.1)'}
                      strokeWidth={isHighlighted ? 2 : 1}
                      strokeDasharray={node.type === 'claim' ? '4 4' : undefined}
                      className="transition-colors duration-300"
                    />
                  );
                })
              )}

              {/* Render Node Circles & Labels */}
              {filteredNodes.map((node) => {
                const isSelected = selectedNodeId === node.id;
                const nodeColor =
                  node.type === 'spec'
                    ? '#C9A86A'
                    : node.type === 'task'
                    ? '#FFFFFF'
                    : '#4ADE80';

                return (
                  <g
                    key={node.id}
                    className="cursor-pointer group"
                    onClick={() => {
                      setSelectedNodeId(node.id);
                      onSelectNode?.(node);
                    }}
                  >
                    {/* Glow ring */}
                    {isSelected && (
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={24}
                        fill="none"
                        stroke={nodeColor}
                        strokeWidth="2"
                        className="animate-pulse opacity-60"
                      />
                    )}

                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={14}
                      fill="#111111"
                      stroke={nodeColor}
                      strokeWidth={isSelected ? 3 : 1.5}
                      className="group-hover:scale-110 transition-all duration-200"
                    />

                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={6}
                      fill={nodeColor}
                      className="transition-all"
                    />

                    {/* Node Text Label */}
                    <text
                      x={node.x}
                      y={node.y + 26}
                      textAnchor="middle"
                      className="font-code-sm text-[11px] fill-white/90 font-medium select-none pointer-events-none"
                    >
                      {node.label}
                    </text>

                    <text
                      x={node.x}
                      y={node.y + 38}
                      textAnchor="middle"
                      className="font-code-sm text-[9px] fill-white/40 uppercase select-none pointer-events-none"
                    >
                      {node.type} • {node.status}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        {/* Right Sidebar: Selected Node Details & Phased Roadmap */}
        <div className="space-y-4">
          {/* Selected Node Details Card */}
          {selectedNode && (
            <div className="bg-[#111111] border border-white/10 rounded-3xl p-5">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
                <span className="text-[10px] text-[#C9A86A] uppercase tracking-[0.2em] font-medium">
                  Node Inspector
                </span>
                <span className="font-code-sm text-xs px-2.5 py-0.5 rounded-full bg-white/10 text-white/90">
                  {selectedNode.id}
                </span>
              </div>

              <div className="space-y-2.5 font-code-sm text-xs">
                <div>
                  <span className="text-white/40">Label:</span>{' '}
                  <span className="text-white font-medium">{selectedNode.label}</span>
                </div>
                <div>
                  <span className="text-white/40">Category:</span>{' '}
                  <span className="text-[#C9A86A] uppercase font-semibold">{selectedNode.type}</span>
                </div>
                <div>
                  <span className="text-white/40">Status:</span>{' '}
                  <span className="text-[#4ADE80] capitalize">{selectedNode.status.replace('_', ' ')}</span>
                </div>
                <div>
                  <span className="text-white/40">Connections:</span>{' '}
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {selectedNode.connections.map((c) => (
                      <span
                        key={c}
                        onClick={() => setSelectedNodeId(c)}
                        className="px-2.5 py-0.5 bg-[#161616] hover:bg-white/10 border border-white/10 text-[#C9A86A] rounded-full cursor-pointer transition-colors"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Phased Roadmap */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-5">
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">alt_route</span>
                Phased Roadmap
              </span>
              <span className="font-code-sm text-xs text-[#4ADE80]">Phase 2 Active</span>
            </div>

            <div className="space-y-3 font-code-sm text-xs">
              {/* Phase 1 */}
              <div className="p-3.5 bg-[#161616] border border-[#4ADE80]/30 rounded-2xl flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-1.5 text-[#4ADE80] font-semibold">
                    <span className="material-symbols-outlined text-[16px]">check_circle</span>
                    Phase 1: Foundation
                  </div>
                  <p className="text-[11px] text-white/40 mt-1">
                    Core storage, schemas, baseline token monitoring.
                  </p>
                </div>
                <span className="text-[11px] font-semibold text-[#4ADE80]">100%</span>
              </div>

              {/* Phase 2 */}
              <div className="p-3.5 bg-[#161616] border border-[#C9A86A]/40 rounded-2xl shadow-[0_0_12px_rgba(201,168,106,0.1)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[#C9A86A] font-semibold">
                    <span className="material-symbols-outlined text-[16px] animate-spin">sync</span>
                    Phase 2: Integration
                  </div>
                  <span className="text-[11px] font-semibold text-[#C9A86A]">45%</span>
                </div>
                <p className="text-[11px] text-white/60 mt-1">
                  NLP parsing, task linking, multi-daemon synchronization.
                </p>
                <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden mt-2.5">
                  <div className="bg-[#C9A86A] h-full rounded-full" style={{ width: '45%' }}></div>
                </div>
              </div>

              {/* Phase 3 */}
              <div className="p-3.5 bg-[#161616] border border-white/5 rounded-2xl opacity-60">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-white/40 font-semibold">
                    <span className="material-symbols-outlined text-[16px]">hourglass_empty</span>
                    Phase 3: Deployment
                  </div>
                  <span className="text-[11px] font-semibold text-white/40">0%</span>
                </div>
                <p className="text-[11px] text-white/40 mt-1">
                  Multi-region mesh orchestration, auto-scaling daemons.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
