import React, { useState } from 'react';

interface DeployAgentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDeploy: (agent: { name: string; model: string; threadLimit: number; memoryLimit: string }) => void;
}

export const DeployAgentModal: React.FC<DeployAgentModalProps> = ({
  isOpen,
  onClose,
  onDeploy,
}) => {
  const [agentName, setAgentName] = useState('');
  const [model, setModel] = useState('Antigravity-v2');
  const [threadLimit, setThreadLimit] = useState(4);
  const [memoryLimit, setMemoryLimit] = useState('4GB');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentName) return;
    onDeploy({
      name: agentName,
      model,
      threadLimit,
      memoryLimit,
    });
    setAgentName('');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-md bg-[#111111] border border-white/10 rounded-3xl shadow-2xl p-6 relative">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">rocket_launch</span>
            <h2 className="text-base font-light text-white">Deploy New Daemon Agent</h2>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white p-1 rounded-full cursor-pointer transition-colors"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 font-code-sm text-xs">
          <div>
            <label className="block text-white/60 mb-1.5 font-medium">Agent Daemon Name</label>
            <input
              type="text"
              required
              placeholder="e.g. Codex-Synthesizer-02"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
            />
          </div>

          <div>
            <label className="block text-white/60 mb-1.5 font-medium">Model Architecture</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
            >
              <option value="Antigravity-v2">Antigravity Core v2 (High-throughput)</option>
              <option value="Codex-5.6">Codex 5.6 (Code Synthesis)</option>
              <option value="Claude-3.7-Sonnet">Claude 3.7 Sonnet (Reasoning & AST)</option>
              <option value="Gemini-2.5-Flash">Gemini 2.5 Flash (Ultra low-latency)</option>
              <option value="Local-LLaMA-3">Local LLaMA 3 (Offline / Vault)</option>
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-white/60 mb-1.5 font-medium">Thread Limit</label>
              <input
                type="number"
                min="1"
                max="16"
                value={threadLimit}
                onChange={(e) => setThreadLimit(Number(e.target.value))}
                className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
              />
            </div>
            <div>
              <label className="block text-white/60 mb-1.5 font-medium">Max Memory</label>
              <select
                value={memoryLimit}
                onChange={(e) => setMemoryLimit(e.target.value)}
                className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
              >
                <option value="2GB">2 GB</option>
                <option value="4GB">4 GB</option>
                <option value="8GB">8 GB</option>
                <option value="16GB">16 GB</option>
              </select>
            </div>
          </div>

          <div className="p-3 bg-[#161616] border border-white/5 rounded-2xl text-[11px] text-white/60 flex items-center gap-2">
            <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">info</span>
            Agent will bind to local RPC socket and register into load balancer cluster.
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-full bg-[#161616] border border-white/10 text-white/60 hover:text-white cursor-pointer transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 rounded-full bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold shadow-[0_0_12px_rgba(201,168,106,0.25)] transition-all cursor-pointer"
            >
              Launch Daemon
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
