import React from 'react';
import { ASSETS } from '../data/initialData';
import { NavigationTab } from '../types';

interface TopAppBarProps {
  currentTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  onOpenSearch: () => void;
  onOpenSettings: () => void;
  onOpenNotifications: () => void;
  daemon: { active: boolean; detail: string };
  workspaces: string[];
  workspace: string;
  onSelectWorkspace: (workspace: string) => void;
  brandVariant: 'secondBrain' | 'antigravity';
}

export const TopAppBar: React.FC<TopAppBarProps> = ({
  currentTab,
  onSelectTab,
  onOpenSearch,
  onOpenSettings,
  onOpenNotifications,
  daemon,
  workspaces,
  workspace,
  onSelectWorkspace,
  brandVariant,
}) => {
  return (
    <header className="fixed top-0 left-0 right-0 h-16 z-50 bg-[#050505]/90 backdrop-blur-md border-b border-white/10 flex items-center justify-between px-4 md:px-8">
      {/* Brand & Active status */}
      <div className="flex items-center gap-4 md:gap-6">
        <div 
          className="flex items-center gap-3 cursor-pointer group"
          onClick={() => onSelectTab('telemetry')}
        >
          {brandVariant === 'secondBrain' ? (
            <div className="w-9 h-9 rounded-full bg-[#121212] border border-[#C9A86A]/40 flex items-center justify-center text-[#C9A86A] shadow-[0_0_15px_rgba(201,168,106,0.15)] group-hover:border-[#C9A86A] transition-all">
              <span className="material-symbols-outlined text-[19px]">memory</span>
            </div>
          ) : (
            <div className="w-9 h-9 rounded-full bg-[#121212] border border-white/20 flex items-center justify-center text-white shadow-[0_0_15px_rgba(255,255,255,0.1)] group-hover:border-white transition-all">
              <span className="material-symbols-outlined text-[19px]">rocket_launch</span>
            </div>
          )}
          <div className="flex flex-col">
            <span className="font-light text-sm md:text-base tracking-[0.15em] uppercase text-white group-hover:text-[#C9A86A] transition-colors">
              {brandVariant === 'secondBrain' ? 'Second Brain' : 'Antigravity'}
            </span>
            <span className="text-[9px] uppercase tracking-[0.25em] text-white/40 -mt-0.5">
              Mission Control
            </span>
          </div>
        </div>

        {/* Daemon state comes from the daemon's own heartbeat file. */}
        <div
          className="hidden sm:flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-white/[0.04] border border-white/10 backdrop-blur-sm"
          title={daemon.detail}
        >
          <div className="relative flex items-center justify-center w-2 h-2">
            {daemon.active && (
              <div className="absolute w-full h-full bg-[#C9A86A] rounded-full opacity-50 pulse-ring"></div>
            )}
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                daemon.active
                  ? 'bg-[#C9A86A] shadow-[0_0_8px_#C9A86A]'
                  : 'bg-white/30'
              }`}
            ></div>
          </div>
          <span className="font-code-sm text-[11px] text-white/70 tracking-wider">
            Daemon: {daemon.active ? 'Active' : 'Stopped'}
          </span>
        </div>

        {/* Workspace scope: which slice of the vault this view is showing. */}
        <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/[0.04] border border-white/10">
          <span className="material-symbols-outlined text-white/40 text-[15px]">folder_open</span>
          <select
            value={workspace}
            onChange={(e) => onSelectWorkspace(e.target.value)}
            title="Scope every view to one workspace"
            className="bg-transparent font-code-sm text-[11px] text-white/80 tracking-wider outline-none cursor-pointer"
          >
            <option value="" className="bg-[#111111]">
              all workspaces
            </option>
            {workspaces.map((slug) => (
              <option key={slug} value={slug} className="bg-[#111111]">
                {slug}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Center Search Input (Desktop) */}
      <div className="hidden md:flex flex-1 max-w-sm mx-6">
        <div 
          onClick={onOpenSearch}
          className="w-full relative cursor-pointer group flex items-center bg-[#111111] border border-white/10 hover:border-white/25 rounded-full px-4 py-2 transition-all shadow-inner"
        >
          <span className="material-symbols-outlined text-white/40 text-[16px] mr-2.5 group-hover:text-[#C9A86A] transition-colors">search</span>
          <span className="font-code-sm text-[11px] text-white/40 group-hover:text-white/70 tracking-wide">
            Search operations or telemetry...
          </span>
          <span className="ml-auto font-code-sm text-[9px] uppercase tracking-widest px-2 py-0.5 rounded-full bg-white/10 text-white/60 border border-white/10">⌘K</span>
        </div>
      </div>

      {/* Right Action Icons */}
      <div className="flex items-center gap-2 md:gap-3">
        <button
          onClick={onOpenSearch}
          className="md:hidden p-2 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors"
          title="Search"
        >
          <span className="material-symbols-outlined text-[20px]">search</span>
        </button>

        <button
          onClick={onOpenNotifications}
          className="relative p-2 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors"
          title="Notifications"
        >
          <span className="material-symbols-outlined text-[20px]">notifications</span>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#C9A86A] shadow-[0_0_6px_#C9A86A]"></span>
        </button>

        <button
          onClick={() => onSelectTab('logs')}
          className={`p-2 rounded-full transition-all ${
            currentTab === 'logs' 
              ? 'text-[#C9A86A] bg-[#C9A86A]/15 border border-[#C9A86A]/40' 
              : 'hover:bg-white/10 text-white/70 hover:text-white border border-transparent'
          }`}
          title="Terminal Logs"
        >
          <span className="material-symbols-outlined text-[20px]">terminal</span>
        </button>

        <button
          onClick={onOpenSettings}
          className="p-2 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors"
          title="Settings"
        >
          <span className="material-symbols-outlined text-[20px]">settings</span>
        </button>

        {/* Profile Avatar */}
        <div 
          onClick={onOpenSettings}
          className="w-9 h-9 rounded-full border border-white/20 hover:border-[#C9A86A] overflow-hidden cursor-pointer transition-all ml-1 shrink-0 p-0.5 bg-white/5"
          title="Operator Profile"
        >
          <img
            src={ASSETS.userAvatar}
            alt="Operator Profile"
            className="w-full h-full object-cover rounded-full"
          />
        </div>
      </div>
    </header>
  );
};
