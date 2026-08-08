import React, { useState, useEffect } from 'react';
import { SummaryReport, BudgetCycle, AppSettings } from '../types';
import {
  TrendingUp,
  TrendingDown,
  ShieldCheck,
  Scale,
  PieChart as PieChartIcon,
  BarChart2,
  Calendar,
  AlertCircle
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid
} from 'recharts';

interface SummaryViewProps {
  cycles: BudgetCycle[];
  settings: AppSettings;
}

export const SummaryView: React.FC<SummaryViewProps> = ({ cycles, settings }) => {
  const [selectedCycleId, setSelectedCycleId] = useState<string>('');
  const [summary, setSummary] = useState<SummaryReport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (cycles.length > 0 && !selectedCycleId) {
      setSelectedCycleId(cycles[0].id);
    }
  }, [cycles, selectedCycleId]);

  useEffect(() => {
    fetchSummary();
  }, [selectedCycleId]);

  const fetchSummary = async () => {
    setLoading(true);
    try {
      const url = selectedCycleId
        ? `/api/summary?cycleId=${encodeURIComponent(selectedCycleId)}`
        : '/api/summary';
      const res = await fetch(url);
      const data = await res.json();
      setSummary(data);
    } catch (err) {
      console.error('Error fetching summary:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading || !summary) {
    return (
      <div className="p-12 text-center text-slate-400 bg-slate-900 border border-slate-800 rounded-xl">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-xs">Loading analytics and summary report...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header & Period Switcher */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-emerald-400" />
            Financial Summary & Analytics
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Period: <span className="text-slate-200 font-medium">{summary.periodLabel}</span> (
            {summary.startDate} to {summary.endDate})
          </p>
        </div>

        {/* Cycle selector */}
        <div className="flex items-center space-x-2">
          <Calendar className="w-4 h-4 text-slate-400" />
          <select
            value={selectedCycleId}
            onChange={e => setSelectedCycleId(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-100 rounded-lg px-3 py-1.5 text-xs focus:outline-hidden focus:border-emerald-500"
          >
            <option value="">All Time Summary</option>
            {cycles.map(c => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.startDate})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Hero Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Income */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Total Income</span>
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-extrabold text-emerald-400">
            {settings.baseCurrency} {summary.totalIncome.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </div>

        {/* Expenses */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Total Expenses</span>
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center">
              <TrendingDown className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-extrabold text-amber-400">
            {settings.baseCurrency} {summary.totalExpenses.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </div>

        {/* Savings */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Total Savings</span>
            <div className="w-8 h-8 rounded-lg bg-sky-500/10 text-sky-400 flex items-center justify-center">
              <ShieldCheck className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-extrabold text-sky-400">
            {settings.baseCurrency} {summary.totalSavings.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </div>

        {/* Unaccounted / Net */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">
              Unaccounted Buffer
            </span>
            <div className="w-8 h-8 rounded-lg bg-purple-500/10 text-purple-400 flex items-center justify-center">
              <Scale className="w-4 h-4" />
            </div>
          </div>
          <p
            className={`text-2xl font-extrabold ${
              (summary.unaccounted || 0) >= 0 ? 'text-purple-400' : 'text-rose-400'
            }`}
          >
            {settings.baseCurrency} {(summary.unaccounted || summary.net).toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </div>
      </div>

      {/* Daily Trends Bar Chart */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
          <BarChart2 className="w-4 h-4 text-emerald-400" />
          Daily Cash Flow Trends
        </h3>
        {summary.dailyTrends.length === 0 ? (
          <p className="text-xs text-slate-500 py-8 text-center">No transactions in selected period</p>
        ) : (
          <div className="h-64 w-full pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={summary.dailyTrends} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                <XAxis dataKey="date" stroke="#94A3B8" fontSize={11} tickLine={false} />
                <YAxis stroke="#94A3B8" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0F172A', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
                />
                <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }} />
                <Bar dataKey="income" name="Income" fill="#10B981" radius={[4, 4, 0, 0]} />
                <Bar dataKey="expenses" name="Expenses" fill="#F59E0B" radius={[4, 4, 0, 0]} />
                <Bar dataKey="savings" name="Savings" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Category Budget vs Actual Spend & Person Attribution Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Category Budget vs Actual (Col Span 2) */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-bold text-slate-200 flex items-center justify-between">
            <span>Category Spend vs Budget Targets</span>
            <span className="text-xs font-normal text-slate-400">
              {summary.categoryBreakdown.filter(c => c.type === 'Expense').length} categories
            </span>
          </h3>

          <div className="space-y-3">
            {summary.categoryBreakdown
              .filter(c => c.type === 'Expense')
              .sort((a, b) => b.actual - a.actual)
              .map(cat => {
                const isOver = cat.budget > 0 && cat.actual > cat.budget;
                return (
                  <div key={cat.category} className="space-y-1 bg-slate-800/40 p-3 rounded-lg border border-slate-800">
                    <div className="flex items-center justify-between text-xs font-medium">
                      <span className="text-slate-200 font-semibold">{cat.category}</span>
                      <div className="text-right">
                        <span className={isOver ? 'text-rose-400 font-bold' : 'text-slate-300'}>
                          {settings.baseCurrency} {cat.actual.toFixed(2)}
                        </span>
                        {cat.budget > 0 && (
                          <span className="text-slate-500 ml-1">
                            / {settings.baseCurrency} {cat.budget.toFixed(2)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Progress bar */}
                    {cat.budget > 0 && (
                      <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all rounded-full ${
                            isOver ? 'bg-rose-500' : 'bg-emerald-500'
                          }`}
                          style={{ width: `${Math.min(100, cat.percentage)}%` }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </div>

        {/* Person Attribution Breakdown */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
            <PieChartIcon className="w-4 h-4 text-emerald-400" />
            Expense by Family Member
          </h3>

          {summary.personBreakdown.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-6">No expenses logged</p>
          ) : (
            <div className="space-y-3">
              {summary.personBreakdown.map(p => (
                <div key={p.person} className="p-3 bg-slate-800/50 rounded-lg border border-slate-800 space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-200">{p.person}</span>
                    <span className="text-slate-300 font-bold">
                      {settings.baseCurrency} {p.amount.toFixed(2)} ({p.percentage}%)
                    </span>
                  </div>
                  <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-500 rounded-full"
                      style={{ width: `${p.percentage}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
