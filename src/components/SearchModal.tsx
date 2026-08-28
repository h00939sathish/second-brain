import React, { useState } from 'react';
import { NavigationTab } from '../types';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (tab: NavigationTab) => void;
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  onNavigate,
}) => {
  const [query, setQuery] = useState('');

  if (!isOpen) return null;

  const quickActions = [
    { title: 'View Token Telemetry & Model Breakdown', tab: 'telemetry' as NavigationTab, icon: 'monitoring' },
    { title: 'Inspect Active Kanban Tasks & Leases', tab: 'kanban' as NavigationTab, icon: 'view_kanban' },
    { title: 'Explore Knowledge Graph & Truth Claims', tab: 'graph' as NavigationTab, icon: 'hub' },
    { title: 'Tail Live Terminal Logs (/var/log)', tab: 'logs' as NavigationTab, icon: 'terminal' },
    { title: 'Edit Unified Component Architecture Spec', tab: 'specs' as NavigationTab, icon: 'description' },
    { title: 'System Load Balancer & Daemon Capacity', tab: 'network' as NavigationTab, icon: 'device_hub' },
  ];

  const filtered = quickActions.filter((a) =>
    a.title.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-xl bg-[#111111] border border-white/10 rounded-3xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="p-4 border-b border-white/10 flex items-center gap-3">
          <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">search</span>
          <input
            type="text"
            autoFocus
            placeholder="Type a command, task ID, or search views..."
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

        <div className="p-3 max-h-72 overflow-y-auto space-y-1.5">
          {filtered.map((action) => (
            <button
              key={action.title}
              onClick={() => {
                onNavigate(action.tab);
                onClose();
              }}
              className="w-full p-3 rounded-2xl hover:bg-white/5 text-left flex items-center justify-between text-xs font-code-sm text-white/70 hover:text-white transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-[#C9A86A] text-[18px]">
                  {action.icon}
                </span>
                <span>{action.title}</span>
              </div>
              <span className="text-white/30 text-[10px] uppercase tracking-wider">{action.tab}</span>
            </button>
          ))}

          {filtered.length === 0 && (
            <div className="p-6 text-center text-xs font-code-sm text-white/40">
              No matching records found for "{query}".
            </div>
          )}
        </div>

        <div className="p-3.5 bg-[#161616] border-t border-white/10 flex items-center justify-between text-[10px] font-code-sm text-white/40">
          <span>Navigate with arrows or click</span>
          <span>Press ESC to exit</span>
        </div>
      </div>
    </div>
  );
};
