import React, { useState } from 'react';
import { TimeRange, InferenceRecord, ModelConsumptionPoint } from '../types';

interface TokenTelemetryViewProps {
  consumptionData: ModelConsumptionPoint[];
  inferences: InferenceRecord[];
  onSelectInference?: (item: InferenceRecord) => void;
}

export const TokenTelemetryView: React.FC<TokenTelemetryViewProps> = ({
  consumptionData,
  inferences,
  onSelectInference,
}) => {
  const [timeRange, setTimeRange] = useState<TimeRange>('24H');
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);
  const [tableSearch, setTableSearch] = useState('');

  // Calculate dynamic multiplier based on time range
  const rangeMultiplier = timeRange === '1H' ? 0.12 : timeRange === '24H' ? 1 : 6.8;
  const tokenTotal = (14.2 * rangeMultiplier).toFixed(1);
  const costTotal = (1240.5 * rangeMultiplier).toFixed(2);

  const filteredInferences = inferences.filter(
    (inf) =>
      inf.id.toLowerCase().includes(tableSearch.toLowerCase()) ||
      inf.modelRoute.toLowerCase().includes(tableSearch.toLowerCase())
  );

  return (
    <div className="space-y-6 pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <span className="text-[10px] uppercase tracking-[0.3em] text-[#C9A86A] font-semibold">
            Telemetry & Inferences
          </span>
          <h1 className="text-3xl md:text-4xl font-light tracking-tight text-white mt-1">
            System Telemetry
          </h1>
          <p className="font-code-sm text-xs text-white/40 mt-1 uppercase tracking-widest">
            Session_ID: 0x8F9A2B • UTC-Active
          </p>
        </div>

        {/* Time Range Filter */}
        <div className="flex items-center gap-1.5 p-1 bg-[#111111] border border-white/10 rounded-full">
          {(['1H', '24H', '7D'] as TimeRange[]).map((range) => {
            const isSelected = timeRange === range;
            return (
              <button
                key={range}
                onClick={() => setTimeRange(range)}
                className={`px-4 py-1.5 font-code-sm text-xs rounded-full transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_12px_rgba(201,168,106,0.3)]'
                    : 'text-white/40 hover:text-white hover:bg-white/5'
                }`}
              >
                {range}
              </button>
            );
          })}
        </div>
      </div>

      {/* KPI Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1 */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Total Tokens</span>
            <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">data_usage</span>
          </div>
          <div className="text-3xl md:text-4xl font-light text-white tracking-tight">{tokenTotal}M</div>
          <div className="font-code-sm text-xs text-[#4ADE80] mt-3 flex items-center gap-1">
            <span className="material-symbols-outlined text-[14px]">arrow_upward</span> 12.4% vs prev
          </div>
        </div>

        {/* KPI 2 */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Total Est. Cost</span>
            <span className="material-symbols-outlined text-white text-[20px]">attach_money</span>
          </div>
          <div className="text-3xl md:text-4xl font-light text-white tracking-tight">${costTotal}</div>
          <div className="font-code-sm text-xs text-white/40 mt-3 flex items-center gap-1">
            Blend: GPT-5.6 / Claude 3.7
          </div>
        </div>

        {/* KPI 3 */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Cache Hit Rate</span>
            <span className="material-symbols-outlined text-[#C9A86A] text-[20px]">memory_alt</span>
          </div>
          <div className="text-3xl md:text-4xl font-light text-white tracking-tight">68.4%</div>
          <div className="font-code-sm text-xs text-[#E5A93C] mt-3 flex items-center gap-1">
            <span className="material-symbols-outlined text-[14px]">arrow_downward</span> 2.1% dip
          </div>
        </div>

        {/* KPI 4 */}
        <div className="bg-[#111111] border border-white/10 p-6 rounded-3xl flex flex-col justify-between hover:border-white/20 transition-all">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Avg Latency</span>
            <span className="material-symbols-outlined text-white/40 text-[20px]">speed</span>
          </div>
          <div className="text-3xl md:text-4xl font-light text-white tracking-tight">420ms</div>
          <div className="font-code-sm text-xs text-white/60 mt-3 flex items-center gap-1">
            P95: 1.2s
          </div>
        </div>
      </div>

      {/* Main Split Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Chart (Spans 2 columns) */}
        <div className="lg:col-span-2 bg-[#111111] border border-white/10 rounded-3xl flex flex-col overflow-hidden">
          <div className="p-6 border-b border-white/10 flex flex-wrap justify-between items-center gap-3">
            <div>
              <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Consumption</span>
              <h2 className="text-lg font-light text-white">
                Model Token Distribution
              </h2>
            </div>
            <div className="flex flex-wrap gap-4 font-code-sm text-xs">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-[#C9A86A] rounded-full shadow-[0_0_8px_#C9A86A]"></span> GPT-5.6
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-white rounded-full shadow-[0_0_8px_white]"></span> Gemini 3.7
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-white/40 rounded-full"></span> Claude 3.7
              </div>
            </div>
          </div>

          {/* Chart Area */}
          <div className="flex-1 p-6 relative min-h-[300px] md:min-h-[340px] flex items-end justify-between gap-1.5 pb-10">
            {/* Y Axis Guide Lines */}
            <div className="absolute inset-x-6 top-6 bottom-10 flex flex-col justify-between pointer-events-none z-0">
              <div className="border-t border-white/5 w-full"></div>
              <div className="border-t border-white/5 w-full"></div>
              <div className="border-t border-white/5 w-full"></div>
              <div className="border-t border-white/5 w-full"></div>
            </div>

            {/* Y Axis Labels */}
            <div className="absolute left-3 top-6 bottom-10 flex flex-col justify-between pointer-events-none z-0 font-code-sm text-[10px] text-white/30">
              <span>1M</span>
              <span>750k</span>
              <span>500k</span>
              <span>250k</span>
              <span>0</span>
            </div>

            {/* Render Stacked Bars */}
            {consumptionData.map((d, i) => {
              const totalK = d.gpt5 + d.gemini + d.claude;
              const isHovered = hoveredBar === i;
              return (
                <div
                  key={i}
                  onMouseEnter={() => setHoveredBar(i)}
                  onMouseLeave={() => setHoveredBar(null)}
                  className="flex-1 h-full flex flex-col justify-end gap-0.5 group z-10 relative cursor-pointer"
                >
                  <div
                    className="w-full bg-white/40 group-hover:bg-white/60 transition-all rounded-t-sm"
                    style={{ height: `${d.claude}%` }}
                  ></div>
                  <div
                    className="w-full bg-white group-hover:bg-white transition-all shadow-[0_0_10px_rgba(255,255,255,0.2)]"
                    style={{ height: `${d.gemini}%` }}
                  ></div>
                  <div
                    className="w-full bg-[#C9A86A] group-hover:bg-[#dfc188] transition-all shadow-[0_0_10px_rgba(201,168,106,0.3)]"
                    style={{ height: `${d.gpt5}%` }}
                  ></div>

                  {/* Tooltip */}
                  {isHovered && (
                    <div className="absolute -top-16 left-1/2 -translate-x-1/2 bg-[#050505] border border-[#C9A86A] px-3 py-2 rounded-xl font-code-sm text-xs text-white whitespace-nowrap z-30 pointer-events-none shadow-[0_0_20px_rgba(0,0,0,0.9)]">
                      <div className="text-[#C9A86A] font-semibold">Total: {totalK}k tokens</div>
                      <div className="text-[10px] text-white/50">
                        GPT: {d.gpt5}k | Gem: {d.gemini}k | Cl: {d.claude}k
                      </div>
                    </div>
                  )}

                  <span className="absolute -bottom-6 left-1/2 -translate-x-1/2 font-code-sm text-[10px] text-white/40 whitespace-nowrap">
                    {d.timeLabel}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Efficiency Scoreboard (Bento Grid) */}
        <div className="grid grid-cols-1 grid-rows-3 gap-4">
          {/* Bento Box 1 */}
          <div className="bg-[#111111] border border-white/10 p-5 rounded-3xl relative overflow-hidden flex flex-col justify-between">
            <div className="absolute -right-4 -top-4 w-24 h-24 bg-[#C9A86A]/5 rounded-full blur-xl pointer-events-none"></div>
            <div className="flex justify-between items-start">
              <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Ponytail Metric</span>
              <span className="material-symbols-outlined text-white/30 text-[16px]">content_cut</span>
            </div>
            <div>
              <div className="text-2xl font-light text-white">1 : 4.2</div>
              <div className="font-code-sm text-xs text-[#C9A86A] mt-1">Deleted vs Written</div>
            </div>
            <div className="w-full bg-white/10 h-1.5 mt-3 rounded-full overflow-hidden">
              <div className="bg-[#C9A86A] h-full rounded-full" style={{ width: '25%' }}></div>
            </div>
          </div>

          {/* Bento Box 2 */}
          <div className="bg-[#111111] border border-white/10 p-5 rounded-3xl relative overflow-hidden flex flex-col justify-between">
            <div className="absolute -right-4 -top-4 w-24 h-24 bg-white/5 rounded-full blur-xl pointer-events-none"></div>
            <div className="flex justify-between items-start">
              <span className="text-[10px] uppercase tracking-[0.25em] text-white/40">Cost / Feature</span>
              <span className="material-symbols-outlined text-white/30 text-[16px]">point_of_sale</span>
            </div>
            <div>
              <div className="text-2xl font-light text-white">$2.45</div>
              <div className="font-code-sm text-xs text-white/40 mt-1">Avg 350 lines per feature</div>
            </div>
            <div className="w-full bg-white/10 h-1.5 mt-3 rounded-full overflow-hidden">
              <div className="bg-white h-full rounded-full" style={{ width: '60%' }}></div>
            </div>
          </div>

          {/* Bento Box 3 with CRT overlay */}
          <div className="bg-[#0c0c0c] border border-white/10 p-5 rounded-3xl relative overflow-hidden flex flex-col justify-between crt-overlay">
            <div className="flex justify-between items-start relative z-10">
              <span className="text-[10px] uppercase tracking-[0.25em] text-[#C9A86A]">Reasoning Overhead</span>
              <span className="material-symbols-outlined text-[#C9A86A] text-[16px] animate-pulse">psychology</span>
            </div>
            <div className="relative z-10">
              <div className="text-2xl font-light text-white">32%</div>
              <div className="font-code-sm text-xs text-white/40 mt-1">Tokens spent on CoT</div>
            </div>
            {/* Micro sparkline */}
            <div className="flex items-end gap-1.5 h-6 mt-2 relative z-10 opacity-80">
              <div className="w-full bg-[#C9A86A]/20 h-[20%] rounded-xs"></div>
              <div className="w-full bg-[#C9A86A]/40 h-[40%] rounded-xs"></div>
              <div className="w-full bg-[#C9A86A]/70 h-[30%] rounded-xs"></div>
              <div className="w-full bg-[#C9A86A]/50 h-[70%] rounded-xs"></div>
              <div className="w-full bg-[#C9A86A] h-[90%] rounded-xs shadow-[0_0_8px_#C9A86A]"></div>
            </div>
          </div>
        </div>
      </div>

      {/* Terminal / Data Table */}
      <div className="bg-[#111111] border border-white/10 rounded-3xl overflow-hidden">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between p-5 border-b border-white/10 bg-[#141414] gap-3">
          <div className="text-xs uppercase tracking-[0.2em] text-white flex items-center gap-2">
            <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">list_alt</span>
            <span>Recent Inferences</span>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Filter tasks..."
              value={tableSearch}
              onChange={(e) => setTableSearch(e.target.value)}
              className="bg-[#0c0c0c] border border-white/10 rounded-full px-4 py-1.5 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A]"
            />
            <div className="font-code-sm text-xs text-white/40 whitespace-nowrap">
              {filteredInferences.length} tasks recorded
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/10 text-[10px] text-white/40 uppercase tracking-[0.2em] bg-white/[0.02]">
                <th className="px-6 py-3.5 font-medium">Task ID</th>
                <th className="px-6 py-3.5 font-medium">Model Route</th>
                <th className="px-6 py-3.5 font-medium">Tokens (In / Out)</th>
                <th className="px-6 py-3.5 font-medium">Latency</th>
                <th className="px-6 py-3.5 font-medium">Resource Impact</th>
                <th className="px-6 py-3.5 font-medium text-right">Cost (USD)</th>
              </tr>
            </thead>
            <tbody className="font-code-sm text-xs text-white/80">
              {filteredInferences.map((row, idx) => {
                const isEven = idx % 2 === 0;
                return (
                  <tr
                    key={row.id}
                    onClick={() => onSelectInference?.(row)}
                    className={`border-b border-white/5 hover:bg-white/[0.04] transition-colors cursor-pointer ${
                      isEven ? 'bg-transparent' : 'bg-white/[0.01]'
                    }`}
                  >
                    <td className="px-6 py-3 text-[#C9A86A] font-medium">{row.id}</td>
                    <td className="px-6 py-3 flex items-center gap-2">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          row.modelColor === 'primary'
                            ? 'bg-[#C9A86A] shadow-[0_0_6px_#C9A86A]'
                            : row.modelColor === 'secondary'
                            ? 'bg-white shadow-[0_0_6px_white]'
                            : row.modelColor === 'tertiary'
                            ? 'bg-white/60'
                            : 'bg-white/30'
                        }`}
                      ></span>
                      <span className="text-white">{row.modelRoute}</span>
                    </td>
                    <td className="px-6 py-3 text-white/40">
                      <span className="text-white">{row.tokensIn.toLocaleString()}</span> /{' '}
                      <span className="text-white/60">{row.tokensOut.toLocaleString()}</span>
                    </td>
                    <td className="px-6 py-3">
                      {row.status === 'warning' ? (
                        <span className="text-[#E5A93C] flex items-center gap-1 font-semibold">
                          {row.latency}{' '}
                          <span className="material-symbols-outlined text-[13px]">warning</span>
                        </span>
                      ) : row.latencyMs < 300 ? (
                        <span className="text-[#4ADE80] font-semibold">{row.latency}</span>
                      ) : (
                        <span>{row.latency}</span>
                      )}
                    </td>
                    <td className="px-6 py-3 text-white/40">{row.resourceImpact}</td>
                    <td className="px-6 py-3 text-right font-semibold text-white">
                      ${row.cost.toFixed(3)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
