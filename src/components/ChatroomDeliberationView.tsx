import React, { useState, useEffect, useCallback } from 'react';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';
import { KanbanTask, SquadData, DeliberationRoomData, DeliberationMessage } from '../types';

interface ChatroomDeliberationViewProps {
  workspace: string;
  workspaces: string[];
  tasks: KanbanTask[];
}

interface NoteItem {
  id: string;
  source: string;
  agent: string;
  color: string;
  topic: string;
  text: string;
  workspace: string;
  project: string;
  created: string;
  timestamp: string;
}

const AGENTS = [
  { id: 'agy', name: 'Antigravity (AGY)', color: '#C9A86A' },
  { id: 'claude', name: 'Claude', color: '#A78BFA' },
  { id: 'codex', name: 'Codex', color: '#34D399' },
  { id: 'opencode', name: 'OpenCode', color: '#38BDF8' },
  { id: 'operator', name: 'Operator (Human)', color: '#9CA3AF' },
];

const AGENT_COLORS: Record<string, string> = {
  agy: '#C9A86A',
  antigravity: '#C9A86A',
  claude: '#A78BFA',
  codex: '#34D399',
  opencode: '#38BDF8',
  operator: '#9CA3AF',
  'control-plane': '#F472B6',
};

const COMMON_TOPICS = ['all', 'general', 'architecture', 'handoffs', 'blockers', 'squad-sync', 'reviews'];

