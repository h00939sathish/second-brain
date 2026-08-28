import React from 'react';

interface NotificationsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const NotificationsDrawer: React.FC<NotificationsDrawerProps> = ({
  isOpen,
  onClose,
}) => {
  if (!isOpen) return null;

  const alerts = [
    {
      id: 'a1',
      title: 'Approaching lease limit',
      desc: 'Task t-20260828-676466 lease has been held by opencode for >14h.',
      time: '5m ago',
      type: 'warning',
    },
    {
      id: 'a2',
      title: 'Codex spawned thread 4492',
      desc: 'Worker initiated for task segment 0x8AF in memory block 12.',
      time: '12m ago',
      type: 'info',
    },
    {
      id: 'a3',
      title: 'Vault backup completed',
      desc: 'AES-256 encrypted snapshot 2066B backed up to cloud vault.',
      time: '1h ago',
      type: 'success',
    },
  ];

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-sm bg-[#111111] border-l border-white/10 shadow-2xl flex flex-col animate-in slide-in-from-right duration-200">
      <div className="p-5 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">notifications</span>
          <h2 className="text-sm font-medium text-white">Mesh Alert Center</h2>
        </div>
        <button
          onClick={onClose}
          className="text-white/40 hover:text-white p-1 rounded-full cursor-pointer transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]">close</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-3 font-code-sm text-xs">
        {alerts.map((a) => (
          <div
            key={a.id}
            className="p-4 bg-[#161616] border border-white/5 rounded-2xl space-y-1.5 hover:border-white/20 transition-colors"
          >
            <div className="flex items-center justify-between">
              <span
                className={`font-semibold ${
                  a.type === 'warning'
                    ? 'text-[#E5A93C]'
                    : a.type === 'success'
                    ? 'text-[#4ADE80]'
                    : 'text-[#C9A86A]'
                }`}
              >
                {a.title}
              </span>
              <span className="text-[10px] text-white/40">{a.time}</span>
            </div>
            <p className="text-white/70 text-[11px] leading-relaxed">{a.desc}</p>
          </div>
        ))}
      </div>

      <div className="p-4 bg-[#161616] border-t border-white/10 flex justify-between items-center text-[10px] font-code-sm text-white/40">
        <span>All daemons operational</span>
        <button
          onClick={onClose}
          className="px-3.5 py-1.5 bg-white/10 text-white rounded-full hover:bg-white/20 cursor-pointer transition-colors"
        >
          Dismiss All
        </button>
      </div>
    </div>
  );
};
