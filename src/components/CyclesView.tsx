import React, { useState } from 'react';
import { BudgetCycle, AppSettings } from '../types';
import { Repeat, Plus, Sparkles, Calendar, DollarSign, ArrowRight, ShieldCheck, TrendingDown } from 'lucide-react';

interface CyclesViewProps {
  cycles: BudgetCycle[];
  settings: AppSettings;
  onStartCycle: (startDate: string, label: string, salaryAmount: number) => void;
  onDetectCycles: () => void;
}

export const CyclesView: React.FC<CyclesViewProps> = ({
  cycles,
  settings,
  onStartCycle,
  onDetectCycles
}) => {
  const [showModal, setShowModal] = useState(false);
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [label, setLabel] = useState('');
  const [salaryAmount, setSalaryAmount] = useState('');

  const activeCycle = cycles[0];

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!startDate) return;
    onStartCycle(startDate, label || `Cycle starting ${startDate}`, parseFloat(salaryAmount) || 0);
    setShowModal(false);
  };

  return (
    <div className="space-y-6">
      {/* Intro Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Repeat className="w-5 h-5 text-emerald-400" />
            Salary-to-Salary Budget Cycles
          </h2>
          <p className="text-xs text-slate-400 mt-1 max-w-2xl">
            Instead of forcing calendar month boundaries (1st to 1st), track your household budget from payday to payday.
            Every cycle records salary income, expenses, savings, and unaccounted liquidity.
          </p>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          <button
            onClick={onDetectCycles}
            className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition-all cursor-pointer"
          >
            <Sparkles className="w-4 h-4 text-emerald-400" />
            <span>Auto-Detect Cycles</span>
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center space-x-1.5 px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-all cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Start New Cycle</span>
          </button>
        </div>
      </div>

      {/* Active Cycle Card */}
      {activeCycle && (
        <div className="bg-slate-900 border border-emerald-500/30 rounded-xl p-6 shadow-md relative overflow-hidden">
          <div className="absolute top-0 right-0 px-3 py-1 bg-emerald-500/10 text-emerald-400 text-xs font-semibold rounded-bl-xl border-l border-b border-emerald-500/20">
            Active Cycle
          </div>

          <div className="space-y-4">
            <div>
              <p className="text-xs font-medium text-slate-400">Current Cycle</p>
              <h3 className="text-xl font-extrabold text-slate-100 mt-0.5">{activeCycle.label}</h3>
              <p className="text-xs text-slate-400 mt-0.5 flex items-center gap-1">
                <Calendar className="w-3.5 h-3.5 text-slate-500" />
                Started: <span className="text-slate-200 font-medium">{activeCycle.startDate}</span>
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 pt-3 border-t border-slate-800">
              <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-800">
                <p className="text-xs text-slate-400">Salary Income</p>
                <p className="text-lg font-bold text-emerald-400 mt-1">
                  +{settings.baseCurrency} {activeCycle.salaryAmount.toFixed(2)}
                </p>
              </div>

              <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-800">
                <p className="text-xs text-slate-400">Tracked Expenses</p>
                <p className="text-lg font-bold text-amber-400 mt-1">
                  -{settings.baseCurrency} {activeCycle.totalExpenses.toFixed(2)}
                </p>
              </div>

              <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-800">
                <p className="text-xs text-slate-400">Tracked Savings</p>
                <p className="text-lg font-bold text-sky-400 mt-1">
                  +{settings.baseCurrency} {activeCycle.totalSavings.toFixed(2)}
                </p>
              </div>

              <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-800">
                <p className="text-xs text-slate-400">Unaccounted Buffer</p>
                <p className={`text-lg font-bold mt-1 ${activeCycle.unaccounted >= 0 ? 'text-purple-400' : 'text-rose-400'}`}>
                  {settings.baseCurrency} {activeCycle.unaccounted.toFixed(2)}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cycle History Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-800">
          <h3 className="text-sm font-bold text-slate-200">Budget Cycles Ledger</h3>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-800/60 text-slate-400 border-b border-slate-800">
              <tr>
                <th className="px-4 py-3 font-semibold">Cycle Label</th>
                <th className="px-4 py-3 font-semibold">Start Date</th>
                <th className="px-4 py-3 font-semibold">End Date</th>
                <th className="px-4 py-3 font-semibold text-right">Salary Income</th>
                <th className="px-4 py-3 font-semibold text-right">Expenses</th>
                <th className="px-4 py-3 font-semibold text-right">Savings</th>
                <th className="px-4 py-3 font-semibold text-right">Unaccounted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {cycles.map(c => (
                <tr key={c.id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-100">{c.label}</td>
                  <td className="px-4 py-3 text-slate-400">{c.startDate}</td>
                  <td className="px-4 py-3 text-slate-400">{c.endDate || 'Present'}</td>
                  <td className="px-4 py-3 text-right text-emerald-400 font-semibold">
                    +{settings.baseCurrency} {c.salaryAmount.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-amber-400 font-semibold">
                    -{settings.baseCurrency} {c.totalExpenses.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sky-400 font-semibold">
                    +{settings.baseCurrency} {c.totalSavings.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right font-bold text-purple-400">
                    {settings.baseCurrency} {c.unaccounted.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Start Cycle Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xs">
          <div className="bg-slate-900 border border-slate-800 rounded-xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-base font-bold text-slate-100">Start New Budget Cycle</h3>

            <form onSubmit={handleSubmit} className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Start Date (Payday) *
                </label>
                <input
                  type="date"
                  required
                  value={startDate}
                  onChange={e => setStartDate(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-xs focus:outline-hidden focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Cycle Label</label>
                <input
                  type="text"
                  placeholder="e.g. Sep 2026 Payday Cycle"
                  value={label}
                  onChange={e => setLabel(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-xs focus:outline-hidden focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Salary / Initial Amount ({settings.baseCurrency})
                </label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="5200.00"
                  value={salaryAmount}
                  onChange={e => setSalaryAmount(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-xs focus:outline-hidden focus:border-emerald-500"
                />
              </div>

              <div className="flex items-center justify-end space-x-2 pt-3">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-xs"
                >
                  Record Cycle
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
