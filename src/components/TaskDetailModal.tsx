import React from 'react';
import { KanbanTask } from '../types';

interface TaskDetailModalProps {
  task: KanbanTask | null;
  isOpen: boolean;
  onClose: () => void;
  onSave?: (task: KanbanTask) => void;
}

export const TaskDetailModal: React.FC<TaskDetailModalProps> = ({
  task,
  isOpen,
  onClose,
}) => {
  if (!isOpen || !task) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs">
      <div className="w-full max-w-lg bg-[#111111] border border-white/10 rounded-3xl shadow-2xl p-6 relative">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <span className="font-code-sm text-xs text-[#C9A86A] font-semibold">{task.id}</span>
            <span
              className="px-2.5 py-0.5 rounded-full font-code-sm text-[9px] font-semibold uppercase tracking-wider"
              style={{
                backgroundColor: `${task.assignee.color}20`,
                color: task.assignee.color,
                border: `1px solid ${task.assignee.color}50`,
              }}
            >
              {task.status}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white p-1 rounded-full cursor-pointer transition-colors"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        <div className="space-y-4 font-code-sm text-xs">
          <div>
            <label className="text-white/40 text-[9px] uppercase tracking-wider">Task Directive</label>
            <h3 className="text-sm font-light text-white mt-0.5">{task.title}</h3>
          </div>

          {task.description && (
            <div>
              <label className="text-white/40 text-[9px] uppercase tracking-wider">Execution Plan</label>
              <p className="text-white/70 text-xs bg-[#161616] p-4 rounded-2xl border border-white/5 mt-1 leading-relaxed">
                {task.description}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 p-4 bg-[#161616] border border-white/5 rounded-2xl">
            <div>
              <span className="text-white/40 text-[9px] uppercase tracking-wider block">Assigned Daemon</span>
              <div className="flex items-center gap-2 mt-1">
                <span
                  className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold text-black"
                  style={{ backgroundColor: task.assignee.color }}
                >
                  {task.assignee.code}
                </span>
                <span className="text-white font-medium">{task.assignee.name}</span>
              </div>
            </div>

            <div>
              <span className="text-white/40 text-[9px] uppercase tracking-wider block">Token Cost</span>
              <span className="text-white font-medium mt-1 block">
                ${task.tokenCost?.toFixed(3) || '0.000'}
              </span>
            </div>

            {task.uptime && (
              <div>
                <span className="text-white/40 text-[9px] uppercase tracking-wider block">Uptime</span>
                <span className="text-[#C9A86A] font-medium mt-1 block">{task.uptime}</span>
              </div>
            )}

            {task.specLink && (
              <div>
                <span className="text-white/40 text-[9px] uppercase tracking-wider block">Linked Spec</span>
                <span className="text-[#C9A86A] font-medium mt-1 block">{task.specLink}</span>
              </div>
            )}
          </div>

          {task.warningMessage && (
            <div className="p-3.5 bg-[#E5A93C]/10 border border-[#E5A93C]/30 rounded-2xl text-[#E5A93C] flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px]">warning</span>
              <span>{task.warningMessage}</span>
            </div>
          )}

          <div className="flex justify-end pt-4 border-t border-white/10">
            <button
              onClick={onClose}
              className="px-5 py-2 rounded-full bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold shadow-[0_0_10px_rgba(201,168,106,0.25)] cursor-pointer transition-all"
            >
              Close Inspector
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
