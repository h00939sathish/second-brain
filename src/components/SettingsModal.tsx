import React from 'react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  brandVariant: 'secondBrain' | 'antigravity';
  onToggleBrand: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  brandVariant,
  onToggleBrand,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-md bg-[#111111] border border-white/10 rounded-3xl shadow-2xl p-6 relative">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">tune</span>
            <h2 className="text-base font-light text-white">Mission Control Preferences</h2>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white p-1 rounded-full cursor-pointer transition-colors"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        <div className="space-y-4 font-code-sm text-xs">
          {/* Brand & Theme Title Switch */}
          <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl flex items-center justify-between">
            <div>
              <div className="text-white font-medium">Brand Persona</div>
              <div className="text-white/40 text-[11px]">Toggle between Second Brain & Antigravity</div>
            </div>
            <button
              onClick={onToggleBrand}
              className="px-3.5 py-1.5 bg-[#C9A86A]/15 border border-[#C9A86A]/40 text-[#C9A86A] font-semibold rounded-full hover:bg-[#C9A86A]/25 cursor-pointer transition-all"
            >
              {brandVariant === 'secondBrain' ? 'Second Brain' : 'Antigravity'}
            </button>
          </div>

          {/* Polling Interval */}
          <div>
            <label className="block text-white/60 mb-1.5 font-medium">Telemetry Polling Rate</label>
            <select className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors">
              <option value="1s">1 Second (Ultra-Realtime)</option>
              <option value="3s">3 Seconds (Standard)</option>
              <option value="10s">10 Seconds (Power-Saver)</option>
            </select>
          </div>

          {/* CRT scanline toggle */}
          <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl flex items-center justify-between">
            <div>
              <div className="text-white font-medium">CRT Overlay Shader</div>
              <div className="text-white/40 text-[11px]">Retro scanline and phosphor bloom effect</div>
            </div>
            <span className="text-[#4ADE80] font-semibold">Enabled</span>
          </div>

          {/* API Endpoint */}
          <div>
            <label className="block text-white/60 mb-1.5 font-medium">Daemon RPC Gateway</label>
            <input
              type="text"
              readOnly
              value="https://api.control.internal/v2/rpc"
              className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white/40 focus:outline-none"
            />
          </div>

          <div className="flex justify-end pt-4 border-t border-white/10">
            <button
              onClick={onClose}
              className="px-5 py-2 rounded-full bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold shadow-[0_0_10px_rgba(201,168,106,0.25)] cursor-pointer transition-all"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
