import React, { useState } from 'react';
import { AppSettings, Category, CurrencyRate } from '../types';
import {
  Settings as SettingsIcon,
  DollarSign,
  Tag,
  Users,
  Download,
  Plus,
  Trash2,
  Check,
  Save
} from 'lucide-react';

interface SettingsViewProps {
  settings: AppSettings;
  currencies: CurrencyRate[];
  categories: Category[];
  onUpdateSettings: (newSettings: Partial<AppSettings>) => Promise<void>;
  onUpdateCurrency: (code: string, rateToBase: number, symbol: string) => Promise<void>;
  onSaveCategory: (category: Category) => Promise<void>;
  onDeleteCategory: (name: string) => Promise<void>;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  settings,
  currencies,
  categories,
  onUpdateSettings,
  onUpdateCurrency,
  onSaveCategory,
  onDeleteCategory
}) => {
  // New Category Form State
  const [newCatName, setNewCatName] = useState('');
  const [newCatType, setNewCatType] = useState<'Expense' | 'Income' | 'Savings'>('Expense');
  const [newCatBudget, setNewCatBudget] = useState('');

  // New Person Form State
  const [newPersonName, setNewPersonName] = useState('');

  // New Currency State
  const [newCurrCode, setNewCurrCode] = useState('');
  const [newCurrRate, setNewCurrRate] = useState('');
  const [newCurrSymbol, setNewCurrSymbol] = useState('');

  const handleAddCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCatName.trim()) return;

    await onSaveCategory({
      name: newCatName.trim(),
      type: newCatType,
      budgetTargetBase: parseFloat(newCatBudget) || 0
    });

    setNewCatName('');
    setNewCatBudget('');
  };

  const handleAddPerson = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPersonName.trim()) return;

    if (!settings.persons.includes(newPersonName.trim())) {
      const updated = [...settings.persons, newPersonName.trim()];
      await onUpdateSettings({ persons: updated });
    }
    setNewPersonName('');
  };

  const handleDeletePerson = async (personName: string) => {
    const updated = settings.persons.filter(p => p !== personName);
    await onUpdateSettings({ persons: updated });
  };

  const handleAddCurrency = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCurrCode.trim()) return;

    await onUpdateCurrency(
      newCurrCode.trim().toUpperCase(),
      parseFloat(newCurrRate) || 1.0,
      newCurrSymbol.trim() || newCurrCode.trim().toUpperCase()
    );

    setNewCurrCode('');
    setNewCurrRate('');
    setNewCurrSymbol('');
  };

  const handleExportData = () => {
    window.open('/api/export', '_blank');
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <SettingsIcon className="w-5 h-5 text-emerald-400" />
            System & Budget Configuration
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Manage base currencies, exchange rates, category budget targets, and family members.
          </p>
        </div>

        <button
          onClick={handleExportData}
          className="flex items-center space-x-1.5 px-3.5 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-lg text-xs font-semibold transition-all cursor-pointer"
        >
          <Download className="w-4 h-4 text-emerald-400" />
          <span>Export JSON Data</span>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Currencies & Base Settings */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-2">
            <DollarSign className="w-4 h-4 text-emerald-400" />
            Base Currency & Exchange Rates
          </h3>

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Base Currency (Global Accounting Unit)
              </label>
              <select
                value={settings.baseCurrency}
                onChange={e => onUpdateSettings({ baseCurrency: e.target.value })}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-hidden focus:border-emerald-500"
              >
                {currencies.map(c => (
                  <option key={c.code} value={c.code}>
                    {c.code} ({c.symbol})
                  </option>
                ))}
              </select>
            </div>

            {/* Exchange Rates Table */}
            <div className="space-y-2 pt-2">
              <span className="text-xs font-medium text-slate-300">Configured Currencies</span>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {currencies.map(c => (
                  <div
                    key={c.code}
                    className="flex items-center justify-between p-2.5 bg-slate-800/50 rounded-lg border border-slate-800 text-xs"
                  >
                    <div className="flex items-center space-x-2">
                      <span className="font-bold text-slate-100">{c.code}</span>
                      <span className="text-slate-400">({c.symbol})</span>
                    </div>

                    <div className="flex items-center space-x-2">
                      <span className="text-slate-400">Rate:</span>
                      <input
                        type="number"
                        step="0.0001"
                        defaultValue={c.rateToBase}
                        onBlur={e =>
                          onUpdateCurrency(c.code, parseFloat(e.target.value) || 1.0, c.symbol)
                        }
                        className="w-20 bg-slate-800 border border-slate-700 rounded-md px-2 py-0.5 text-slate-100 font-mono text-xs text-right"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Add Currency Form */}
            <form onSubmit={handleAddCurrency} className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800">
              <input
                type="text"
                placeholder="Code e.g. CAD"
                value={newCurrCode}
                onChange={e => setNewCurrCode(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-100"
              />
              <input
                type="number"
                step="0.01"
                placeholder="Rate to Base"
                value={newCurrRate}
                onChange={e => setNewCurrRate(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-100"
              />
              <button
                type="submit"
                className="flex items-center justify-center space-x-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md text-xs font-semibold"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add</span>
              </button>
            </form>
          </div>
        </div>

        {/* Family Members / Persons */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-2">
            <Users className="w-4 h-4 text-emerald-400" />
            Family Members / Persons
          </h3>

          <div className="space-y-3">
            <div className="space-y-1.5">
              {settings.persons.map(p => (
                <div
                  key={p}
                  className="flex items-center justify-between p-2.5 bg-slate-800/50 rounded-lg border border-slate-800 text-xs"
                >
                  <span className="font-semibold text-slate-100">{p}</span>
                  {settings.persons.length > 1 && (
                    <button
                      onClick={() => handleDeletePerson(p)}
                      className="p-1 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded-md transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>

            {/* Add Person Form */}
            <form onSubmit={handleAddPerson} className="flex space-x-2 pt-2 border-t border-slate-800">
              <input
                type="text"
                placeholder="New family member name..."
                value={newPersonName}
                onChange={e => setNewPersonName(e.target.value)}
                className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
              />
              <button
                type="submit"
                className="flex items-center space-x-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Member</span>
              </button>
            </form>
          </div>
        </div>
      </div>

      {/* Categories & Monthly Budget Targets */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-bold text-slate-200 flex items-center justify-between border-b border-slate-800 pb-2">
          <span className="flex items-center gap-2">
            <Tag className="w-4 h-4 text-emerald-400" />
            Categories & Monthly Budget Targets ({settings.baseCurrency})
          </span>
        </h3>

        {/* Categories Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {categories.map(cat => (
            <div
              key={cat.name}
              className="p-3 bg-slate-800/40 border border-slate-800 rounded-xl flex items-center justify-between gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center space-x-2">
                  <span className="font-bold text-xs text-slate-100 truncate">{cat.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-slate-800 text-slate-400">
                    {cat.type}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 mt-1 flex items-center space-x-1">
                  <span>Target:</span>
                  <input
                    type="number"
                    step="10"
                    defaultValue={cat.budgetTargetBase}
                    onBlur={e =>
                      onSaveCategory({
                        ...cat,
                        budgetTargetBase: parseFloat(e.target.value) || 0
                      })
                    }
                    className="w-20 bg-slate-800 border border-slate-700/80 rounded-md px-1.5 py-0.5 text-slate-100 text-xs font-semibold"
                  />
                  <span>{settings.baseCurrency}</span>
                </div>
              </div>

              <button
                onClick={() => onDeleteCategory(cat.name)}
                className="p-1 text-slate-500 hover:text-rose-400 rounded-md transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>

        {/* Add Category Form */}
        <form onSubmit={handleAddCategory} className="grid grid-cols-1 sm:grid-cols-4 gap-3 pt-4 border-t border-slate-800">
          <input
            type="text"
            required
            placeholder="Category Name"
            value={newCatName}
            onChange={e => setNewCatName(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
          />

          <select
            value={newCatType}
            onChange={e => setNewCatType(e.target.value as any)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
          >
            <option value="Expense">Expense</option>
            <option value="Income">Income</option>
            <option value="Savings">Savings</option>
          </select>

          <input
            type="number"
            step="10"
            placeholder="Target Budget Amount"
            value={newCatBudget}
            onChange={e => setNewCatBudget(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
          />

          <button
            type="submit"
            className="flex items-center justify-center space-x-1 px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Create Category</span>
          </button>
        </form>
      </div>
    </div>
  );
};
