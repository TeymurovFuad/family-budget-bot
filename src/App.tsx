import React, { useState, useEffect } from 'react';
import {
  Transaction,
  Category,
  CurrencyRate,
  AppSettings,
  BudgetCycle,
  DraftTransactionRow
} from './types';
import { Navbar } from './components/Navbar';
import { LedgerView } from './components/LedgerView';
import { SummaryView } from './components/SummaryView';
import { CyclesView } from './components/CyclesView';
import { BulkImportView } from './components/BulkImportView';
import { LogsView } from './components/LogsView';
import { SettingsView } from './components/SettingsView';
import { AddTransactionModal } from './components/AddTransactionModal';

export default function App() {
  const [activeTab, setActiveTab] = useState<'ledger' | 'summary' | 'cycles' | 'bulk' | 'logs' | 'settings'>('ledger');
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [currencies, setCurrencies] = useState<CurrencyRate[]>([]);
  const [cycles, setCycles] = useState<BudgetCycle[]>([]);
  const [settings, setSettings] = useState<AppSettings>({
    baseCurrency: 'USD',
    displayCurrency: 'USD',
    budgetCycleEnabled: true,
    persons: ['Fuad', 'Partner', 'Shared'],
    allowedCurrencies: ['USD', 'EUR', 'GBP', 'AZN', 'PLN']
  });

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editingTx, setEditingTx] = useState<Transaction | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAllData();
  }, []);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [setsRes, curRes, catRes, txRes, cycRes] = await Promise.all([
        fetch('/api/settings'),
        fetch('/api/currencies'),
        fetch('/api/categories'),
        fetch('/api/transactions'),
        fetch('/api/cycles')
      ]);

      if (setsRes.ok) setSettings(await setsRes.json());
      if (curRes.ok) setCurrencies(await curRes.json());
      if (catRes.ok) setCategories(await catRes.json());
      if (txRes.ok) setTransactions(await txRes.json());
      if (cycRes.ok) setCycles(await cycRes.json());
    } catch (err) {
      console.error('Error fetching data from server:', err);
    } finally {
      setLoading(false);
    }
  };

  // Transaction CRUD
  const handleSaveTransaction = async (txData: Partial<Transaction>) => {
    try {
      if (txData.id) {
        // PUT edit
        const res = await fetch(`/api/transactions/${txData.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(txData)
        });
        if (res.ok) {
          const updated = await res.json();
          setTransactions(prev => prev.map(t => (t.id === updated.id ? updated : t)));
        }
      } else {
        // POST create
        const res = await fetch('/api/transactions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(txData)
        });
        if (res.ok) {
          const created = await res.json();
          setTransactions(prev => [created, ...prev]);
        }
      }

      // Refresh cycles as cycle totals may update
      const cycRes = await fetch('/api/cycles');
      if (cycRes.ok) setCycles(await cycRes.json());
    } catch (err) {
      console.error('Save transaction error:', err);
    }
  };

  const handleDeleteTransaction = async (id: string) => {
    if (!confirm('Are you sure you want to delete this transaction?')) return;
    try {
      const res = await fetch(`/api/transactions/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setTransactions(prev => prev.filter(t => t.id !== id));
        const cycRes = await fetch('/api/cycles');
        if (cycRes.ok) setCycles(await cycRes.json());
      }
    } catch (err) {
      console.error('Delete transaction error:', err);
    }
  };

  // Bulk Save from AI Parser
  const handleSaveBatch = async (rows: DraftTransactionRow[]) => {
    try {
      const res = await fetch('/api/transactions/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows })
      });
      if (res.ok) {
        await fetchAllData();
      }
    } catch (err) {
      console.error('Bulk save error:', err);
    }
  };

  // Cycles
  const handleStartCycle = async (startDate: string, label: string, salaryAmount: number) => {
    try {
      const res = await fetch('/api/cycles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ startDate, label, salaryAmount })
      });
      if (res.ok) {
        const cycRes = await fetch('/api/cycles');
        if (cycRes.ok) setCycles(await cycRes.json());
      }
    } catch (err) {
      console.error('Start cycle error:', err);
    }
  };

  const handleDetectCycles = async () => {
    try {
      const res = await fetch('/api/cycles/detect', { method: 'POST' });
      if (res.ok) {
        setCycles(await res.json());
      }
    } catch (err) {
      console.error('Detect cycles error:', err);
    }
  };

  // Settings & Reference Lists
  const handleUpdateSettings = async (newSettings: Partial<AppSettings>) => {
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings)
      });
      if (res.ok) {
        setSettings(await res.json());
      }
    } catch (err) {
      console.error('Update settings error:', err);
    }
  };

  const handleUpdateCurrency = async (code: string, rateToBase: number, symbol: string) => {
    try {
      const res = await fetch('/api/currencies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, rateToBase, symbol })
      });
      if (res.ok) {
        setCurrencies(await res.json());
        const txRes = await fetch('/api/transactions');
        if (txRes.ok) setTransactions(await txRes.json());
      }
    } catch (err) {
      console.error('Update currency error:', err);
    }
  };

  const handleSaveCategory = async (cat: Category) => {
    try {
      const res = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cat)
      });
      if (res.ok) {
        setCategories(await res.json());
      }
    } catch (err) {
      console.error('Save category error:', err);
    }
  };

  const handleDeleteCategory = async (name: string) => {
    try {
      const res = await fetch(`/api/categories/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if (res.ok) {
        const data = await res.json();
        if (data.categories) setCategories(data.categories);
      }
    } catch (err) {
      console.error('Delete category error:', err);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-4">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 border-3 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm font-medium text-slate-300">Loading Family Budget Workspace...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-slate-950 text-slate-100 flex flex-col font-sans overflow-x-hidden">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        settings={settings}
        onOpenAddModal={() => {
          setEditingTx(null);
          setIsAddModalOpen(true);
        }}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'ledger' && (
          <LedgerView
            transactions={transactions}
            categories={categories}
            settings={settings}
            onEdit={tx => {
              setEditingTx(tx);
              setIsAddModalOpen(true);
            }}
            onDelete={handleDeleteTransaction}
            onOpenAddModal={() => {
              setEditingTx(null);
              setIsAddModalOpen(true);
            }}
          />
        )}

        {activeTab === 'summary' && <SummaryView cycles={cycles} settings={settings} />}

        {activeTab === 'cycles' && (
          <CyclesView
            cycles={cycles}
            settings={settings}
            onStartCycle={handleStartCycle}
            onDetectCycles={handleDetectCycles}
          />
        )}

        {activeTab === 'bulk' && (
          <BulkImportView
            categories={categories}
            settings={settings}
            onSaveBatch={handleSaveBatch}
          />
        )}

        {activeTab === 'logs' && <LogsView />}

        {activeTab === 'settings' && (
          <SettingsView
            settings={settings}
            currencies={currencies}
            categories={categories}
            onUpdateSettings={handleUpdateSettings}
            onUpdateCurrency={handleUpdateCurrency}
            onSaveCategory={handleSaveCategory}
            onDeleteCategory={handleDeleteCategory}
          />
        )}
      </main>

      {/* Add / Edit Transaction Modal */}
      <AddTransactionModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSave={handleSaveTransaction}
        initialData={editingTx}
        categories={categories}
        settings={settings}
      />
    </div>
  );
}
