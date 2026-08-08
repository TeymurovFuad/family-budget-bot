import React from 'react';
import { AppSettings } from '../types';
import {
  ListFilter,
  BarChart3,
  Repeat,
  UploadCloud,
  Settings as SettingsIcon,
  Plus,
  Wallet,
  FileText
} from 'lucide-react';

interface NavbarProps {
  activeTab: 'ledger' | 'summary' | 'cycles' | 'bulk' | 'logs' | 'settings';
  setActiveTab: (tab: 'ledger' | 'summary' | 'cycles' | 'bulk' | 'logs' | 'settings') => void;
  settings: AppSettings;
  onOpenAddModal: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  settings,
  onOpenAddModal
}) => {
  const tabs = [
    { id: 'ledger', label: 'Transactions', icon: ListFilter },
    { id: 'summary', label: 'Reports', icon: BarChart3 },
    { id: 'cycles', label: 'Budget Cycles', icon: Repeat },
    { id: 'bulk', label: 'AI Import', icon: UploadCloud },
    { id: 'logs', label: 'System Logs', icon: FileText },
    { id: 'settings', label: 'Settings', icon: SettingsIcon }
  ] as const;

  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-30 shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand */}
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shadow-sm">
              <Wallet className="w-5 h-5" />
            </div>
            <div>
              <span className="text-lg font-bold text-slate-100 tracking-tight">
                Family Budget
              </span>
              <span className="hidden sm:inline-block ml-2 text-xs font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                {settings.baseCurrency} Base
              </span>
            </div>
          </div>

          {/* Desktop Navigation */}
          <nav className="hidden md:flex items-center space-x-1">
            {tabs.map(tab => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                    isActive
                      ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Action Button */}
          <div className="flex items-center space-x-3">
            <button
              onClick={onOpenAddModal}
              className="flex items-center space-x-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium shadow-sm transition-all active:scale-95 cursor-pointer"
            >
              <Plus className="w-4 h-4 stroke-[2.5]" />
              <span className="hidden sm:inline">Add Transaction</span>
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Tab Bar */}
      <div className="md:hidden flex items-center justify-around border-t border-slate-800 bg-slate-900/95 backdrop-blur-md px-1 py-1.5">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex flex-col items-center py-1 px-2.5 rounded-md text-xs font-medium transition-all ${
                isActive ? 'text-emerald-400 bg-slate-800/80' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Icon className="w-4 h-4 mb-0.5" />
              <span>{tab.label.split(' ')[0]}</span>
            </button>
          );
        })}
      </div>
    </header>
  );
};
