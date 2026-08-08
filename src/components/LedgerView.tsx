import React, { useState, useMemo } from 'react';
import { Transaction, Category, AppSettings, TransactionType } from '../types';
import {
  Search,
  Calendar,
  Filter,
  ArrowUpDown,
  Edit2,
  Trash2,
  Plus,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  ShieldCheck
} from 'lucide-react';

interface LedgerViewProps {
  transactions: Transaction[];
  categories: Category[];
  settings: AppSettings;
  onEdit: (tx: Transaction) => void;
  onDelete: (id: string) => void;
  onOpenAddModal: () => void;
}

type DatePreset = 'cycle' | 'month' | '30days' | 'year' | 'all';

export const LedgerView: React.FC<LedgerViewProps> = ({
  transactions,
  categories,
  settings,
  onEdit,
  onDelete,
  onOpenAddModal
}) => {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [selectedType, setSelectedType] = useState('all');
  const [selectedPerson, setSelectedPerson] = useState('all');
  const [datePreset, setDatePreset] = useState<DatePreset>('all');
  const [sortKey, setSortKey] = useState<'date' | 'value'>('date');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');
  const [pageSize, setPageSize] = useState<number>(50);
  const [currentPage, setCurrentPage] = useState<number>(1);

  // Date range filter calculations
  const filteredByDate = useMemo(() => {
    if (datePreset === 'all') return transactions;

    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth();

    if (datePreset === 'month') {
      const start = `${y}-${String(m + 1).padStart(2, '0')}-01`;
      return transactions.filter(t => t.date >= start);
    }

    if (datePreset === '30days') {
      const past30 = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      const start = past30.toISOString().slice(0, 10);
      return transactions.filter(t => t.date >= start);
    }

    if (datePreset === 'year') {
      const start = `${y}-01-01`;
      return transactions.filter(t => t.date >= start);
    }

    return transactions;
  }, [transactions, datePreset]);

  // Search & Type/Category/Person Filters
  const filteredList = useMemo(() => {
    let result = [...filteredByDate];

    if (search.trim()) {
      const q = search.toLowerCase().trim();
      result = result.filter(
        t =>
          t.description.toLowerCase().includes(q) ||
          t.category.toLowerCase().includes(q) ||
          t.person.toLowerCase().includes(q) ||
          t.currency.toLowerCase().includes(q)
      );
    }

    if (selectedCategory !== 'all') {
      result = result.filter(t => t.category.toLowerCase() === selectedCategory.toLowerCase());
    }

    if (selectedType !== 'all') {
      result = result.filter(t => t.type.toLowerCase() === selectedType.toLowerCase());
    }

    if (selectedPerson !== 'all') {
      result = result.filter(t => t.person.toLowerCase() === selectedPerson.toLowerCase());
    }

    // Sorting
    result.sort((a, b) => {
      if (sortKey === 'value') {
        return sortOrder === 'asc' ? a.valueBase - b.valueBase : b.valueBase - a.valueBase;
      }
      return sortOrder === 'asc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date);
    });

    return result;
  }, [filteredByDate, search, selectedCategory, selectedType, selectedPerson, sortKey, sortOrder]);

  // Page Calculations
  const totalPages = Math.max(1, Math.ceil(filteredList.length / pageSize));
  const pageIndex = Math.min(currentPage, totalPages);
  const pagedList = useMemo(() => {
    const start = (pageIndex - 1) * pageSize;
    return filteredList.slice(start, start + pageSize);
  }, [filteredList, pageIndex, pageSize]);

  // Totals for filtered list
  const totalIncome = useMemo(
    () => filteredList.filter(t => t.type === 'Income').reduce((sum, t) => sum + t.valueBase, 0),
    [filteredList]
  );
  const totalExpenses = useMemo(
    () => filteredList.filter(t => t.type === 'Expense').reduce((sum, t) => sum + t.valueBase, 0),
    [filteredList]
  );
  const totalSavings = useMemo(
    () => filteredList.filter(t => t.type === 'Savings').reduce((sum, t) => sum + t.valueBase, 0),
    [filteredList]
  );

  // Group paged transactions by date
  const groupedByDate = useMemo(() => {
    const groups: { [date: string]: Transaction[] } = {};
    pagedList.forEach(t => {
      if (!groups[t.date]) groups[t.date] = [];
      groups[t.date].push(t);
    });
    return groups;
  }, [pagedList]);

  const getTypeBadge = (type: TransactionType) => {
    if (type === 'Income') {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          <TrendingUp className="w-3 h-3 mr-1" /> Income
        </span>
      );
    }
    if (type === 'Savings') {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-sky-500/10 text-sky-400 border border-sky-500/20">
          <ShieldCheck className="w-3 h-3 mr-1" /> Savings
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
        <TrendingDown className="w-3 h-3 mr-1" /> Expense
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Top Ledger Header & Quick Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-slate-400">Total Income</p>
            <p className="text-xl font-bold text-emerald-400 mt-1">
              +{settings.baseCurrency} {totalIncome.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
            <TrendingUp className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-slate-400">Total Expenses</p>
            <p className="text-xl font-bold text-amber-400 mt-1">
              -{settings.baseCurrency} {totalExpenses.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
            <TrendingDown className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-slate-400">Total Savings</p>
            <p className="text-xl font-bold text-sky-400 mt-1">
              +{settings.baseCurrency} {totalSavings.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Control Bar: Search, Date Presets, Filters */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
        {/* Date Presets Row */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-slate-400 mr-1 flex items-center">
              <Calendar className="w-3.5 h-3.5 mr-1" /> Range:
            </span>
            {[
              { id: 'all', label: 'All Time' },
              { id: 'month', label: 'This Month' },
              { id: '30days', label: 'Last 30 Days' },
              { id: 'year', label: 'This Year' }
            ].map(preset => (
              <button
                key={preset.id}
                onClick={() => {
                  setDatePreset(preset.id as DatePreset);
                  setCurrentPage(1);
                }}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-all cursor-pointer ${
                  datePreset === preset.id
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                    : 'bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700/50'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <button
            onClick={onOpenAddModal}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium transition-all shadow-xs"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Transaction</span>
          </button>
        </div>

        {/* Filters and Search Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 pt-2 border-t border-slate-800">
          {/* Search */}
          <div className="relative col-span-1 sm:col-span-2">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search description, category, member..."
              value={search}
              onChange={e => {
                setSearch(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full bg-slate-800 border border-slate-700/70 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-hidden focus:border-emerald-500 transition-colors"
            />
          </div>

          {/* Type Filter */}
          <div>
            <select
              value={selectedType}
              onChange={e => {
                setSelectedType(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full bg-slate-800 border border-slate-700/70 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-hidden focus:border-emerald-500"
            >
              <option value="all">All Types</option>
              <option value="Expense">Expense</option>
              <option value="Income">Income</option>
              <option value="Savings">Savings</option>
            </select>
          </div>

          {/* Category Filter */}
          <div>
            <select
              value={selectedCategory}
              onChange={e => {
                setSelectedCategory(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full bg-slate-800 border border-slate-700/70 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-hidden focus:border-emerald-500"
            >
              <option value="all">All Categories</option>
              {categories.map(c => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {/* Person Filter */}
          <div>
            <select
              value={selectedPerson}
              onChange={e => {
                setSelectedPerson(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full bg-slate-800 border border-slate-700/70 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-hidden focus:border-emerald-500"
            >
              <option value="all">All Members</option>
              {settings.persons.map(p => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Transactions Table / List */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        {Object.keys(groupedByDate).length === 0 ? (
          <div className="p-12 text-center">
            <Filter className="w-10 h-10 text-slate-600 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-slate-300">No transactions found</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
              Try adjusting your date range, search query, or filters, or add a new transaction.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-800">
            {Object.entries(groupedByDate).map(([dateStr, items]: [string, Transaction[]]) => {
              const dayTotalExpense = items
                .filter(i => i.type === 'Expense')
                .reduce((s, i) => s + i.valueBase, 0);
              const dayTotalIncome = items
                .filter(i => i.type === 'Income')
                .reduce((s, i) => s + i.valueBase, 0);

              return (
                <div key={dateStr} className="divide-y divide-slate-800/60">
                  {/* Sticky Day Header */}
                  <div className="sticky top-16 z-10 bg-slate-800/90 backdrop-blur-xs px-4 py-2 flex items-center justify-between border-y border-slate-700/50">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-bold text-slate-200">{dateStr}</span>
                      <span className="text-[11px] text-slate-400">
                        ({items.length} {items.length === 1 ? 'item' : 'items'})
                      </span>
                    </div>
                    <div className="flex items-center space-x-3 text-xs font-medium">
                      {dayTotalIncome > 0 && (
                        <span className="text-emerald-400">
                          +{settings.baseCurrency} {dayTotalIncome.toFixed(2)}
                        </span>
                      )}
                      {dayTotalExpense > 0 && (
                        <span className="text-amber-400">
                          -{settings.baseCurrency} {dayTotalExpense.toFixed(2)}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Day Items List */}
                  {items.map(tx => (
                    <div
                      key={tx.id}
                      className="px-4 py-3 hover:bg-slate-800/40 transition-colors flex items-center justify-between gap-4 group"
                    >
                      <div className="flex items-center space-x-3 min-w-0 flex-1">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center space-x-2 flex-wrap">
                            <span className="text-xs font-semibold text-slate-100 truncate">
                              {tx.description || tx.category}
                            </span>
                            {getTypeBadge(tx.type)}
                            <span className="text-[11px] px-2 py-0.5 rounded-sm bg-slate-800 text-slate-300 border border-slate-700">
                              {tx.category}
                            </span>
                            <span className="text-[11px] px-1.5 py-0.5 rounded-sm bg-slate-800/60 text-slate-400">
                              {tx.person}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Right Amount & Actions */}
                      <div className="flex items-center space-x-3 shrink-0">
                        <div className="text-right">
                          <p
                            className={`text-sm font-bold ${
                              tx.type === 'Income'
                                ? 'text-emerald-400'
                                : tx.type === 'Savings'
                                ? 'text-sky-400'
                                : 'text-amber-400'
                            }`}
                          >
                            {tx.type === 'Income' ? '+' : '-'} {tx.currency}{' '}
                            {tx.value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </p>
                          {tx.currency !== settings.baseCurrency && (
                            <p className="text-[10px] text-slate-500">
                              ≈ {settings.baseCurrency} {tx.valueBase.toFixed(2)}
                            </p>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center space-x-1 opacity-80 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => onEdit(tx)}
                            title="Edit"
                            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-md transition-colors"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => onDelete(tx.id)}
                            title="Delete"
                            className="p-1.5 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded-md transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {/* Footer Pagination */}
        <div className="px-4 py-3 bg-slate-900 border-t border-slate-800 flex items-center justify-between flex-wrap gap-3 text-xs text-slate-400">
          <div className="flex items-center space-x-2">
            <span>Rows per page:</span>
            <select
              value={pageSize}
              onChange={e => {
                setPageSize(Number(e.target.value));
                setCurrentPage(1);
              }}
              className="bg-slate-800 border border-slate-700 text-slate-200 rounded-md px-2 py-1 text-xs"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <span>
              Showing {filteredList.length === 0 ? 0 : (pageIndex - 1) * pageSize + 1} -{' '}
              {Math.min(pageIndex * pageSize, filteredList.length)} of {filteredList.length}
            </span>
          </div>

          <div className="flex items-center space-x-1">
            <button
              disabled={pageIndex <= 1}
              onClick={() => setCurrentPage(p => p - 1)}
              className="p-1.5 rounded-md bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-700 cursor-pointer"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-2 font-medium">
              Page {pageIndex} of {totalPages}
            </span>
            <button
              disabled={pageIndex >= totalPages}
              onClick={() => setCurrentPage(p => p + 1)}
              className="p-1.5 rounded-md bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-700 cursor-pointer"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
