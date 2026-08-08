export type TransactionType = 'Expense' | 'Income' | 'Savings';

export interface Transaction {
  id: string;
  date: string; // YYYY-MM-DD
  value: number;
  type: TransactionType;
  category: string;
  person: string;
  description: string;
  currency: string;
  valueBase: number;
  isRecurring?: boolean;
  isDone?: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface BudgetCycle {
  id: string;
  startDate: string; // YYYY-MM-DD
  endDate?: string | null; // YYYY-MM-DD
  label: string;
  salaryAmount: number;
  totalExpenses: number;
  totalSavings: number;
  unaccounted: number;
}

export interface Category {
  name: string;
  type: TransactionType;
  budgetTargetBase: number;
  icon?: string;
  color?: string;
}

export interface CurrencyRate {
  code: string;
  rateToBase: number; // multiplier to get value in base currency (or valueBase = value * rateToBase)
  symbol: string;
}

export interface AppSettings {
  baseCurrency: string;
  displayCurrency: string;
  budgetCycleEnabled: boolean;
  persons: string[];
  allowedCurrencies: string[];
}

export interface StatementProfile {
  id: string;
  name: string;
  bankName: string;
  dateCol: string;
  descCol: string;
  amountCol: string;
  decimalSeparator: '.' | ',';
  dateFormat: string;
}

export interface DraftTransactionRow {
  id: string;
  date: string;
  value: number;
  type: TransactionType;
  category: string;
  person: string;
  description: string;
  currency: string;
  valueBase: number;
  isDuplicate?: boolean;
  validationError?: string;
}

export type LogLevel = 'INFO' | 'WARNING' | 'ERROR';

export interface LogEntry {
  id: string;
  timestamp: string; // ISO string e.g. 2026-08-08T11:28:11-07:00
  level: LogLevel;
  source: string; // e.g. 'Transactions', 'Cycles', 'BulkImport', 'Settings', 'System'
  action: string;
  message: string;
  details?: string;
}

export interface BulkImportDraft {
  id: string;
  createdAt: string;
  sourceName: string;
  sourceType: 'text' | 'csv' | 'statement' | 'image';
  rows: DraftTransactionRow[];
}

export interface SummaryReport {
  periodType: 'cycle' | 'month' | 'year' | 'custom' | 'all';
  periodLabel: string;
  startDate: string;
  endDate: string;
  activeFilters?: {
    person?: string;
    category?: string;
    type?: string;
    search?: string;
  };
  totalIncome: number;
  totalExpenses: number;
  totalSavings: number;
  net: number;
  unaccounted?: number;
  categoryBreakdown: {
    category: string;
    type: TransactionType;
    actual: number;
    budget: number;
    percentage: number;
  }[];
  personBreakdown: {
    person: string;
    amount: number;
    percentage: number;
  }[];
  dailyTrends: {
    date: string;
    income: number;
    expenses: number;
    savings: number;
  }[];
}
