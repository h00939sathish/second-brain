import React, { useState } from 'react';
import { NavigationTab, KanbanTask } from '../types';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate?: (tab: NavigationTab) => void;
  tasks?: KanbanTask[];
  onSelectTask?: (task: KanbanTask) => void;
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  onNavigate,
  tasks = [],
  onSelectTask,
}) => {
  const [query, setQuery] = useState('');

  if (!isOpen) return null;

  const quickActions = [
    { title: 'Inspect Active Kanban Tasks & Leases', tab: 'kanban' as NavigationTab, icon: 'view_kanban', desc: 'Board columns, active task states' },
    { title: 'Workflow Orchestrator & Pipeline', tab: 'workflow' as NavigationTab, icon: 'account_tree', desc: 'Multi-agent sequential stages' },
    { title: 'View Token Telemetry & Model Breakdown', tab: 'telemetry' as NavigationTab, icon: 'monitoring', desc: 'Live inference costs & token burn' },
    { title: 'Explore Knowledge Graph & Truth Claims', tab: 'graph' as NavigationTab, icon: 'hub', desc: 'Topological specs & verified claims' },
    { title: 'Tail Live Terminal Logs (/var/log)', tab: 'logs' as NavigationTab, icon: 'terminal', desc: 'Streaming daemon events & errors' },
    { title: 'Edit Unified Component Architecture Spec', tab: 'specs' as NavigationTab, icon: 'description', desc: 'System specs and ADR blueprints' },
    { title: 'System Load Balancer & Daemon Capacity', tab: 'network' as NavigationTab, icon: 'device_hub', desc: 'Regional routing & thread telemetry' },
  ];

  const filteredActions = quickActions.filter((a) =>
    a.title.toLowerCase().includes(query.toLowerCase()) ||
    a.desc.toLowerCase().includes(query.toLowerCase()) ||
    a.tab.toLowerCase().includes(query.toLowerCase())
  );

  const filteredTasks = tasks.filter((t) =>
    t.title.toLowerCase().includes(query.toLowerCase()) ||
    t.id.toLowerCase().includes(query.toLowerCase()) ||
    t.tags.some((tag) => tag.toLowerCase().includes(query.toLowerCase()))
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-xl bg-[#111111] border border-white/10 rounded-3xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="p-4 border-b border-white/10 flex items-center gap-3">
          <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">search</span>
          <input
            type="text"
            autoFocus
            placeholder="Type a view name, command, or task ID (e.g. kanban, graph, t-)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent border-none text-white font-code-sm text-sm focus:outline-none placeholder:text-white/40"
          />
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white px-2 py-1 rounded-full border border-white/10 font-code-sm text-[11px] cursor-pointer transition-colors"
          >
            ESC
          </button>
        </div>

        <div className="p-3 max-h-80 overflow-y-auto space-y-3">
          {/* Views & Navigation */}
          {filteredActions.length > 0 && (
            <div>
              <div className="px-2 pb-1.5 text-[10px] text-white/40 uppercase tracking-widest font-code-sm">
                Views & Actions
              </div>
              <div className="space-y-1">
                {filteredActions.map((action) => (
                  <button
                    key={action.title}
                    onClick={() => {
                      onNavigate?.(action.tab);
                      onClose();
                    }}
                    className="w-full p-2.5 rounded-2xl hover:bg-white/5 text-left flex items-center justify-between text-xs font-code-sm text-white/70 hover:text-white transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-[#C9A86A] text-[18px]">
                        {action.icon}
                      </span>
                      <div>
                        <div className="text-white/90 font-medium">{action.title}</div>
                        <div className="text-[10px] text-white/40">{action.desc}</div>
                      </div>
                    </div>
                    <span className="text-white/30 text-[10px] uppercase tracking-wider group-hover:text-[#C9A86A]">
                      {action.tab}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Matching Tasks */}
          {query.trim() && filteredTasks.length > 0 && (
            <div>
              <div className="px-2 pb-1.5 text-[10px] text-[#C9A86A] uppercase tracking-widest font-code-sm">
                Matching Tasks ({filteredTasks.length})
              </div>
              <div className="space-y-1">
                {filteredTasks.slice(0, 5).map((task) => (
                  <button
                    key={task.id}
                    onClick={() => {
                      onSelectTask?.(task);
                      onClose();
                    }}
                    className="w-full p-2.5 bg-[#161616] border border-white/5 hover:border-white/20 rounded-2xl text-left flex items-center justify-between text-xs font-code-sm text-white/80 hover:text-white transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5 truncate">
                      <span className="px-1.5 py-0.5 rounded-full bg-white/10 text-[9px] uppercase font-semibold text-[#C9A86A]">
                        {task.id}
                      </span>
                      <span className="truncate">{task.title}</span>
                    </div>
                    <span className="text-[10px] text-white/40 capitalize ml-2 shrink-0">{task.status}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {filteredActions.length === 0 && filteredTasks.length === 0 && (
            <div className="p-6 text-center text-xs font-code-sm text-white/40">
              No matching records found for "{query}".
            </div>
          )}
        </div>

        <div className="p-3.5 bg-[#161616] border-t border-white/10 flex items-center justify-between text-[10px] font-code-sm text-white/40">
          <span>Click to select or navigate</span>
          <span>Press ESC to exit</span>
        </div>
      </div>
    </div>
  );
};
