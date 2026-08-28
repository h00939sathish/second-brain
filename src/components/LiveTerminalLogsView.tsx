import React, { useState, useEffect, useRef } from 'react';
import { LogEntry } from '../types';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface LiveTerminalLogsViewProps {
  logs: LogEntry[];
  onAddLog: (log: LogEntry) => void;
  onClearLogs: () => void;
}

export const LiveTerminalLogsView: React.FC<LiveTerminalLogsViewProps> = ({
  logs,
  onAddLog,
  onClearLogs,
}) => {
  useTrackComponentRender('LiveTerminalLogsView');
  const [autoScroll, setAutoScroll] = useState(true);
  const [filterLevel, setFilterLevel] = useState<string>('ALL');
  const [filterStream, setFilterStream] = useState<string>('ALL');
  const [commandInput, setCommandInput] = useState('');
  const [expandedJson, setExpandedJson] = useState<Record<string, boolean>>({ 'log-5': true });
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) {
      terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const filteredLogs = logs.filter((log) => {
    const matchesLevel = filterLevel === 'ALL' || log.level === filterLevel;
    const matchesStream =
      filterStream === 'ALL' ||
      (filterStream === 'Codex' && log.tag.includes('Codex')) ||
      (filterStream === 'Claude' && log.tag.includes('Claude')) ||
      (filterStream === 'Sys' && (log.tag.includes('Sys') || log.tag.includes('Kernel')));
    return matchesLevel && matchesStream;
  });

  const handleCommandSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cmd = commandInput.trim();
    if (!cmd) return;

    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(
      now.getMinutes()
    ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}.${String(
      now.getMilliseconds()
    ).padStart(3, '0')}`;

    // Append user command
    onAddLog({
      id: `cmd-${Date.now()}`,
      timestamp: timeStr,
      level: 'SYS',
      tag: '[CLI]',
      sourceColor: '#22d3ee',
      message: `$ ${cmd}`,
    });

    // Execute built-in command responses
    const lower = cmd.toLowerCase();
    if (lower === 'help') {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'INFO',
        tag: '[SYS]',
        sourceColor: '#d0bcff',
        message: 'Available commands: help, status, daemons, ping, sync, vault, clear, top, whoami',
      });
    } else if (lower === 'clear') {
      onClearLogs();
    } else if (lower === 'status') {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'OK',
        tag: '[Sys-Mon]',
        sourceColor: '#10b981',
        message: 'MISSION_CONTROL Core: 100% HEALTHY. 4 daemons active, 0 fatal crashes.',
      });
    } else if (lower === 'daemons') {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'INFO',
        tag: '[Sys-Mon]',
        sourceColor: '#22d3ee',
        message: 'Active Daemons: [Codex-Alpha PID: 4492 (850ms)], [Claude-Sync PID: 1104 (210ms)], [Opencode PID: 2049 (Idle)]',
      });
    } else if (lower === 'ping') {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'OK',
        tag: '[Net]',
        sourceColor: '#4cd7f6',
        message: 'PONG 127.0.0.1 (0.24ms) | US-EAST Gateway (14ms)',
      });
    } else if (lower === 'vault') {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'OK',
        tag: '[Vault]',
        sourceColor: '#10b981',
        message: 'Vault status: 2066/2200B secure tokens mapped, AES-256-GCM armed.',
      });
    } else if (lower === 'whoami') {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'INFO',
        tag: '[Auth]',
        sourceColor: '#ffb690',
        message: 'Operator UID: op-0x8f9a2b (Admin / Titan Clearance)',
      });
    } else {
      onAddLog({
        id: `resp-${Date.now()}`,
        timestamp: timeStr,
        level: 'WARN',
        tag: '[CLI]',
        sourceColor: '#ffb4ab',
        message: `Command not recognized: '${cmd}'. Type 'help' for command list.`,
      });
    }

    setCommandInput('');
  };

  const handleExport = () => {
    const text = logs
      .map(
        (l) =>
          `[${l.timestamp}] [${l.level}] ${l.tag} ${l.message} ${
            l.jsonPayload ? JSON.stringify(l.jsonPayload) : ''
          }`
      )
      .join('\n');
    navigator.clipboard.writeText(text);
    alert('Log history copied to clipboard!');
  };

  const toggleJson = (id: string) => {
    setExpandedJson((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="space-y-4 pb-12">
      {/* Top Status Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 bg-[#111111] border border-white/10 rounded-3xl">
        <div className="flex items-center gap-2 font-code-sm text-xs text-[#C9A86A]">
          <span className="material-symbols-outlined text-[16px]">folder_open</span>
          <span className="text-white font-medium">/var/log/mission_control/live.log</span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Level Filter */}
          <div className="flex items-center gap-1 bg-[#161616] border border-white/10 p-1 rounded-full font-code-sm text-[10px]">
            {(['ALL', 'INFO', 'OK', 'WARN', 'ERR', 'SYS'] as const).map((lvl) => (
              <button
                key={lvl}
                onClick={() => setFilterLevel(lvl)}
                className={`px-3 py-1 rounded-full transition-all cursor-pointer ${
                  filterLevel === lvl
                    ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                    : 'text-white/40 hover:text-white hover:bg-white/5'
                }`}
              >
                {lvl}
              </button>
            ))}
          </div>

          {/* Auto scroll toggle */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`px-3.5 py-1.5 rounded-full font-code-sm text-xs flex items-center gap-1.5 border transition-colors cursor-pointer ${
              autoScroll
                ? 'bg-white/10 text-white border-white/20 font-medium shadow-sm'
                : 'bg-[#161616] text-white/40 border-white/10'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {autoScroll ? 'check_circle' : 'radio_button_unchecked'}
            </span>
            Auto-Scroll
          </button>

          {/* Export Log */}
          <button
            onClick={handleExport}
            className="px-3.5 py-1.5 bg-[#161616] hover:bg-white/10 text-white/70 hover:text-white border border-white/10 rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[14px]">content_copy</span>
            Export
          </button>

          {/* Clear Log */}
          <button
            onClick={onClearLogs}
            className="px-3.5 py-1.5 bg-[#161616] hover:bg-[#E5A93C]/20 text-[#E5A93C] border border-white/10 rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[14px]">delete</span>
            Clear
          </button>
        </div>
      </div>

      {/* Main Terminal Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Left Streams Sidebar */}
        <div className="space-y-3">
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-4">
            <div className="flex items-center justify-between pb-2 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium">
                Active Streams
              </span>
              <span className="font-code-sm text-[10px] text-[#4ADE80]">3 Connected</span>
            </div>

            <div className="space-y-2">
              <button
                onClick={() => setFilterStream(filterStream === 'Codex' ? 'ALL' : 'Codex')}
                className={`w-full p-2.5 rounded-xl flex items-center justify-between text-left font-code-sm text-xs transition-all cursor-pointer ${
                  filterStream === 'Codex'
                    ? 'bg-[#C9A86A]/15 border border-[#C9A86A]/40 text-white'
                    : 'bg-[#161616] border border-white/5 hover:border-white/20 text-white/70'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#C9A86A] animate-pulse shadow-[0_0_6px_#C9A86A]"></span>
                  <span className="text-white font-medium">Codex-Alpha</span>
                </div>
                <span className="text-[10px] text-white/40">PID 4492</span>
              </button>

              <button
                onClick={() => setFilterStream(filterStream === 'Claude' ? 'ALL' : 'Claude')}
                className={`w-full p-2.5 rounded-xl flex items-center justify-between text-left font-code-sm text-xs transition-all cursor-pointer ${
                  filterStream === 'Claude'
                    ? 'bg-white/15 border border-white/40 text-white'
                    : 'bg-[#161616] border border-white/5 hover:border-white/20 text-white/70'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-white animate-pulse shadow-[0_0_6px_white]"></span>
                  <span className="text-white font-medium">Claude-Sync</span>
                </div>
                <span className="text-[10px] text-white/40">PID 1104</span>
              </button>

              <button
                onClick={() => setFilterStream(filterStream === 'Sys' ? 'ALL' : 'Sys')}
                className={`w-full p-2.5 rounded-xl flex items-center justify-between text-left font-code-sm text-xs transition-all cursor-pointer ${
                  filterStream === 'Sys'
                    ? 'bg-white/10 border border-white/30 text-white'
                    : 'bg-[#161616] border border-white/5 hover:border-white/20 text-white/70'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-white/60 animate-pulse"></span>
                  <span className="text-white font-medium">Sys-Monitor</span>
                </div>
                <span className="text-[10px] text-white/40">PID 001</span>
              </button>
            </div>
          </div>

          {/* System Load Box */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-4">
            <div className="text-[10px] text-white/40 uppercase tracking-[0.2em] mb-3">
              Daemon Load
            </div>
            <div className="space-y-3 font-code-sm text-xs">
              <div>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-white/60">CPU Cluster</span>
                  <span className="text-[#C9A86A] font-semibold">42%</span>
                </div>
                <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden">
                  <div className="bg-[#C9A86A] h-full rounded-full" style={{ width: '42%' }}></div>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-white/60">VRAM Buffer</span>
                  <span className="text-white font-semibold">64%</span>
                </div>
                <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden">
                  <div className="bg-white h-full rounded-full" style={{ width: '64%' }}></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Terminal Console (Spans 3 col on lg) */}
        <div className="lg:col-span-3 bg-[#090909] border border-white/10 rounded-3xl flex flex-col h-[520px] overflow-hidden crt-overlay">
          {/* Terminal Console Header */}
          <div className="px-5 py-3 bg-[#111111] border-b border-white/10 flex items-center justify-between relative z-10">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-white/20"></span>
              <span className="w-2.5 h-2.5 rounded-full bg-white/30"></span>
              <span className="w-2.5 h-2.5 rounded-full bg-[#C9A86A]/80"></span>
              <span className="font-code-sm text-xs text-white/40 ml-2">tty1 • root@control: /opt/daemons</span>
            </div>
            <span className="font-code-sm text-[10px] text-[#C9A86A] animate-pulse tracking-wider">STREAM ACTIVE</span>
          </div>

          {/* Logs Output Area */}
          <div className="flex-1 p-5 overflow-y-auto font-code-sm text-xs space-y-2.5 relative z-10 select-text">
            {filteredLogs.map((log) => {
              const levelColor =
                log.level === 'ERR'
                  ? 'text-[#E5A93C] bg-[#E5A93C]/10 border-[#E5A93C]/30'
                  : log.level === 'WARN'
                  ? 'text-[#E5A93C] bg-[#E5A93C]/10 border-[#E5A93C]/30'
                  : log.level === 'OK'
                  ? 'text-[#4ADE80] bg-[#4ADE80]/10 border-[#4ADE80]/30'
                  : log.level === 'SYS'
                  ? 'text-white/80 bg-white/5 border-white/20'
                  : 'text-[#C9A86A] bg-[#C9A86A]/10 border-[#C9A86A]/30';

              return (
                <div key={log.id} className="leading-relaxed hover:bg-white/[0.03] px-2 py-1 rounded-lg">
                  <span className="text-white/30 mr-2">[{log.timestamp}]</span>
                  <span className={`px-2 py-0.5 text-[9px] border rounded-full font-semibold mr-2 ${levelColor}`}>
                    {log.level}
                  </span>
                  <span className="font-medium mr-2" style={{ color: log.sourceColor }}>
                    {log.tag}
                  </span>
                  <span className="text-white/80">{log.message}</span>

                  {log.errorCode && (
                    <span className="ml-2 font-semibold text-[#E5A93C] bg-[#E5A93C]/20 px-2 py-0.5 rounded-full border border-[#E5A93C]/40">
                      {log.errorCode}
                    </span>
                  )}

                  {/* JSON Payload preview if present */}
                  {log.jsonPayload && (
                    <div className="mt-2 ml-4 p-3 bg-[#111111] border border-white/10 rounded-xl text-[11px]">
                      <button
                        onClick={() => toggleJson(log.id)}
                        className="text-[#C9A86A] hover:underline flex items-center gap-1 font-medium mb-1.5 cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-[14px]">
                          {expandedJson[log.id] ? 'expand_more' : 'chevron_right'}
                        </span>
                        {expandedJson[log.id] ? 'Hide Payload' : 'Inspect JSON Payload'}
                      </button>

                      {expandedJson[log.id] && (
                        <pre className="text-white/70 bg-[#050505] p-3 rounded-lg border border-white/5 overflow-x-auto text-[10px]">
                          {JSON.stringify(log.jsonPayload, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            <div ref={terminalEndRef} />
          </div>

          {/* Interactive Terminal Input Form */}
          <form
            onSubmit={handleCommandSubmit}
            className="p-3 bg-[#111111] border-t border-white/10 flex items-center gap-3 relative z-10"
          >
            <span className="font-code-sm text-xs text-[#C9A86A] font-semibold">root@control:~#</span>
            <input
              type="text"
              value={commandInput}
              onChange={(e) => setCommandInput(e.target.value)}
              placeholder="Type command (e.g. help, status, daemons, ping, sync)..."
              className="flex-1 bg-transparent border-none text-white font-code-sm text-xs focus:outline-none placeholder:text-white/30"
            />
            <button
              type="submit"
              className="px-4 py-1.5 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs transition-all shadow-[0_0_10px_rgba(201,168,106,0.2)] cursor-pointer"
            >
              EXEC
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