export const ChatroomDeliberationView: React.FC<ChatroomDeliberationViewProps> = ({
  workspace,
  workspaces,
  tasks,
}) => {
  useTrackComponentRender('ChatroomDeliberationView');

  // Active sub-tab
  const [activeTab, setActiveTab] = useState<'chat' | 'deliberation' | 'squad'>('chat');

  // Squad State
  const [squad, setSquad] = useState<SquadData | null>(null);
  const [squadLoading, setSquadLoading] = useState(false);
  const [roleUpdateMsg, setRoleUpdateMsg] = useState<string | null>(null);

  // Chatroom / Notes State
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [selectedTopic, setSelectedTopic] = useState('all');
  const [noteAuthor, setNoteAuthor] = useState('agy');
  const [customTopic, setCustomTopic] = useState('');
  const [noteText, setNoteText] = useState('');
  const [isPostingNote, setIsPostingNote] = useState(false);

  // Deliberation Room State
  const [selectedTaskId, setSelectedTaskId] = useState<string>(tasks[0]?.id || '');
  const [roomData, setRoomData] = useState<DeliberationRoomData | null>(null);
  const [roomLoading, setRoomLoading] = useState(false);
  const [roomError, setRoomError] = useState<string | null>(null);
  const [adjudicateResult, setAdjudicateResult] = useState<any>(null);

  // Deliberation Post Form State
  const [delibMsgType, setDelibMsgType] = useState('QUESTION');
  const [delibSeverity, setDelibMsgSeverity] = useState('medium');
  const [delibSender, setDelibSender] = useState('agy');
  const [delibBody, setDelibBody] = useState('');
  const [delibRef, setDelibRef] = useState('');
  const [isPostingDelib, setIsPostingDelib] = useState(false);

  // Fetch Squad Data
  const fetchSquad = useCallback(async () => {
    try {
      setSquadLoading(true);
      const scope = workspace ? `?workspace=${encodeURIComponent(workspace)}` : '';
      const res = await fetch(`/api/squad${scope}`);
      if (res.ok) {
        const data = await res.json();
        setSquad(data);
      }
    } catch {
      // ignore network errors
    } finally {
      setSquadLoading(false);
    }
  }, [workspace]);

  // Fetch Notes / Chatroom
  const fetchNotes = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (workspace) params.set('workspace', workspace);
      else params.set('all', '1');
      if (selectedTopic !== 'all') params.set('topic', selectedTopic);
      params.set('limit', '80');

      const res = await fetch(`/api/notes?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setNotes(data);
        }
      }
    } catch {
      // ignore
    }
  }, [workspace, selectedTopic]);

  // Fetch Deliberation Room
  const fetchRoom = useCallback(async (taskId: string) => {
    if (!taskId) return;
    try {
      setRoomLoading(true);
      setRoomError(null);
      const scope = workspace ? `&workspace=${encodeURIComponent(workspace)}` : '';
      const res = await fetch(`/api/deliberation?task=${encodeURIComponent(taskId)}${scope}`);
      if (res.ok) {
        const data = await res.json();
        setRoomData(data);
      } else {
        setRoomData(null);
        if (res.status === 404) {
          setRoomError('No Deliberation Room has been opened for this task yet.');
        } else {
          const err = await res.json().catch(() => ({}));
          setRoomError(err.error || 'Failed to load deliberation room.');
        }
      }
    } catch {
      setRoomError('Network error loading deliberation room.');
    } finally {
      setRoomLoading(false);
    }
  }, [workspace]);

  // Polling loop
  useEffect(() => {
    fetchSquad();
    fetchNotes();
    if (selectedTaskId) {
      fetchRoom(selectedTaskId);
    }
    const interval = setInterval(() => {
      fetchSquad();
      fetchNotes();
      if (selectedTaskId) {
        fetchRoom(selectedTaskId);
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [fetchSquad, fetchNotes, fetchRoom, selectedTaskId]);

  // Handle reassigning squad role
  const handleAssignRole = async (role: string, agent: string) => {
    try {
      const res = await fetch('/api/squad/role', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, agent, workspace }),
      });
      if (res.ok) {
        setRoleUpdateMsg(`Assigned role "${role}" to ${agent}`);
        fetchSquad();
        setTimeout(() => setRoleUpdateMsg(null), 3000);
      }
    } catch {
      // ignore
    }
  };

  // Handle posting a chat note
  const handlePostNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    try {
      setIsPostingNote(true);
      const effectiveTopic = customTopic.trim() || (selectedTopic === 'all' ? 'general' : selectedTopic);
      const res = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: noteText.trim(),
          agent: noteAuthor,
          topic: effectiveTopic,
          workspace,
        }),
      });
      if (res.ok) {
        setNoteText('');
        setCustomTopic('');
        fetchNotes();
      }
    } catch {
      // ignore
    } finally {
      setIsPostingNote(false);
    }
  };

  // Handle opening deliberation room
  const handleOpenRoom = async () => {
    if (!selectedTaskId) return;
    try {
      setRoomLoading(true);
      const res = await fetch('/api/deliberation/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: selectedTaskId,
          workspace,
          risk: 'normal',
          mode: 'normal',
        }),
      });
      if (res.ok) {
        fetchRoom(selectedTaskId);
      } else {
        const err = await res.json().catch(() => ({}));
        setRoomError(err.error || 'Failed to open deliberation room.');
      }
    } catch {
      setRoomError('Network error opening deliberation room.');
    } finally {
      setRoomLoading(false);
    }
  };

  // Handle posting message/objection to deliberation
  const handlePostDelibMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!delibBody.trim() || !selectedTaskId) return;
    try {
      setIsPostingDelib(true);
      const res = await fetch('/api/deliberation/post', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: selectedTaskId,
          sender: delibSender,
          type: delibMsgType,
          severity: delibSeverity,
          body: delibBody.trim(),
          references: delibRef.trim() ? [delibRef.trim()] : [],
          workspace,
        }),
      });
      if (res.ok) {
        setDelibBody('');
        setDelibRef('');
        fetchRoom(selectedTaskId);
      }
    } catch {
      // ignore
    } finally {
      setIsPostingDelib(false);
    }
  };

  // Handle Adjudication
  const handleAdjudicate = async (force: boolean = false) => {
    if (!selectedTaskId) return;
    try {
      setAdjudicateResult(null);
      const res = await fetch('/api/deliberation/adjudicate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: selectedTaskId,
          workspace,
          actor: 'control-plane',
          force,
        }),
      });
      const data = await res.json();
      setAdjudicateResult(data);
      fetchRoom(selectedTaskId);
    } catch (err: any) {
      setAdjudicateResult({ ok: false, reason: err.message || 'Adjudication request failed' });
    }
  };

  const getAgentColor = (name: string) => {
    const key = (name || '').toLowerCase();
    for (const [k, v] of Object.entries(AGENT_COLORS)) {
      if (key.includes(k)) return v;
    }
    return '#9CA3AF';
  };

  return (
    <div className="space-y-6 pb-16">
      {/* Top Header / Mode Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 bg-[#111111] border border-white/10 rounded-3xl">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-[#C9A86A]/10 border border-[#C9A86A]/30 flex items-center justify-center text-[#C9A86A]">
            <span className="material-symbols-outlined text-[22px]">forum</span>
          </div>
          <div>
            <h2 className="text-base font-semibold text-white tracking-wide flex items-center gap-2">
              Multi-Agent Squad & Deliberation Control
              <span className="px-2 py-0.5 text-[9px] uppercase tracking-widest font-code-sm rounded-full bg-[#C9A86A]/15 text-[#C9A86A] border border-[#C9A86A]/30">
                RigSpec Pods
              </span>
            </h2>
            <p className="text-xs text-white/50 font-code-sm mt-0.5">
              Declarative squads, topic chatrooms, and INV-008 deliberation gates
            </p>
          </div>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center bg-[#161616] p-1 rounded-2xl border border-white/10">
          <button
            onClick={() => setActiveTab('chat')}
            className={`px-4 py-2 rounded-xl text-xs uppercase tracking-wider font-semibold transition-all cursor-pointer flex items-center gap-2 ${
              activeTab === 'chat'
                ? 'bg-white/10 text-white shadow-sm border border-white/15'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">chat</span>
            Topic Chatroom
          </button>
          <button
            onClick={() => setActiveTab('deliberation')}
            className={`px-4 py-2 rounded-xl text-xs uppercase tracking-wider font-semibold transition-all cursor-pointer flex items-center gap-2 ${
              activeTab === 'deliberation'
                ? 'bg-[#C9A86A]/20 text-[#C9A86A] shadow-sm border border-[#C9A86A]/30'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">gavel</span>
            Deliberation Room
          </button>
          <button
            onClick={() => setActiveTab('squad')}
            className={`px-4 py-2 rounded-xl text-xs uppercase tracking-wider font-semibold transition-all cursor-pointer flex items-center gap-2 ${
              activeTab === 'squad'
                ? 'bg-white/10 text-white shadow-sm border border-white/15'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">group</span>
            Squad Loadout
          </button>
        </div>
      </div>

      {roleUpdateMsg && (
        <div className="p-3 bg-[#4ADE80]/10 border border-[#4ADE80]/30 rounded-2xl text-xs font-code-sm text-[#4ADE80] flex items-center gap-2 animate-fade-in">
          <span className="material-symbols-outlined text-[16px]">check_circle</span>
          <span>{roleUpdateMsg}</span>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 1: TOPIC CHATROOM & CONTEXT FEED                                      */}
      {/* ========================================================================= */}
      {activeTab === 'chat' && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Left: Topic Selector & Info */}
          <div className="lg:col-span-1 space-y-4">
            <div className="p-4 bg-[#111111] border border-white/10 rounded-3xl space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase tracking-widest text-white/50 font-code-sm">
                  Active Channels
                </span>
                <span className="text-[10px] text-[#C9A86A] font-code-sm">
                  {notes.length} notes
                </span>
              </div>

              <div className="space-y-1">
                {COMMON_TOPICS.map((topic) => {
                  const isSelected = selectedTopic === topic;
                  return (
                    <button
                      key={topic}
                      onClick={() => setSelectedTopic(topic)}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-code-sm transition-all text-left cursor-pointer ${
                        isSelected
                          ? 'bg-[#C9A86A]/20 text-[#C9A86A] border border-[#C9A86A]/30 font-semibold'
                          : 'text-white/60 hover:text-white hover:bg-white/5 border border-transparent'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-white/40">#</span>
                        <span>{topic}</span>
                      </div>
                      {isSelected && (
                        <span className="w-1.5 h-1.5 rounded-full bg-[#C9A86A] animate-pulse"></span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Squad Snapshot Card */}
            {squad && (
              <div className="p-4 bg-[#111111] border border-white/10 rounded-3xl space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] uppercase tracking-widest text-white/50 font-code-sm">
                    Pod Loadout
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/10 text-white/70 font-code-sm">
                    {squad.name}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs font-code-sm">
                  {Object.entries(squad.roles).map(([role, agent]) => (
                    <div key={role} className="p-2 bg-[#161616] rounded-xl border border-white/5">
                      <div className="text-[10px] uppercase text-white/40">{role}</div>
                      <div className="font-semibold text-white truncate" style={{ color: getAgentColor(agent) }}>
                        @{agent}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right: Feed + Composer */}
          <div className="lg:col-span-3 space-y-4">
            {/* Note Composer */}
            <form onSubmit={handlePostNote} className="p-4 bg-[#111111] border border-white/10 rounded-3xl space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-white/40 font-code-sm">Posting as:</span>
                  <select
                    value={noteAuthor}
                    onChange={(e) => setNoteAuthor(e.target.value)}
                    className="bg-[#181818] border border-white/15 text-white text-xs font-code-sm rounded-xl px-2.5 py-1 focus:outline-none focus:border-[#C9A86A]"
                  >
                    {AGENTS.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs text-white/40 font-code-sm">Channel:</span>
                  <input
                    type="text"
                    placeholder={`#${selectedTopic === 'all' ? 'general' : selectedTopic}`}
                    value={customTopic}
                    onChange={(e) => setCustomTopic(e.target.value)}
                    className="bg-[#181818] border border-white/15 text-white text-xs font-code-sm rounded-xl px-2.5 py-1 w-36 focus:outline-none focus:border-[#C9A86A]"
                  />
                </div>
              </div>

              <textarea
                rows={2}
                placeholder="Broadcast a note, status update, architectural decision, or handoff insight to the squad..."
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-xs text-white placeholder-white/30 focus:outline-none focus:border-[#C9A86A] resize-none font-code-sm"
              />

              <div className="flex items-center justify-between pt-1">
                <span className="text-[10px] text-white/30 font-code-sm">
                  Indexed via SQLite FTS5 WAL • Subscribed agents notified via event bus
                </span>
                <button
                  type="submit"
                  disabled={isPostingNote || !noteText.trim()}
                  className="px-5 py-2 bg-[#C9A86A] hover:bg-[#dfc188] disabled:opacity-40 text-black font-semibold rounded-full text-xs font-code-sm uppercase tracking-wider flex items-center gap-2 transition-all cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">send</span>
                  {isPostingNote ? 'Broadcasting...' : 'Broadcast'}
                </button>
              </div>
            </form>

            {/* Notes List */}
            <div className="space-y-3">
              {notes.length === 0 ? (
                <div className="p-8 text-center bg-[#111111] border border-white/10 rounded-3xl text-white/40 font-code-sm text-xs">
                  No notes found in channel #{selectedTopic}. Broadcast the first message above!
                </div>
              ) : (
                notes.map((note) => {
                  const color = getAgentColor(note.agent || note.source);
                  return (
                    <div
                      key={note.id}
                      className="p-4 bg-[#111111] border border-white/10 rounded-2xl space-y-2 hover:border-white/20 transition-all"
                    >
                      <div className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-black"
                            style={{ backgroundColor: color }}
                          >
                            {(note.agent || note.source || 'A').slice(0, 2).toUpperCase()}
                          </div>
                          <span className="font-semibold text-white tracking-wide" style={{ color }}>
                            @{note.agent || note.source}
                          </span>
                          {note.topic && (
                            <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/60 font-code-sm text-[10px]">
                              #{note.topic}
                            </span>
                          )}
                        </div>
                        <span className="text-white/40 text-[10px] font-code-sm">
                          {note.timestamp || note.created}
                        </span>
                      </div>

                      <div className="text-xs text-white/80 font-code-sm leading-relaxed whitespace-pre-wrap pl-8">
                        {note.text}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: DELIBERATION ROOM (INV-008)                                        */}
      {/* ========================================================================= */}
      {activeTab === 'deliberation' && (
        <div className="space-y-6">
          {/* Task Picker & Room State Header */}
          <div className="p-5 bg-[#111111] border border-white/10 rounded-3xl space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="text-xs uppercase tracking-widest text-white/50 font-code-sm">
                  Target Task:
                </span>
                <select
                  value={selectedTaskId}
                  onChange={(e) => setSelectedTaskId(e.target.value)}
                  className="bg-[#181818] border border-white/20 text-white font-code-sm text-xs rounded-xl px-3 py-1.5 focus:outline-none focus:border-[#C9A86A]"
                >
                  {tasks.map((t) => (
                    <option key={t.id} value={t.id}>
                      [{t.status.toUpperCase()}] {t.title} ({t.id})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center gap-2">
                {roomData ? (
                  <>
                    <span
                      className={`px-3 py-1 rounded-full font-code-sm text-xs font-semibold border ${
                        roomData.context.status === 'AUTHORIZED'
                          ? 'bg-[#4ADE80]/15 text-[#4ADE80] border-[#4ADE80]/30'
                          : roomData.context.status === 'BLOCKED'
                          ? 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30'
                          : 'bg-[#C9A86A]/15 text-[#C9A86A] border-[#C9A86A]/30'
                      }`}
                    >
                      GATE: {roomData.context.status}
                    </span>
                    <button
                      onClick={() => handleAdjudicate(false)}
                      className="px-4 py-1.5 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all shadow-[0_0_10px_rgba(201,168,106,0.25)] cursor-pointer"
                    >
                      <span className="material-symbols-outlined text-[16px]">balance</span>
                      Adjudicate Gate
                    </button>
                  </>
                ) : (
                  <button
                    onClick={handleOpenRoom}
                    disabled={roomLoading}
                    className="px-4 py-1.5 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full font-code-sm text-xs flex items-center gap-1.5 transition-all cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[16px]">meeting_room</span>
                    Open Deliberation Room
                  </button>
                )}
              </div>
            </div>

            {/* Adjudication Feedback Banner */}
            {adjudicateResult && (
              <div
                className={`p-4 rounded-2xl border text-xs font-code-sm space-y-1.5 animate-fade-in ${
                  adjudicateResult.ok
                    ? 'bg-[#4ADE80]/10 border-[#4ADE80]/30 text-[#4ADE80]'
                    : 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#EF4444]'
                }`}
              >
                <div className="font-semibold flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">
                    {adjudicateResult.ok ? 'verified' : 'block'}
                  </span>
                  <span>
                    {adjudicateResult.ok
                      ? `Gate cleared! Decision ID: ${adjudicateResult.decision_id}`
                      : `Adjudication Refused: ${adjudicateResult.reason}`}
                  </span>
                </div>
                {adjudicateResult.unresolved_objections && (
                  <div className="pl-6 text-white/70 space-y-1">
                    <div>Blocking objections that must be addressed:</div>
                    <ul className="list-disc list-inside">
                      {adjudicateResult.unresolved_objections.map((o: any) => (
                        <li key={o.message_id}>
                          <span className="text-[#EF4444] font-semibold">{o.message_id}</span> ({o.sender}): {o.body}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {roomError && !roomData && (
              <div className="p-4 bg-white/5 border border-white/10 rounded-2xl text-xs text-white/60 font-code-sm flex items-center justify-between">
                <span>{roomError}</span>
                <button
                  onClick={handleOpenRoom}
                  className="px-3 py-1 bg-white/10 hover:bg-white/20 rounded-xl text-white font-semibold cursor-pointer"
                >
                  Initialize Room
                </button>
              </div>
            )}
          </div>

          {/* Deliberation Details Grid */}
          {roomData && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Column: Context, Quorum, & Proposals */}
              <div className="space-y-4">
                {/* Governance Metadata */}
                <div className="p-4 bg-[#111111] border border-white/10 rounded-3xl space-y-3 font-code-sm text-xs">
                  <div className="text-[11px] uppercase tracking-widest text-white/40">
                    Governance Status
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between py-1 border-b border-white/5">
                      <span className="text-white/50">Risk Tier:</span>
                      <span className="font-semibold text-white uppercase">{roomData.context.risk}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-white/5">
                      <span className="text-white/50">Deliberation Round:</span>
                      <span className="text-white font-semibold">
                        Round {roomData.context.current_round} of {roomData.context.max_rounds}
                      </span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-white/5">
                      <span className="text-white/50">Required Quorum:</span>
                      <span className="text-white font-semibold">
                        {roomData.context.required_acknowledgements} ack(s)
                      </span>
                    </div>
                  </div>

                  <div className="pt-2">
                    <div className="text-[10px] uppercase text-white/40 mb-2">Required Seats:</div>
                    <div className="flex flex-wrap gap-1.5">
                      {roomData.context.required_participants.map((seat) => {
                        const participated =
                          roomData.messages.some((m) => m.sender === seat) ||
                          roomData.proposals.some((p) => p.agent === seat);
                        return (
                          <span
                            key={seat}
                            className={`px-2 py-0.5 rounded-full text-[10px] flex items-center gap-1 border ${
                              participated
                                ? 'bg-[#4ADE80]/15 text-[#4ADE80] border-[#4ADE80]/30'
                                : 'bg-white/5 text-white/40 border-white/10'
                            }`}
                          >
                            <span className="material-symbols-outlined text-[12px]">
                              {participated ? 'check' : 'hourglass_empty'}
                            </span>
                            @{seat}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Technical Proposals */}
                <div className="p-4 bg-[#111111] border border-white/10 rounded-3xl space-y-3 font-code-sm text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] uppercase tracking-widest text-white/40">
                      Technical Proposals ({roomData.proposals.length})
                    </span>
                  </div>

                  {roomData.proposals.length === 0 ? (
                    <div className="text-white/40 py-2">
                      No proposals submitted yet. Agents must propose a plan before adjudication.
                    </div>
                  ) : (
                    roomData.proposals.map((prop) => (
                      <div key={prop.proposal_id} className="p-3 bg-[#161616] border border-white/5 rounded-2xl space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-semibold text-white" style={{ color: getAgentColor(prop.agent) }}>
                            @{prop.agent}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded-full text-[9px] font-semibold border ${
                              prop.status === 'ACCEPTED'
                                ? 'bg-[#4ADE80]/15 text-[#4ADE80] border-[#4ADE80]/30'
                                : prop.status === 'OBJECTED'
                                ? 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30'
                                : 'bg-[#C9A86A]/15 text-[#C9A86A] border-[#C9A86A]/30'
                            }`}
                          >
                            {prop.status}
                          </span>
                        </div>

                        {prop.plan && prop.plan.length > 0 && (
                          <div className="space-y-1 text-white/70">
                            <div className="text-[10px] text-white/40 uppercase">Plan:</div>
                            <ol className="list-decimal list-inside space-y-0.5 text-[11px]">
                              {prop.plan.map((step, idx) => (
                                <li key={idx}>{step}</li>
                              ))}
                            </ol>
                          </div>
                        )}

                        {prop.files_expected && prop.files_expected.length > 0 && (
                          <div className="text-[10px] text-white/50">
                            Files: {prop.files_expected.join(', ')}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Right Column (2 cols): Deliberation Log & Objection Form */}
              <div className="lg:col-span-2 space-y-4">
                {/* Form to raise objection or post message */}
                <form onSubmit={handlePostDelibMessage} className="p-4 bg-[#111111] border border-white/10 rounded-3xl space-y-3 font-code-sm text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="text-white/40">Sender:</span>
                      <select
                        value={delibSender}
                        onChange={(e) => setDelibSender(e.target.value)}
                        className="bg-[#181818] border border-white/15 text-white text-xs rounded-xl px-2.5 py-1 focus:outline-none focus:border-[#C9A86A]"
                      >
                        {AGENTS.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-white/40">Type:</span>
                      <select
                        value={delibMsgType}
                        onChange={(e) => setDelibMsgType(e.target.value)}
                        className="bg-[#181818] border border-white/15 text-white text-xs rounded-xl px-2.5 py-1 focus:outline-none focus:border-[#C9A86A]"
                      >
                        <option value="QUESTION">QUESTION</option>
                        <option value="PROPOSAL">PROPOSAL</option>
                        <option value="ANSWER">ANSWER</option>
                        <option value="OBJECTION">OBJECTION</option>
                        <option value="SUGGESTION">SUGGESTION</option>
                        <option value="EVIDENCE">EVIDENCE</option>
                        <option value="ACKNOWLEDGEMENT">ACKNOWLEDGEMENT</option>
                        <option value="DEPENDENCY">DEPENDENCY</option>
                        <option value="WARNING">WARNING</option>
                        <option value="HANDOFF">HANDOFF</option>
                      </select>
                    </div>

                    {delibMsgType === 'OBJECTION' && (
                      <div className="flex items-center gap-2">
                        <span className="text-white/40">Severity:</span>
                        <select
                          value={delibSeverity}
                          onChange={(e) => setDelibMsgSeverity(e.target.value)}
                          className="bg-[#181818] border border-[#EF4444]/40 text-[#EF4444] text-xs font-semibold rounded-xl px-2.5 py-1 focus:outline-none"
                        >
                          <option value="low">LOW</option>
                          <option value="medium">MEDIUM</option>
                          <option value="high">HIGH (Blocking)</option>
                          <option value="blocking">BLOCKING</option>
                        </select>
                      </div>
                    )}

                    <div className="flex items-center gap-2">
                      <span className="text-white/40">Ref:</span>
                      <input
                        type="text"
                        placeholder="msg_xxx or prop_xxx"
                        value={delibRef}
                        onChange={(e) => setDelibRef(e.target.value)}
                        className="bg-[#181818] border border-white/15 text-white text-xs rounded-xl px-2.5 py-1 w-32 focus:outline-none focus:border-[#C9A86A]"
                      />
                    </div>
                  </div>

                  <textarea
                    rows={2}
                    placeholder={
                      delibMsgType === 'OBJECTION'
                        ? 'State the technical risk, architectural conflict, or security objection...'
                        : 'Submit question, peer critique, or evidence...'
                    }
                    value={delibBody}
                    onChange={(e) => setDelibBody(e.target.value)}
                    className="w-full bg-[#161616] border border-white/10 rounded-2xl p-3 text-xs text-white placeholder-white/30 focus:outline-none focus:border-[#C9A86A] resize-none"
                  />

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isPostingDelib || !delibBody.trim()}
                      className={`px-5 py-2 font-semibold rounded-full text-xs uppercase tracking-wider flex items-center gap-2 transition-all cursor-pointer ${
                        delibMsgType === 'OBJECTION'
                          ? 'bg-[#EF4444] text-white hover:bg-[#dc2626]'
                          : 'bg-[#C9A86A] text-black hover:bg-[#dfc188]'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[16px]">
                        {delibMsgType === 'OBJECTION' ? 'warning' : 'send'}
                      </span>
                      {delibMsgType === 'OBJECTION' ? 'Raise Objection' : 'Record Message'}
                    </button>
                  </div>
                </form>

                {/* Deliberation Thread */}
                <div className="space-y-3">
                  <div className="text-xs uppercase tracking-widest text-white/40 font-code-sm px-1">
                    Deliberation Record ({roomData.messages.length} messages)
                  </div>

                  {roomData.messages.map((msg) => {
                    const isBlocking =
                      msg.type === 'OBJECTION' && (msg.severity === 'high' || msg.severity === 'blocking');
                    const color = getAgentColor(msg.sender);
                    return (
                      <div
                        key={msg.message_id}
                        className={`p-4 rounded-2xl border transition-all space-y-2 ${
                          isBlocking
                            ? 'bg-[#EF4444]/10 border-[#EF4444]/40 shadow-[0_0_12px_rgba(239,68,68,0.15)]'
                            : msg.type === 'OBJECTION'
                            ? 'bg-[#F59E0B]/10 border-[#F59E0B]/30'
                            : msg.type === 'ACKNOWLEDGEMENT'
                            ? 'bg-[#4ADE80]/10 border-[#4ADE80]/30'
                            : 'bg-[#111111] border-white/10'
                        }`}
                      >
                        <div className="flex items-center justify-between text-xs font-code-sm">
                          <div className="flex items-center gap-2.5">
                            <span className="font-semibold" style={{ color }}>
                              @{msg.sender}
                            </span>
                            <span
                              className={`px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider ${
                                isBlocking
                                  ? 'bg-[#EF4444] text-white'
                                  : msg.type === 'OBJECTION'
                                  ? 'bg-[#F59E0B] text-black'
                                  : msg.type === 'ACKNOWLEDGEMENT'
                                  ? 'bg-[#4ADE80] text-black'
                                  : 'bg-white/10 text-white/70'
                              }`}
                            >
                              {msg.type} {msg.severity ? `[${msg.severity.toUpperCase()}]` : ''}
                            </span>
                            <span className="text-white/30 text-[10px]">{msg.message_id}</span>
                          </div>
                          <span className="text-white/40 text-[10px]">{msg.timestamp}</span>
                        </div>

                        <div className="text-xs text-white/90 font-code-sm pl-2 leading-relaxed">
                          {msg.body}
                        </div>

                        {msg.references && msg.references.length > 0 && (
                          <div className="text-[10px] text-white/40 font-code-sm pl-2">
                            References: {msg.references.join(', ')}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: DECLARATIVE SQUAD LOADOUT                                         */}
      {/* ========================================================================= */}
      {activeTab === 'squad' && (
        <div className="space-y-6">
          <div className="p-6 bg-[#111111] border border-white/10 rounded-3xl space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-semibold text-white tracking-wide">
                  Declarative Squad Configuration (squad.yaml)
                </h3>
                <p className="text-xs text-white/50 font-code-sm mt-1">
                  RigSpec Pod roles mapped to kanban stage routing and gatekeepers
                </p>
              </div>

              <div className="flex items-center gap-2">
                <span className="px-3 py-1 rounded-full bg-white/10 text-white font-code-sm text-xs">
                  Workspace: {workspace || 'default'}
                </span>
                <span className="px-3 py-1 rounded-full bg-[#4ADE80]/15 text-[#4ADE80] border border-[#4ADE80]/30 font-code-sm text-xs font-semibold">
                  {squad?.configured ? 'DECLARED' : 'DEFAULT ROLES'}
                </span>
              </div>
            </div>

            {/* Squad Role Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                {
                  role: 'lead',
                  title: 'Squad Lead',
                  icon: 'stars',
                  stages: ['backlog', 'planning', 'coordinating'],
                  desc: 'Orchestrates architectural plans, goals, and initial specs.',
                },
                {
                  role: 'builder',
                  title: 'Core Builder',
                  icon: 'construction',
                  stages: ['running', 'ready'],
                  desc: 'Takes leases, writes code, and executes test suites.',
                },
                {
                  role: 'reviewer',
                  title: 'Code Reviewer',
                  icon: 'rate_review',
                  stages: ['review', 'blocked'],
                  desc: 'Audits diffs, checks invariants, and signs off code changes.',
                },
                {
                  role: 'qa',
                  title: 'QA / Verification',
                  icon: 'verified_user',
                  stages: ['done'],
                  desc: 'Verifies receipts, runs hostile probes, and hot-potato closes.',
                },
              ].map(({ role, title, icon, stages, desc }) => {
                const assignedAgent = squad?.roles?.[role] || 'unassigned';
                const color = getAgentColor(assignedAgent);
                const hasActiveSession = squad?.active_sessions?.[assignedAgent];

                return (
                  <div
                    key={role}
                    className="p-5 bg-[#161616] border border-white/10 rounded-2xl space-y-4 hover:border-white/20 transition-all flex flex-col justify-between"
                  >
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="w-8 h-8 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center text-[#C9A86A]">
                          <span className="material-symbols-outlined text-[18px]">{icon}</span>
                        </div>
                        <span className="text-[10px] uppercase tracking-widest text-white/40 font-code-sm">
                          {role}
                        </span>
                      </div>

                      <div>
                        <h4 className="font-semibold text-sm text-white">{title}</h4>
                        <p className="text-[11px] text-white/50 font-code-sm mt-1 leading-snug">
                          {desc}
                        </p>
                      </div>

                      {/* Stage routing badge */}
                      <div className="pt-1">
                        <div className="text-[9px] uppercase tracking-wider text-white/40 font-code-sm mb-1">
                          Routes stages:
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {stages.map((st) => (
                            <span
                              key={st}
                              className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/70 font-code-sm text-[9px] uppercase"
                            >
                              {st}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="pt-3 border-t border-white/10 space-y-2">
                      <div className="flex items-center justify-between text-xs font-code-sm">
                        <span className="text-white/40">Seat:</span>
                        <div className="flex items-center gap-1.5">
                          {hasActiveSession && (
                            <span className="w-1.5 h-1.5 rounded-full bg-[#4ADE80] shadow-[0_0_6px_#4ADE80] animate-pulse"></span>
                          )}
                          <span className="font-semibold" style={{ color }}>
                            @{assignedAgent}
                          </span>
                        </div>
                      </div>

                      <select
                        value={assignedAgent}
                        onChange={(e) => handleAssignRole(role, e.target.value)}
                        className="w-full bg-[#111111] border border-white/20 text-white font-code-sm text-xs rounded-xl px-2.5 py-1.5 focus:outline-none focus:border-[#C9A86A] cursor-pointer"
                      >
                        {AGENTS.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
