import React, { useState, useEffect } from 'react';
import { LogEntry, LogLevel } from '../types';
import {
  FileText,
  Search,
  Filter,
  Calendar,
  Info,
  AlertTriangle,
  AlertOctagon,
  RotateCcw,
  Trash2,
  ChevronDown,
  ChevronUp,
  Clock,
  Layers,
  ArrowUpDown,
  RefreshCw
} from 'lucide-react';

interface LogsViewProps {
  // Option to trigger fresh fetch
}

type DatePreset = 'today' | 'yesterday' | 'last7' | 'month' | 'year' | 'all' | 'custom';

export const LogsView: React.FC<LogsViewProps> = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [countsByLevel, setCountsByLevel] = useState<{ INFO: number; WARNING: number; ERROR: number }>({
    INFO: 0,
    WARNING: 0,
    ERROR: 0
  });
  const [loading, setLoading] = useState<boolean>(true);

  // Filter States
  const [selectedLevel, setSelectedLevel] = useState<string>('ALL');
  const [selectedSource, setSelectedSource] = useState<string>('ALL');
  const [datePreset, setDatePreset] = useState<DatePreset>('all');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');

  // UI State
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const pageSize = 20;

  useEffect(() => {
    fetchLogs();
  }, [selectedLevel, selectedSource, datePreset, startDate, endDate, search, sortOrder]);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedLevel !== 'ALL') params.append('level', selectedLevel);
      if (selectedSource !== 'ALL') params.append('source', selectedSource);
      if (datePreset !== 'custom') params.append('datePreset', datePreset);
      if (datePreset === 'custom' && startDate) params.append('startDate', startDate);
      if (datePreset === 'custom' && endDate) params.append('endDate', endDate);
      if (search.trim()) params.append('search', search.trim());
      params.append('sort', sortOrder);

      const res = await fetch(`/api/logs?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
        setTotalCount(data.totalCount || 0);
        if (data.countsByLevel) {
          setCountsByLevel(data.countsByLevel);
        }
      }
    } catch (err) {
      console.error('Failed to fetch system logs:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleClearLogs = async () => {
    if (!confirm('Are you sure you want to clear all system activity logs?')) return;
    try {
      const res = await fetch('/api/logs/clear', { method: 'DELETE' });
      if (res.ok) {
        fetchLogs();
      }
    } catch (err) {
      console.error('Clear logs error:', err);
    }
  };

  const handleResetFilters = () => {
    setSelectedLevel('ALL');
    setSelectedSource('ALL');
    setDatePreset('all');
    setStartDate('');
    setEndDate('');
    setSearch('');
    setSortOrder('desc');
    setCurrentPage(1);
  };

  const isFiltered =
    selectedLevel !== 'ALL' ||
    selectedSource !== 'ALL' ||
    datePreset !== 'all' ||
    search.trim() !== '' ||
    startDate !== '' ||
    endDate !== '';

  // Pagination logic
  const totalPages = Math.max(1, Math.ceil(logs.length / pageSize));
  const pagedLogs = logs.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const getLevelBadge = (level: LogLevel) => {
    switch (level) {
      case 'INFO':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <Info className="w-3 h-3 mr-1" /> INFO
          </span>
        );
      case 'WARNING':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertTriangle className="w-3 h-3 mr-1" /> WARNING
          </span>
        );
      case 'ERROR':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <AlertOctagon className="w-3 h-3 mr-1" /> ERROR
          </span>
        );
    }
  };

  const formatDate = (isoStr: string) => {
    try {
      const d = new Date(isoStr);
      return d.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch (e) {
      return isoStr;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header & Quick Log Level Overview */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <FileText className="w-5 h-5 text-emerald-400" />
            System & Activity Logs
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Real-time audit trail of background operations, transaction modifications, budget cycle events, and system notifications.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchLogs}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition-all cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5 text-slate-400" />
            <span>Refresh</span>
          </button>
          <button
            onClick={handleClearLogs}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-rose-950/40 hover:bg-rose-900/50 text-rose-300 border border-rose-800/60 rounded-lg text-xs font-semibold transition-all cursor-pointer"
          >
            <Trash2 className="w-3.5 h-3.5 text-rose-400" />
            <span>Clear Logs</span>
          </button>
        </div>
      </div>

      {/* Log Stats Banner */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div
          onClick={() => {
            setSelectedLevel('ALL');
            setCurrentPage(1);
          }}
          className={`p-3.5 rounded-xl border transition-all cursor-pointer ${
            selectedLevel === 'ALL'
              ? 'bg-slate-800 border-slate-600 shadow-sm'
              : 'bg-slate-900/80 border-slate-800 hover:bg-slate-800/50'
          }`}
        >
          <div className="text-[11px] font-semibold text-slate-400">Total Entries</div>
          <div className="text-2xl font-black text-slate-100 mt-0.5">{totalCount}</div>
        </div>

        <div
          onClick={() => {
            setSelectedLevel('INFO');
            setCurrentPage(1);
          }}
          className={`p-3.5 rounded-xl border transition-all cursor-pointer ${
            selectedLevel === 'INFO'
              ? 'bg-emerald-950/40 border-emerald-500/50 shadow-sm'
              : 'bg-slate-900/80 border-slate-800 hover:bg-slate-800/50'
          }`}
        >
          <div className="text-[11px] font-semibold text-emerald-400 flex items-center gap-1">
            <Info className="w-3 h-3" /> Info Logs
          </div>
          <div className="text-2xl font-black text-emerald-400 mt-0.5">{countsByLevel.INFO}</div>
        </div>

        <div
          onClick={() => {
            setSelectedLevel('WARNING');
            setCurrentPage(1);
          }}
          className={`p-3.5 rounded-xl border transition-all cursor-pointer ${
            selectedLevel === 'WARNING'
              ? 'bg-amber-950/40 border-amber-500/50 shadow-sm'
              : 'bg-slate-900/80 border-slate-800 hover:bg-slate-800/50'
          }`}
        >
          <div className="text-[11px] font-semibold text-amber-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Warning Logs
          </div>
          <div className="text-2xl font-black text-amber-400 mt-0.5">{countsByLevel.WARNING}</div>
        </div>

        <div
          onClick={() => {
            setSelectedLevel('ERROR');
            setCurrentPage(1);
          }}
          className={`p-3.5 rounded-xl border transition-all cursor-pointer ${
            selectedLevel === 'ERROR'
              ? 'bg-rose-950/40 border-rose-500/50 shadow-sm'
              : 'bg-slate-900/80 border-slate-800 hover:bg-slate-800/50'
          }`}
        >
          <div className="text-[11px] font-semibold text-rose-400 flex items-center gap-1">
            <AlertOctagon className="w-3 h-3" /> Error Logs
          </div>
          <div className="text-2xl font-black text-rose-400 mt-0.5">{countsByLevel.ERROR}</div>
        </div>
      </div>

      {/* Modern Designer Filter Panel */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 space-y-4 shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
          <div className="flex items-center space-x-2">
            <Filter className="w-4 h-4 text-emerald-400" />
            <span className="text-xs font-bold text-slate-200 uppercase tracking-wider">
              Log Filter Controls
            </span>
          </div>

          {isFiltered && (
            <button
              onClick={handleResetFilters}
              className="flex items-center space-x-1 text-xs text-emerald-400 hover:text-emerald-300 font-semibold cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Filters</span>
            </button>
          )}
        </div>

        {/* Filter Rows */}
        <div className="space-y-3">
          {/* Level Filter Pills */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-400 w-16">Level:</span>
            {[
              { id: 'ALL', label: 'All Levels' },
              { id: 'INFO', label: 'Info Only' },
              { id: 'WARNING', label: 'Warnings' },
              { id: 'ERROR', label: 'Errors' }
            ].map(lvl => (
              <button
                key={lvl.id}
                onClick={() => {
                  setSelectedLevel(lvl.id);
                  setCurrentPage(1);
                }}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  selectedLevel === lvl.id
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-xs'
                    : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 border border-slate-700/60'
                }`}
              >
                {lvl.label}
              </button>
            ))}
          </div>

          {/* Date Range Presets */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-400 w-16">Period:</span>
            {[
              { id: 'all', label: 'All Time' },
              { id: 'today', label: 'Today' },
              { id: 'yesterday', label: 'Yesterday' },
              { id: 'last7', label: 'Last 7 Days' },
              { id: 'month', label: 'This Month' },
              { id: 'year', label: 'This Year' },
              { id: 'custom', label: 'Custom Range' }
            ].map(dp => (
              <button
                key={dp.id}
                onClick={() => {
                  setDatePreset(dp.id as DatePreset);
                  setCurrentPage(1);
                }}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  datePreset === dp.id
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-xs'
                    : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 border border-slate-700/60'
                }`}
              >
                {dp.label}
              </button>
            ))}
          </div>

          {/* Custom Date Inputs */}
          {datePreset === 'custom' && (
            <div className="flex flex-wrap items-center gap-3 pt-2 pl-18">
              <div className="flex items-center space-x-2">
                <span className="text-xs text-slate-400 font-medium">From:</span>
                <input
                  type="date"
                  value={startDate}
                  onChange={e => {
                    setStartDate(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-hidden focus:border-emerald-500"
                />
              </div>

              <div className="flex items-center space-x-2">
                <span className="text-xs text-slate-400 font-medium">To:</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={e => {
                    setEndDate(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-hidden focus:border-emerald-500"
                />
              </div>
            </div>
          )}

          {/* Grid Controls: Search, Source, Sort Order */}
          <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-4 gap-3 pt-2 border-t border-slate-800/80">
            {/* Search */}
            <div className="relative sm:col-span-2">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
              <input
                type="text"
                placeholder="Search logs message, action, details..."
                value={search}
                onChange={e => {
                  setSearch(e.target.value);
                  setCurrentPage(1);
                }}
                className="w-full bg-slate-800/80 border border-slate-700/70 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-hidden focus:border-emerald-500"
              />
            </div>

            {/* Source */}
            <div>
              <select
                value={selectedSource}
                onChange={e => {
                  setSelectedSource(e.target.value);
                  setCurrentPage(1);
                }}
                className="w-full bg-slate-800/80 border border-slate-700/70 rounded-xl px-3 py-1.5 text-xs text-slate-200 focus:outline-hidden focus:border-emerald-500"
              >
                <option value="ALL">All Sources</option>
                <option value="Transactions">Transactions</option>
                <option value="Cycles">Cycles</option>
                <option value="BulkImport">Bulk AI Import</option>
                <option value="Settings">Settings</option>
                <option value="Categories">Categories</option>
                <option value="Currencies">Currencies</option>
                <option value="System">System</option>
              </select>
            </div>

            {/* Sort Order */}
            <div>
              <button
                onClick={() => setSortOrder(prev => (prev === 'desc' ? 'asc' : 'desc'))}
                className="w-full flex items-center justify-between bg-slate-800/80 border border-slate-700/70 rounded-xl px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 cursor-pointer"
              >
                <span className="flex items-center gap-1.5">
                  <ArrowUpDown className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Order: {sortOrder === 'desc' ? 'Newest First' : 'Oldest First'}</span>
                </span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Log Feed Table / List */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-sm">
        {loading ? (
          <div className="p-12 text-center text-slate-400">
            <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-xs">Fetching system audit logs...</p>
          </div>
        ) : pagedLogs.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <FileText className="w-10 h-10 text-slate-600 mx-auto" />
            <p className="text-sm font-semibold text-slate-300">No logs found matching your criteria</p>
            <p className="text-xs text-slate-500">
              Try adjusting your level, date range, or search query.
            </p>
            {isFiltered && (
              <button
                onClick={handleResetFilters}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold mt-2 cursor-pointer"
              >
                Reset All Filters
              </button>
            )}
          </div>
        ) : (
          <div className="divide-y divide-slate-800/80">
            {pagedLogs.map(log => {
              const isExpanded = expandedLogId === log.id;
              return (
                <div key={log.id} className="p-4 hover:bg-slate-800/40 transition-colors">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-start sm:items-center space-x-3">
                      {getLevelBadge(log.level)}

                      <div>
                        <div className="flex items-center space-x-2">
                          <span className="text-xs font-bold text-slate-100">{log.message}</span>
                        </div>

                        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400 mt-1">
                          <span className="flex items-center gap-1 font-medium text-slate-300">
                            <Layers className="w-3 h-3 text-slate-500" />
                            {log.source}
                          </span>
                          <span>•</span>
                          <span className="px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 font-mono text-[10px]">
                            {log.action}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center justify-between sm:justify-end space-x-3 pt-2 sm:pt-0 border-t sm:border-t-0 border-slate-800/60">
                      <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
                        <Clock className="w-3 h-3 text-slate-500" />
                        {formatDate(log.timestamp)}
                      </span>

                      {log.details && (
                        <button
                          onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                          className="p-1 text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-800 cursor-pointer"
                        >
                          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Expanded Technical Details Drawer */}
                  {isExpanded && log.details && (
                    <div className="mt-3 p-3 bg-slate-950/80 rounded-xl border border-slate-800 text-xs font-mono text-slate-300 space-y-1 animate-in fade-in duration-150">
                      <p className="text-[10px] uppercase font-bold text-slate-500">Log Details</p>
                      <pre className="whitespace-pre-wrap break-words text-slate-300">{log.details}</pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Pagination Bar */}
        {totalPages > 1 && (
          <div className="p-4 bg-slate-900 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span>
              Showing {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, logs.length)} of {logs.length} logs
            </span>

            <div className="flex items-center space-x-1">
              <button
                disabled={currentPage === 1}
                onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-200 rounded-md transition-colors"
              >
                Previous
              </button>
              <span className="px-2 font-semibold text-slate-200">
                {currentPage} / {totalPages}
              </span>
              <button
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
                className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-200 rounded-md transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
