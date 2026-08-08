import { Transaction, Category, CurrencyRate, AppSettings, BudgetCycle } from '../types';

export const INITIAL_SETTINGS: AppSettings = {
  baseCurrency: 'USD',
  displayCurrency: 'USD',
  budgetCycleEnabled: true,
  persons: ['Fuad', 'Partner', 'Shared'],
  allowedCurrencies: ['USD', 'EUR', 'GBP', 'AZN', 'PLN']
};

export const INITIAL_CURRENCIES: CurrencyRate[] = [
  { code: 'USD', rateToBase: 1.0, symbol: '$' },
  { code: 'EUR', rateToBase: 1.08, symbol: '€' },
  { code: 'GBP', rateToBase: 1.28, symbol: '£' },
  { code: 'AZN', rateToBase: 0.59, symbol: '₼' },
  { code: 'PLN', rateToBase: 0.25, symbol: 'zł' }
];

export const INITIAL_CATEGORIES: Category[] = [
  // Income
  { name: 'Salary', type: 'Income', budgetTargetBase: 0, icon: 'Briefcase', color: '#10B981' },
  { name: 'Bonus & Side Jobs', type: 'Income', budgetTargetBase: 0, icon: 'TrendingUp', color: '#059669' },
  { name: 'Investment Income', type: 'Income', budgetTargetBase: 0, icon: 'DollarSign', color: '#34D399' },
  { name: 'Other Income', type: 'Income', budgetTargetBase: 0, icon: 'PlusCircle', color: '#6EE7B7' },

  // Expenses
  { name: 'Groceries & Market', type: 'Expense', budgetTargetBase: 800, icon: 'ShoppingCart', color: '#F59E0B' },
  { name: 'Housing & Rent', type: 'Expense', budgetTargetBase: 1500, icon: 'Home', color: '#EF4444' },
  { name: 'Utilities & Internet', type: 'Expense', budgetTargetBase: 250, icon: 'Zap', color: '#3B82F6' },
  { name: 'Dining & Cafes', type: 'Expense', budgetTargetBase: 350, icon: 'Coffee', color: '#EC4899' },
  { name: 'Transportation & Fuel', type: 'Expense', budgetTargetBase: 300, icon: 'Car', color: '#8B5CF6' },
  { name: 'Shopping & Apparel', type: 'Expense', budgetTargetBase: 400, icon: 'ShoppingBag', color: '#6366F1' },
  { name: 'Healthcare & Pharma', type: 'Expense', budgetTargetBase: 200, icon: 'Activity', color: '#14B8A6' },
  { name: 'Entertainment & Hobbies', type: 'Expense', budgetTargetBase: 200, icon: 'Film', color: '#D97706' },
  { name: 'Subscriptions & Services', type: 'Expense', budgetTargetBase: 100, icon: 'Repeat', color: '#64748B' },
  { name: 'Other Expense', type: 'Expense', budgetTargetBase: 150, icon: 'MoreHorizontal', color: '#94A3B8' },

  // Savings
  { name: 'Emergency Fund', type: 'Savings', budgetTargetBase: 500, icon: 'ShieldCheck', color: '#0EA5E9' },
  { name: 'Investment Account', type: 'Savings', budgetTargetBase: 600, icon: 'PiggyBank', color: '#0284C7' },
  { name: 'Vacation Fund', type: 'Savings', budgetTargetBase: 300, icon: 'Compass', color: '#38BDF8' }
];

export const INITIAL_CYCLES: BudgetCycle[] = [
  {
    id: 'cycle-2026-08',
    startDate: '2026-08-01',
    endDate: null,
    label: 'Aug 2026 Salary Cycle',
    salaryAmount: 5200,
    totalExpenses: 2850,
    totalSavings: 1100,
    unaccounted: 1250
  },
  {
    id: 'cycle-2026-07',
    startDate: '2026-07-01',
    endDate: '2026-07-31',
    label: 'Jul 2026 Salary Cycle',
    salaryAmount: 5200,
    totalExpenses: 3120,
    totalSavings: 1200,
    unaccounted: 880
  }
];

export const INITIAL_TRANSACTIONS: Transaction[] = [
  {
    id: 'tx-101',
    date: '2026-08-01',
    value: 5200,
    type: 'Income',
    category: 'Salary',
    person: 'Fuad',
    description: 'Monthly Salary Credit',
    currency: 'USD',
    valueBase: 5200,
    isDone: true
  },
  {
    id: 'tx-102',
    date: '2026-08-01',
    value: 1500,
    type: 'Expense',
    category: 'Housing & Rent',
    person: 'Shared',
    description: 'Apartment Monthly Rent',
    currency: 'USD',
    valueBase: 1500,
    isDone: true
  },
  {
    id: 'tx-103',
    date: '2026-08-02',
    value: 600,
    type: 'Savings',
    category: 'Investment Account',
    person: 'Fuad',
    description: 'Monthly S&P Index Transfer',
    currency: 'USD',
    valueBase: 600,
    isDone: true
  },
  {
    id: 'tx-104',
    date: '2026-08-02',
    value: 500,
    type: 'Savings',
    category: 'Emergency Fund',
    person: 'Fuad',
    description: 'High Yield Savings Deposit',
    currency: 'USD',
    valueBase: 500,
    isDone: true
  },
  {
    id: 'tx-105',
    date: '2026-08-03',
    value: 185.50,
    type: 'Expense',
    category: 'Groceries & Market',
    person: 'Partner',
    description: 'Weekly Organic Grocery Supermarket',
    currency: 'USD',
    valueBase: 185.50,
    isDone: true
  },
  {
    id: 'tx-106',
    date: '2026-08-04',
    value: 120.00,
    type: 'Expense',
    category: 'Utilities & Internet',
    person: 'Shared',
    description: 'Fiber Internet & Power Bill',
    currency: 'USD',
    valueBase: 120.00,
    isDone: true
  },
  {
    id: 'tx-107',
    date: '2026-08-05',
    value: 65.20,
    type: 'Expense',
    category: 'Dining & Cafes',
    person: 'Fuad',
    description: 'Family Weekend Lunch',
    currency: 'USD',
    valueBase: 65.20,
    isDone: true
  },
  {
    id: 'tx-108',
    date: '2026-08-06',
    value: 75.00,
    type: 'Expense',
    category: 'Transportation & Fuel',
    person: 'Fuad',
    description: 'Car Gas Refill',
    currency: 'USD',
    valueBase: 75.00,
    isDone: true
  },
  {
    id: 'tx-109',
    date: '2026-08-07',
    value: 140.00,
    type: 'Expense',
    category: 'Shopping & Apparel',
    person: 'Partner',
    description: 'Summer Wardrobe Items',
    currency: 'USD',
    valueBase: 140.00,
    isDone: true
  },
  {
    id: 'tx-110',
    date: '2026-08-08',
    value: 45.00,
    type: 'Expense',
    category: 'Subscriptions & Services',
    person: 'Fuad',
    description: 'Cloud & AI Subscriptions',
    currency: 'USD',
    valueBase: 45.00,
    isDone: true
  }
];
