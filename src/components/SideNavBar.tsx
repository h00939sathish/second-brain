import React from 'react';
import { ASSETS } from '../data/initialData';
import { NavigationTab } from '../types';

interface SideNavBarProps {
  currentTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  onOpenDeployModal: () => void;
  onOpenDocs: () => void;
  onOpenSupport: () => void;
  brandVariant: 'secondBrain' | 'antigravity';
  activeAgentsCount: number;
}

export const SideNavBar: React.FC<SideNavBarProps> = ({
  currentTab,
  onSelectTab,
  onOpenDeployModal,
  onOpenDocs,
  onOpenSupport,
  brandVariant,
}) => {
  const navItems = [
    {
      tab: 'kanban' as NavigationTab,
      label: 'Kanban Board',
      icon: 'view_kanban',
    },
    {
      tab: 'workflow' as NavigationTab,
      label: 'Workflow Orchestrator',
      icon: 'account_tree',
    },
    {
      tab: 'telemetry' as NavigationTab,
      label: 'Token Telemetry',
      icon: 'monitoring',
    },
    {
      tab: 'graph' as NavigationTab,
      label: 'Knowledge Graph',
      icon: 'hub',
    },
    {
      tab: 'logs' as NavigationTab,
      label: 'Live Terminal Logs',
      icon: 'terminal',
    },
    {
      tab: 'specs' as NavigationTab,
      label: 'Specs',
      icon: 'description',
    },
    {
      tab: 'network' as NavigationTab,
      label: 'Network',
      icon: 'device_hub',
    },
  ];

  return (
    <aside className="fixed left-0 top-16 bottom-0 w-64 z-40 flex flex-col bg-[#050505] border-r border-white/10 hidden md:flex select-none">
      {/* Daemon Status Card */}
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center gap-3 p-3 bg-[#111111] border border-white/10 rounded-2xl">
          <div className="w-10 h-10 rounded-full bg-[#181818] border border-white/15 flex items-center justify-center text-[#C9A86A] relative overflow-hidden shrink-0">
            <img 
              src={ASSETS.logoAvatar} 
              alt="System Avatar" 
              className="w-full h-full object-cover rounded-full" 
            />
            <div className="absolute inset-0 bg-[#C9A86A]/10 animate-pulse pointer-events-none"></div>
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium text-white uppercase tracking-[0.15em] leading-tight truncate">
              {brandVariant === 'secondBrain' ? 'Daemon Engine' : 'Core Engine'}
            </div>
            <div className="font-code-sm text-[10px] text-white/50 flex items-center gap-1.5 mt-1 tracking-wider">
              <span className="w-1.5 h-1.5 rounded-full bg-[#C9A86A] shadow-[0_0_6px_#C9A86A] animate-pulse"></span>
              <span>Status: Nominal</span>
            </div>
          </div>
        </div>

        <button
          onClick={onOpenDeployModal}
          className="mt-3 w-full py-2 px-3 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full text-[10px] uppercase tracking-[0.2em] flex items-center justify-center gap-2 transition-all shadow-[0_0_15px_rgba(201,168,106,0.2)] group cursor-pointer"
        >
          <span className="material-symbols-outlined text-[16px] group-hover:scale-110 transition-transform">rocket_launch</span>
          Deploy Agent
        </button>
      </div>

      {/* Nav List */}
      <div className="flex-1 overflow-y-auto px-3 py-4 space-y-1.5">
        {navItems.map((item) => {
          const isActive = currentTab === item.tab;
          return (
            <button
              key={item.tab}
              onClick={() => onSelectTab(item.tab)}
              className={`w-full flex items-center gap-3.5 px-4 py-2.5 rounded-full text-[10px] uppercase tracking-[0.2em] transition-all text-left group cursor-pointer ${
                isActive
                  ? 'bg-white/10 text-white border border-white/20 font-medium shadow-sm backdrop-blur-md'
                  : 'text-white/40 hover:text-white hover:bg-white/5 border border-transparent'
              }`}
            >
              <span 
                className={`material-symbols-outlined text-[18px] transition-colors ${
                  isActive ? 'text-[#C9A86A]' : 'text-white/40 group-hover:text-white'
                }`}
                style={{ fontVariationSettings: isActive ? "'FILL' 1" : "'FILL' 0" }}
              >
                {item.icon}
              </span>
              <span>{item.label}</span>
              {isActive && (
                <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#C9A86A] shadow-[0_0_6px_#C9A86A]"></span>
              )}
            </button>
          );
        })}
      </div>

      {/* Footer Navigation */}
      <div className="mt-auto px-4 py-4 border-t border-white/10 space-y-1.5 bg-[#080808]">
        <div className="px-3.5 py-2 mb-2 bg-[#111111] rounded-xl border border-white/5 flex items-center justify-between font-code-sm text-[9px] uppercase tracking-widest text-white/40">
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 bg-[#C9A86A] rounded-full animate-pulse"></div>
            <span>Daemon Pulse</span>
          </div>
          <span className="text-white/80 font-semibold">14d 02h</span>
        </div>

        <button
          onClick={onOpenDocs}
          className="w-full flex items-center gap-3 px-3.5 py-2 text-white/40 hover:text-white hover:bg-white/5 rounded-full text-[10px] uppercase tracking-[0.2em] transition-all text-left"
        >
          <span className="material-symbols-outlined text-[16px] text-white/40">menu_book</span>
          <span>Docs</span>
        </button>

        <button
          onClick={onOpenSupport}
          className="w-full flex items-center gap-3 px-3.5 py-2 text-white/40 hover:text-white hover:bg-white/5 rounded-full text-[10px] uppercase tracking-[0.2em] transition-all text-left"
        >
          <span className="material-symbols-outlined text-[16px] text-white/40">support_agent</span>
          <span>Support</span>
        </button>
      </div>
    </aside>
  );
};
