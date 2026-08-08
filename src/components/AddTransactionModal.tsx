import React, { useState, useEffect } from 'react';
import { Transaction, Category, AppSettings, TransactionType } from '../types';
import { X, Check } from 'lucide-react';

interface AddTransactionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (tx: Partial<Transaction>) => void;
  initialData?: Transaction | null;
  categories: Category[];
  settings: AppSettings;
}

export const AddTransactionModal: React.FC<AddTransactionModalProps> = ({
  isOpen,
  onClose,
  onSave,
  initialData,
  categories,
  settings
}) => {
  const [date, setDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [value, setValue] = useState<string>('');
  const [type, setType] = useState<TransactionType>('Expense');
  const [category, setCategory] = useState<string>('');
  const [person, setPerson] = useState<string>('');
  const [currency, setCurrency] = useState<string>('');
  const [description, setDescription] = useState<string>('');
  const [isRecurring, setIsRecurring] = useState<boolean>(false);

  useEffect(() => {
    if (initialData) {
      setDate(initialData.date);
      setValue(String(initialData.value));
      setType(initialData.type);
      setCategory(initialData.category);
      setPerson(initialData.person);
      setCurrency(initialData.currency);
      setDescription(initialData.description);
      setIsRecurring(!!initialData.isRecurring);
    } else {
      setDate(new Date().toISOString().slice(0, 10));
      setValue('');
      setType('Expense');
      setPerson(settings.persons[0] || 'Fuad');
      setCurrency(settings.baseCurrency || 'USD');
      setDescription('');
      setIsRecurring(false);
      // Pick default category for Expense
      const firstCat = categories.find(c => c.type === 'Expense');
      if (firstCat) setCategory(firstCat.name);
    }
  }, [initialData, isOpen, categories, settings]);

  useEffect(() => {
    // When type changes, select the first matching category if current category isn't valid for this type
    const validCats = categories.filter(c => c.type === type);
    if (validCats.length > 0 && !validCats.some(c => c.name === category)) {
      setCategory(validCats[0].name);
    }
  }, [type, categories]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const numValue = parseFloat(value);
    if (isNaN(numValue) || numValue <= 0) return;

    onSave({
      id: initialData?.id,
      date,
      value: numValue,
      type,
      category: category || 'Other Expense',
      person: person || settings.persons[0] || 'Me',
      currency: currency || settings.baseCurrency,
      description: description.trim(),
      isRecurring
    });

    onClose();
  };

  const filteredCategories = categories.filter(c => c.type === type);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 className="text-lg font-semibold text-slate-100">
            {initialData ? 'Edit Transaction' : 'Add New Transaction'}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Type Selector */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Transaction Type
            </label>
            <div className="grid grid-cols-3 gap-2">
              {(['Expense', 'Income', 'Savings'] as TransactionType[]).map(t => (
                <button
                  type="button"
                  key={t}
                  onClick={() => setType(t)}
                  className={`py-2 px-3 rounded-lg text-xs font-semibold border transition-all ${
                    type === t
                      ? t === 'Expense'
                        ? 'bg-amber-500/10 border-amber-500/30 text-amber-400'
                        : t === 'Income'
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                        : 'bg-sky-500/10 border-sky-500/30 text-sky-400'
                      : 'bg-slate-800/50 border-slate-700/60 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Amount & Currency */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Amount *
              </label>
              <input
                type="number"
                step="0.01"
                required
                placeholder="0.00"
                value={value}
                onChange={e => setValue(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3.5 py-2 text-slate-100 text-sm focus:outline-hidden focus:border-emerald-500 transition-colors"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Currency
              </label>
              <select
                value={currency}
                onChange={e => setCurrency(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-hidden focus:border-emerald-500 transition-colors"
              >
                {settings.allowedCurrencies.map(c => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Date & Person */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Date *
              </label>
              <input
                type="date"
                required
                value={date}
                onChange={e => setDate(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3.5 py-2 text-slate-100 text-sm focus:outline-hidden focus:border-emerald-500 transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Family Member / Person
              </label>
              <select
                value={person}
                onChange={e => setPerson(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-hidden focus:border-emerald-500 transition-colors"
              >
                {settings.persons.map(p => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Category */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">
              Category *
            </label>
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3.5 py-2 text-slate-100 text-sm focus:outline-hidden focus:border-emerald-500 transition-colors"
            >
              {filteredCategories.map(c => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
              {filteredCategories.length === 0 && (
                <option value="Other">Other</option>
              )}
            </select>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">
              Description / Merchant
            </label>
            <input
              type="text"
              placeholder="e.g. Supermarket grocery shopping"
              value={description}
              onChange={e => setDescription(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3.5 py-2 text-slate-100 text-sm focus:outline-hidden focus:border-emerald-500 transition-colors"
            />
          </div>

          {/* Is Recurring */}
          <div className="flex items-center space-x-2.5 pt-1">
            <input
              type="checkbox"
              id="isRecurring"
              checked={isRecurring}
              onChange={e => setIsRecurring(e.target.checked)}
              className="w-4 h-4 rounded-sm border-slate-700 bg-slate-800 text-emerald-500 focus:ring-emerald-500 focus:ring-offset-slate-900"
            />
            <label htmlFor="isRecurring" className="text-xs text-slate-300">
              Recurring monthly payment
            </label>
          </div>

          {/* Form Footer Actions */}
          <div className="flex items-center justify-end space-x-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center space-x-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-sm transition-all"
            >
              <Check className="w-4 h-4" />
              <span>{initialData ? 'Save Changes' : 'Add Transaction'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
