import React, { useState, useEffect } from 'react';
import { KanbanTask } from '../types';

interface CreateTaskModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAddTask: (task: KanbanTask) => void;
}

export const CreateTaskModal: React.FC<CreateTaskModalProps> = ({
  isOpen,
  onClose,
  onAddTask,
}) => {
  const [title, setTitle] = useState('');
  const [daemon, setDaemon] = useState<'Cx' | 'op' | 'Cl' | 'Ag'>('Cx');
  const [specLink, setSpecLink] = useState('');
  const [tag, setTag] = useState('Project TITAN');
  const [description, setDescription] = useState('');
  const [availableSpecs, setAvailableSpecs] = useState<{ id: string; title: string; project: string }[]>([]);

  useEffect(() => {
    if (isOpen) {
      fetch('/api/specs')
        .then((res) => res.json())
        .then((data) => {
          if (Array.isArray(data)) {
            setAvailableSpecs(data);
            if (data.length > 0 && !specLink) {
              setSpecLink(data[0].id);
              if (data[0].project) {
                setTag(data[0].project);
              }
            }
          }
        })
        .catch(() => null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const daemonMap = {
    Cx: { code: 'Cx', name: 'Codex (Planner)', color: '#22d3ee' },
    op: { code: 'op', name: 'opencode (Builder)', color: '#10b981' },
    Cl: { code: 'Cl', name: 'Claude (Builder)', color: '#ec6a06' },
    Ag: { code: 'Ag', name: 'Antigravity (Reviewer)', color: '#d0bcff' },
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title) return;

    const newTask: KanbanTask = {
      id: `t-${Date.now().toString().slice(-8)}`,
      title,
      status: 'backlog',
      assignee: daemonMap[daemon],
      uptime: 'Just created',
      tags: [tag],
      specLink: specLink || undefined,
      description,
      tokenCost: 0.012,
      createdAt: new Date().toISOString(),
    };

    onAddTask(newTask);
    setTitle('');
    setDescription('');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-md bg-[#111111] border border-white/10 rounded-3xl shadow-2xl p-6 relative">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">add_task</span>
            <h2 className="text-base font-light text-white">Create Pipeline Task</h2>
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
            <label className="block text-white/60 mb-1.5 font-medium">Task Directive</label>
            <input
              type="text"
              required
              placeholder="e.g. Optimize vector token caching..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-white/60 mb-1.5 font-medium">Assign Daemon</label>
              <select
                value={daemon}
                onChange={(e) => setDaemon(e.target.value as any)}
                className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
              >
                <option value="Cx">Codex (Planner)</option>
                <option value="op">opencode (Builder)</option>
                <option value="Cl">Claude (Builder)</option>
                <option value="Ag">Antigravity (Reviewer)</option>
              </select>
            </div>

            <div>
              <label className="block text-white/60 mb-1.5 font-medium">Spec Link</label>
              <select
                value={specLink}
                onChange={(e) => {
                  setSpecLink(e.target.value);
                  const found = availableSpecs.find((s) => s.id === e.target.value);
                  if (found && found.project) setTag(found.project);
                }}
                className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] transition-colors"
              >
                <option value="">None / Standalone</option>
                {availableSpecs.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id}: {s.title.slice(0, 24)}...
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-white/60 mb-1.5 font-medium">Task Scope / Description</label>
            <textarea
              rows={3}
              placeholder="Provide context or requirements for autonomous daemon execution..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-white focus:outline-none focus:border-[#C9A86A] resize-none transition-colors"
            />
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
              Enqueue Task
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export const DocsSupportModal: React.FC<{
  type: 'docs' | 'support' | null;
  onClose: () => void;
}> = ({ type, onClose }) => {
  if (!type) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-md bg-[#111111] border border-white/10 rounded-3xl shadow-2xl p-6 relative">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">
              {type === 'docs' ? 'menu_book' : 'support_agent'}
            </span>
            <h2 className="text-base font-light text-white">
              {type === 'docs' ? 'Mission Control Architecture Manual' : 'Daemon Cluster Support'}
            </h2>
          </div>
          <button onClick={onClose} className="text-white/40 hover:text-white p-1 rounded-full cursor-pointer transition-colors">
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        {type === 'docs' ? (
          <div className="space-y-3 font-code-sm text-xs text-white/70">
            <p>
              Welcome to the <strong className="text-[#C9A86A]">Second Brain Mission Control</strong> documentation.
            </p>
            <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl space-y-1.5 text-[11px]">
              <div className="text-[#C9A86A] font-semibold">Key Architectural Concepts:</div>
              <div>• <strong>Autonomous Daemons:</strong> Codex, Claude, and Opencode sync over RPC.</div>
              <div>• <strong>File Leases:</strong> Prevents concurrent destructive AST mutations.</div>
              <div>• <strong>Truth Claims:</strong> Graph-linked formal assertions and unit proofs.</div>
            </div>
          </div>
        ) : (
          <div className="space-y-3 font-code-sm text-xs text-white/70">
            <p>
              Operator diagnostics and real-time support hotline:
            </p>
            <div className="p-4 bg-[#161616] border border-white/5 rounded-2xl space-y-1.5 text-[11px]">
              <div>• <strong>Channel:</strong> #antigravity-mission-control (Internal Slack)</div>
              <div>• <strong>Direct RPC:</strong> rpc.missioncontrol.internal:9090</div>
              <div>• <strong>Security Vault:</strong> PGP Key 0x8F9A2B</div>
            </div>
          </div>
        )}

        <div className="flex justify-end pt-4 mt-4 border-t border-white/10">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-full bg-[#C9A86A] text-black font-semibold text-xs hover:bg-[#dfc188] cursor-pointer transition-all shadow-[0_0_10px_rgba(201,168,106,0.25)]"
          >
            Acknowledge
          </button>
        </div>
      </div>
    </div>
  );
};
