import express, { Request, Response } from 'express';
import path from 'path';
import fs from 'fs';
import { createServer as createViteServer } from 'vite';
import { GoogleGenAI } from '@google/genai';
import {
  INITIAL_SETTINGS,
  INITIAL_CURRENCIES,
  INITIAL_CATEGORIES,
  INITIAL_CYCLES,
  INITIAL_TRANSACTIONS
} from './src/data/initialData';
import {
  Transaction,
  Category,
  CurrencyRate,
  AppSettings,
  BudgetCycle,
  BulkImportDraft,
  DraftTransactionRow,
  LogEntry,
  LogLevel
} from './src/types';

const PORT = 3000;
const DB_FILE = path.join(process.cwd(), 'data_store.json');

// Memory Data Store with JSON File Persistence
interface StoreData {
  settings: AppSettings;
  currencies: CurrencyRate[];
  categories: Category[];
  cycles: BudgetCycle[];
  transactions: Transaction[];
  drafts: BulkImportDraft[];
  logs: LogEntry[];
}

function getInitialLogs(): LogEntry[] {
  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10);

  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  const yesterdayStr = yesterday.toISOString().slice(0, 10);

  const past3 = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000);
  const past3Str = past3.toISOString().slice(0, 10);

  return [
    {
      id: 'log-1',
      timestamp: `${todayStr}T11:28:10.000Z`,
      level: 'INFO',
      source: 'System',
      action: 'SYSTEM_START',
      message: 'Workspace family budget service started successfully.',
      details: 'Loaded persistent store with base currency USD.'
    },
    {
      id: 'log-2',
      timestamp: `${todayStr}T11:25:00.000Z`,
      level: 'INFO',
      source: 'Transactions',
      action: 'FETCH_ALL',
      message: 'Retrieved transaction ledger and computed totals.',
      details: 'Processed 15 ledger entries.'
    },
    {
      id: 'log-3',
      timestamp: `${todayStr}T10:14:22.000Z`,
      level: 'INFO',
      source: 'BulkImport',
      action: 'AI_PARSER_READY',
      message: 'Gemini AI receipt & statement parsing engine initialized.',
      details: 'Available model: gemini-2.5-flash.'
    },
    {
      id: 'log-4',
      timestamp: `${todayStr}T09:05:12.000Z`,
      level: 'WARNING',
      source: 'Settings',
      action: 'RATE_STALE',
      message: 'PLN and AZN exchange rates are 24 hours old.',
      details: 'Consider reviewing live currency conversion rates in Settings.'
    },
    {
      id: 'log-5',
      timestamp: `${yesterdayStr}T18:40:00.000Z`,
      level: 'INFO',
      source: 'Transactions',
      action: 'CREATE_TRANSACTION',
      message: 'Added transaction: Grocery Market ($142.80)',
      details: 'Category: Groceries | Person: Fuad'
    },
    {
      id: 'log-6',
      timestamp: `${yesterdayStr}T14:12:05.000Z`,
      level: 'WARNING',
      source: 'Categories',
      action: 'BUDGET_THRESHOLD',
      message: 'Category "Dining Out" reached 88% of budget limit.',
      details: 'Spent: $352 / Budget: $400'
    },
    {
      id: 'log-7',
      timestamp: `${yesterdayStr}T08:30:11.000Z`,
      level: 'ERROR',
      source: 'BulkImport',
      action: 'PARSE_FAILED',
      message: 'Low contrast on uploaded receipt image.',
      details: 'User adjusted lighting and re-uploaded receipt.'
    },
    {
      id: 'log-8',
      timestamp: `${past3Str}T12:00:00.000Z`,
      level: 'INFO',
      source: 'Cycles',
      action: 'CYCLE_DETECT',
      message: 'Auto-detected salary budget cycle starting August 1st.',
      details: 'Salary amount: $5,200.00'
    }
  ];
}

function loadStore(): StoreData {
  try {
    if (fs.existsSync(DB_FILE)) {
      const raw = fs.readFileSync(DB_FILE, 'utf-8');
      const loaded = JSON.parse(raw);
      return {
        settings: loaded.settings || { ...INITIAL_SETTINGS },
        currencies: loaded.currencies || [...INITIAL_CURRENCIES],
        categories: loaded.categories || [...INITIAL_CATEGORIES],
        cycles: loaded.cycles || [...INITIAL_CYCLES],
        transactions: loaded.transactions || [...INITIAL_TRANSACTIONS],
        drafts: loaded.drafts || [],
        logs: Array.isArray(loaded.logs) && loaded.logs.length > 0 ? loaded.logs : getInitialLogs()
      };
    }
  } catch (err) {
    console.error('Error loading DB file, fallback to initial:', err);
  }
  return {
    settings: { ...INITIAL_SETTINGS },
    currencies: [...INITIAL_CURRENCIES],
    categories: [...INITIAL_CATEGORIES],
    cycles: [...INITIAL_CYCLES],
    transactions: [...INITIAL_TRANSACTIONS],
    drafts: [],
    logs: getInitialLogs()
  };
}

let store = loadStore();

function saveStore() {
  try {
    fs.writeFileSync(DB_FILE, JSON.stringify(store, null, 2), 'utf-8');
  } catch (err) {
    console.error('Error saving DB file:', err);
  }
}

function addLog(level: LogLevel, source: string, action: string, message: string, details?: string) {
  const newLog: LogEntry = {
    id: 'log-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
    timestamp: new Date().toISOString(),
    level,
    source,
    action,
    message,
    details: details || ''
  };
  store.logs.unshift(newLog);
  if (store.logs.length > 500) {
    store.logs = store.logs.slice(0, 500);
  }
  saveStore();
}

// Helper: Convert raw currency to base currency
function convertToBase(amount: number, currency: string, currencies: CurrencyRate[], baseCurrency: string): number {
  if (currency === baseCurrency) return amount;
  const curObj = currencies.find(c => c.code.toUpperCase() === currency.toUpperCase());
  const baseObj = currencies.find(c => c.code.toUpperCase() === baseCurrency.toUpperCase());
  const curRate = curObj ? curObj.rateToBase : 1.0;
  const baseRate = baseObj ? baseObj.rateToBase : 1.0;
  if (baseRate === 0) return amount;
  return Number(((amount * curRate) / baseRate).toFixed(2));
}

// Recalculate Budget Cycle Totals
function updateCycleTotals() {
  if (!store.cycles || store.cycles.length === 0) return;

  // Sort cycles by startDate ascending
  const sortedCycles = [...store.cycles].sort((a, b) => a.startDate.localeCompare(b.startDate));

  for (let i = 0; i < sortedCycles.length; i++) {
    const cycle = sortedCycles[i];
    const nextCycle = sortedCycles[i + 1];
    const startDate = cycle.startDate;
    const endDate = nextCycle ? nextCycle.startDate : '9999-12-31';

    // Get transactions within this cycle range [startDate, endDate)
    const cycleTx = store.transactions.filter(
      t => t.date >= startDate && t.date < endDate
    );

    const salaryTx = cycleTx.filter(t => t.type === 'Income' && t.category.toLowerCase().includes('salary'));
    const totalSalary = salaryTx.reduce((sum, t) => sum + t.valueBase, 0) || cycle.salaryAmount || 0;

    const totalExpenses = cycleTx
      .filter(t => t.type === 'Expense')
      .reduce((sum, t) => sum + t.valueBase, 0);

    const totalSavings = cycleTx
      .filter(t => t.type === 'Savings')
      .reduce((sum, t) => sum + t.valueBase, 0);

    cycle.salaryAmount = Number(totalSalary.toFixed(2));
    cycle.totalExpenses = Number(totalExpenses.toFixed(2));
    cycle.totalSavings = Number(totalSavings.toFixed(2));
    cycle.unaccounted = Number((cycle.salaryAmount - cycle.totalExpenses - cycle.totalSavings).toFixed(2));
    if (nextCycle) {
      cycle.endDate = nextCycle.startDate;
    }
  }

  store.cycles = sortedCycles;
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: '10mb' }));

  // --- API ROUTES ---

  app.get('/api/health', (req: Request, res: Response) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  // Settings
  app.get('/api/settings', (req: Request, res: Response) => {
    res.json(store.settings);
  });

  app.post('/api/settings', (req: Request, res: Response) => {
    store.settings = { ...store.settings, ...req.body };
    addLog('INFO', 'Settings', 'UPDATE_SETTINGS', 'Updated application configuration settings.');
    saveStore();
    res.json(store.settings);
  });

  // Currencies
  app.get('/api/currencies', (req: Request, res: Response) => {
    res.json(store.currencies);
  });

  app.post('/api/currencies', (req: Request, res: Response) => {
    const { code, rateToBase, symbol } = req.body;
    if (!code) {
      res.status(400).json({ error: 'Code is required' });
      return;
    }
    const existingIndex = store.currencies.findIndex(c => c.code.toUpperCase() === code.toUpperCase());
    if (existingIndex >= 0) {
      store.currencies[existingIndex] = {
        code: code.toUpperCase(),
        rateToBase: Number(rateToBase) || 1.0,
        symbol: symbol || code
      };
    } else {
      store.currencies.push({
        code: code.toUpperCase(),
        rateToBase: Number(rateToBase) || 1.0,
        symbol: symbol || code
      });
    }

    // Re-calculate all transaction valueBase values if rates updated
    store.transactions.forEach(t => {
      t.valueBase = convertToBase(t.value, t.currency, store.currencies, store.settings.baseCurrency);
    });

    addLog('INFO', 'Currencies', 'UPDATE_CURRENCY', `Updated exchange rate for ${code.toUpperCase()} to ${rateToBase}`);
    saveStore();
    res.json(store.currencies);
  });

  // Categories
  app.get('/api/categories', (req: Request, res: Response) => {
    res.json(store.categories);
  });

  app.post('/api/categories', (req: Request, res: Response) => {
    const { name, type, budgetTargetBase, icon, color } = req.body;
    if (!name || !type) {
      res.status(400).json({ error: 'Name and type are required' });
      return;
    }
    const idx = store.categories.findIndex(c => c.name.toLowerCase() === name.toLowerCase());
    const newCat: Category = {
      name,
      type,
      budgetTargetBase: Number(budgetTargetBase) || 0,
      icon: icon || 'Tag',
      color: color || '#3B82F6'
    };
    if (idx >= 0) {
      store.categories[idx] = newCat;
    } else {
      store.categories.push(newCat);
    }
    addLog('INFO', 'Categories', 'UPDATE_CATEGORY', `Updated category "${name}" (${type}) with target ${budgetTargetBase}`);
    saveStore();
    res.json(store.categories);
  });

  app.delete('/api/categories/:name', (req: Request, res: Response) => {
    const catName = req.params.name;
    store.categories = store.categories.filter(c => c.name.toLowerCase() !== catName.toLowerCase());
    addLog('WARNING', 'Categories', 'DELETE_CATEGORY', `Deleted category "${catName}"`);
    saveStore();
    res.json({ success: true, categories: store.categories });
  });

  // Transactions
  app.get('/api/transactions', (req: Request, res: Response) => {
    let list = [...store.transactions];

    const { search, category, type, person, startDate, endDate, sort, order } = req.query;

    if (search && typeof search === 'string') {
      const q = search.toLowerCase();
      list = list.filter(t =>
        t.description.toLowerCase().includes(q) ||
        t.category.toLowerCase().includes(q) ||
        t.person.toLowerCase().includes(q) ||
        t.currency.toLowerCase().includes(q)
      );
    }

    if (category && typeof category === 'string' && category !== 'all') {
      list = list.filter(t => t.category.toLowerCase() === category.toLowerCase());
    }

    if (type && typeof type === 'string' && type !== 'all') {
      list = list.filter(t => t.type.toLowerCase() === type.toLowerCase());
    }

    if (person && typeof person === 'string' && person !== 'all') {
      list = list.filter(t => t.person.toLowerCase() === person.toLowerCase());
    }

    if (startDate && typeof startDate === 'string' && startDate.trim()) {
      list = list.filter(t => t.date >= startDate.trim());
    }

    if (endDate && typeof endDate === 'string' && endDate.trim()) {
      list = list.filter(t => t.date <= endDate.trim());
    }

    // Sort by date descending by default
    const isAsc = order === 'asc';
    list.sort((a, b) => {
      if (sort === 'value') {
        return isAsc ? a.valueBase - b.valueBase : b.valueBase - a.valueBase;
      }
      return isAsc ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date);
    });

    res.json(list);
  });

  app.post('/api/transactions', (req: Request, res: Response) => {
    const { date, value, type, category, person, description, currency, isRecurring } = req.body;
    if (!date || value === undefined || !type || !category) {
      res.status(400).json({ error: 'Date, value, type, and category are required' });
      return;
    }

    const cur = currency || store.settings.baseCurrency;
    const valBase = convertToBase(Number(value), cur, store.currencies, store.settings.baseCurrency);

    const newTx: Transaction = {
      id: 'tx-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
      date,
      value: Number(value),
      type,
      category,
      person: person || store.settings.persons[0] || 'Me',
      description: description || '',
      currency: cur,
      valueBase: valBase,
      isRecurring: !!isRecurring,
      isDone: true,
      createdAt: new Date().toISOString()
    };

    store.transactions.unshift(newTx);
    updateCycleTotals();
    addLog(
      'INFO',
      'Transactions',
      'CREATE_TRANSACTION',
      `Created ${type}: ${description || category} (${cur} ${value})`,
      `Date: ${date} | Member: ${newTx.person} | Base value: $${valBase.toFixed(2)}`
    );
    saveStore();

    res.json(newTx);
  });

  app.put('/api/transactions/:id', (req: Request, res: Response) => {
    const id = req.params.id;
    const idx = store.transactions.findIndex(t => t.id === id);
    if (idx === -1) {
      res.status(404).json({ error: 'Transaction not found' });
      return;
    }

    const existing = store.transactions[idx];
    const updated = { ...existing, ...req.body };
    updated.valueBase = convertToBase(updated.value, updated.currency, store.currencies, store.settings.baseCurrency);
    updated.updatedAt = new Date().toISOString();

    store.transactions[idx] = updated;
    updateCycleTotals();
    addLog(
      'INFO',
      'Transactions',
      'EDIT_TRANSACTION',
      `Updated transaction: ${updated.description || updated.category}`,
      `ID: ${id} | New value: ${updated.currency} ${updated.value}`
    );
    saveStore();

    res.json(updated);
  });

  app.delete('/api/transactions/:id', (req: Request, res: Response) => {
    const id = req.params.id;
    const existing = store.transactions.find(t => t.id === id);
    store.transactions = store.transactions.filter(t => t.id !== id);
    updateCycleTotals();
    addLog(
      'WARNING',
      'Transactions',
      'DELETE_TRANSACTION',
      `Deleted transaction: ${existing ? existing.description || existing.category : id}`
    );
    saveStore();
    res.json({ success: true, id });
  });

  // Bulk Save Transactions
  app.post('/api/transactions/bulk', (req: Request, res: Response) => {
    const { rows } = req.body;
    if (!Array.isArray(rows) || rows.length === 0) {
      res.status(400).json({ error: 'Rows array is required' });
      return;
    }

    const newTxs: Transaction[] = rows.map((r: DraftTransactionRow) => {
      const cur = r.currency || store.settings.baseCurrency;
      return {
        id: 'tx-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7),
        date: r.date || new Date().toISOString().slice(0, 10),
        value: Number(r.value),
        type: r.type || 'Expense',
        category: r.category || 'Other Expense',
        person: r.person || store.settings.persons[0] || 'Me',
        description: r.description || 'Imported Transaction',
        currency: cur,
        valueBase: convertToBase(Number(r.value), cur, store.currencies, store.settings.baseCurrency),
        isDone: true,
        createdAt: new Date().toISOString()
      };
    });

    store.transactions.unshift(...newTxs);
    updateCycleTotals();
    addLog('INFO', 'BulkImport', 'BULK_SAVE', `Successfully imported ${newTxs.length} transactions via AI parser.`);
    saveStore();

    res.json({ success: true, addedCount: newTxs.length, transactions: newTxs });
  });

  // Cycles
  app.get('/api/cycles', (req: Request, res: Response) => {
    updateCycleTotals();
    res.json(store.cycles);
  });

  app.post('/api/cycles', (req: Request, res: Response) => {
    const { startDate, label, salaryAmount } = req.body;
    if (!startDate) {
      res.status(400).json({ error: 'startDate is required' });
      return;
    }

    const newCycle: BudgetCycle = {
      id: 'cycle-' + startDate,
      startDate,
      label: label || `Cycle starting ${startDate}`,
      salaryAmount: Number(salaryAmount) || 0,
      totalExpenses: 0,
      totalSavings: 0,
      unaccounted: Number(salaryAmount) || 0
    };

    store.cycles.push(newCycle);
    updateCycleTotals();
    addLog('INFO', 'Cycles', 'CREATE_CYCLE', `Created budget cycle: ${newCycle.label}`, `Start date: ${startDate}`);
    saveStore();

    res.json(newCycle);
  });

  // Auto-detect cycles from Salary transactions
  app.post('/api/cycles/detect', (req: Request, res: Response) => {
    const salaryTxs = store.transactions
      .filter(t => t.type === 'Income' && t.category.toLowerCase().includes('salary'))
      .sort((a, b) => a.date.localeCompare(b.date));

    const detectedCycles: BudgetCycle[] = [];
    salaryTxs.forEach(st => {
      if (!detectedCycles.some(c => c.startDate === st.date)) {
        detectedCycles.push({
          id: 'cycle-' + st.date,
          startDate: st.date,
          label: `${st.date.slice(0, 7)} Salary Cycle`,
          salaryAmount: st.valueBase,
          totalExpenses: 0,
          totalSavings: 0,
          unaccounted: st.valueBase
        });
      }
    });

    if (detectedCycles.length > 0) {
      store.cycles = detectedCycles;
      updateCycleTotals();
      addLog('INFO', 'Cycles', 'DETECT_CYCLES', `Auto-detected ${detectedCycles.length} cycles from salary entries.`);
      saveStore();
    }

    res.json(store.cycles);
  });

  // Logs Endpoint
  app.get('/api/logs', (req: Request, res: Response) => {
    let list = [...store.logs];

    const { level, source, datePreset, startDate, endDate, search, sort } = req.query;

    // Filter by Log Level
    if (level && typeof level === 'string' && level !== 'ALL') {
      list = list.filter(l => l.level.toUpperCase() === level.toUpperCase());
    }

    // Filter by Source
    if (source && typeof source === 'string' && source !== 'ALL') {
      list = list.filter(l => l.source.toLowerCase() === source.toLowerCase());
    }

    // Filter by Search Query
    if (search && typeof search === 'string' && search.trim()) {
      const q = search.toLowerCase().trim();
      list = list.filter(
        l =>
          l.message.toLowerCase().includes(q) ||
          l.source.toLowerCase().includes(q) ||
          l.action.toLowerCase().includes(q) ||
          (l.details && l.details.toLowerCase().includes(q))
      );
    }

    // Date Filtering based on local YYYY-MM-DD
    const now = new Date();
    const todayStr = now.toISOString().slice(0, 10);

    let filterStart = '2000-01-01';
    let filterEnd = '2099-12-31';

    if (datePreset === 'today') {
      filterStart = todayStr;
      filterEnd = todayStr;
    } else if (datePreset === 'yesterday') {
      const yest = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      const yestStr = yest.toISOString().slice(0, 10);
      filterStart = yestStr;
      filterEnd = yestStr;
    } else if (datePreset === 'last7') {
      const p7 = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      filterStart = p7.toISOString().slice(0, 10);
      filterEnd = todayStr;
    } else if (datePreset === 'month') {
      const y = now.getFullYear();
      const m = String(now.getMonth() + 1).padStart(2, '0');
      filterStart = `${y}-${m}-01`;
      filterEnd = `${y}-${m}-31`;
    } else if (datePreset === 'year') {
      const y = now.getFullYear();
      filterStart = `${y}-01-01`;
      filterEnd = `${y}-12-31`;
    } else if (startDate || endDate) {
      if (startDate && typeof startDate === 'string' && startDate.trim()) {
        filterStart = startDate.trim();
      }
      if (endDate && typeof endDate === 'string' && endDate.trim()) {
        filterEnd = endDate.trim();
      }
    }

    // Compare local YYYY-MM-DD string slice of log ISO timestamp
    list = list.filter(l => {
      const logDate = l.timestamp.slice(0, 10);
      return logDate >= filterStart && logDate <= filterEnd;
    });

    // Sorting
    const isAsc = sort === 'asc';
    list.sort((a, b) => (isAsc ? a.timestamp.localeCompare(b.timestamp) : b.timestamp.localeCompare(a.timestamp)));

    res.json({
      logs: list,
      totalCount: list.length,
      countsByLevel: {
        INFO: store.logs.filter(l => l.level === 'INFO').length,
        WARNING: store.logs.filter(l => l.level === 'WARNING').length,
        ERROR: store.logs.filter(l => l.level === 'ERROR').length
      }
    });
  });

  app.delete('/api/logs/clear', (req: Request, res: Response) => {
    store.logs = [];
    addLog('INFO', 'System', 'CLEAR_LOGS', 'System activity logs cleared by user.');
    saveStore();
    res.json({ success: true, message: 'Logs cleared.' });
  });

  // Summary Report
  app.get('/api/summary', (req: Request, res: Response) => {
    const { cycleId, period, startDate: reqStart, endDate: reqEnd, person, category, type, search } = req.query;

    const now = new Date();
    const todayStr = now.toISOString().slice(0, 10);

    let startDate = '2000-01-01';
    let endDate = '2099-12-31';
    let label = 'All Time';

    updateCycleTotals();

    if (cycleId && typeof cycleId === 'string' && cycleId !== 'all') {
      const cyc = store.cycles.find(c => c.id === cycleId);
      if (cyc) {
        startDate = cyc.startDate;
        endDate = cyc.endDate ? cyc.endDate : '2099-12-31';
        label = cyc.label;
      }
    } else if (reqStart && reqEnd && String(reqStart).trim() && String(reqEnd).trim()) {
      startDate = String(reqStart).trim();
      endDate = String(reqEnd).trim();
      label = `${startDate} to ${endDate}`;
    } else if (period === 'today') {
      startDate = todayStr;
      endDate = todayStr;
      label = `Today (${todayStr})`;
    } else if (period === 'yesterday') {
      const yest = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      const yestStr = yest.toISOString().slice(0, 10);
      startDate = yestStr;
      endDate = yestStr;
      label = `Yesterday (${yestStr})`;
    } else if (period === 'last-7') {
      const p7 = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      startDate = p7.toISOString().slice(0, 10);
      endDate = todayStr;
      label = 'Last 7 Days';
    } else if (period === 'this-month') {
      const y = now.getFullYear();
      const m = String(now.getMonth() + 1).padStart(2, '0');
      startDate = `${y}-${m}-01`;
      endDate = `${y}-${m}-31`;
      label = `This Month (${y}-${m})`;
    } else if (period === 'last-30') {
      const p30 = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      startDate = p30.toISOString().slice(0, 10);
      endDate = todayStr;
      label = 'Last 30 Days';
    } else if (period === 'this-year') {
      const y = now.getFullYear();
      startDate = `${y}-01-01`;
      endDate = `${y}-12-31`;
      label = `This Year (${y})`;
    }

    let filtered = store.transactions.filter(t => t.date >= startDate && t.date <= endDate);

    // Filter by Person
    if (person && typeof person === 'string' && person !== 'all') {
      filtered = filtered.filter(t => t.person.toLowerCase() === person.toLowerCase());
    }

    // Filter by Category
    if (category && typeof category === 'string' && category !== 'all') {
      filtered = filtered.filter(t => t.category.toLowerCase() === category.toLowerCase());
    }

    // Filter by Type
    if (type && typeof type === 'string' && type !== 'all') {
      filtered = filtered.filter(t => t.type.toLowerCase() === type.toLowerCase());
    }

    // Search filter
    if (search && typeof search === 'string' && search.trim()) {
      const q = search.toLowerCase().trim();
      filtered = filtered.filter(
        t =>
          t.description.toLowerCase().includes(q) ||
          t.category.toLowerCase().includes(q) ||
          t.person.toLowerCase().includes(q)
      );
    }

    const totalIncome = filtered
      .filter(t => t.type === 'Income')
      .reduce((sum, t) => sum + t.valueBase, 0);

    const totalExpenses = filtered
      .filter(t => t.type === 'Expense')
      .reduce((sum, t) => sum + t.valueBase, 0);

    const totalSavings = filtered
      .filter(t => t.type === 'Savings')
      .reduce((sum, t) => sum + t.valueBase, 0);

    const net = totalIncome - totalExpenses - totalSavings;
    const unaccounted = totalIncome - totalExpenses - totalSavings;

    // Category Breakdown
    const catMap = new Map<string, { actual: number; type: 'Expense' | 'Income' | 'Savings' }>();
    filtered.forEach(t => {
      const key = t.category;
      const cur = catMap.get(key) || { actual: 0, type: t.type };
      cur.actual += t.valueBase;
      catMap.set(key, cur);
    });

    const categoryBreakdown = Array.from(catMap.entries()).map(([catName, data]) => {
      const catDef = store.categories.find(c => c.name.toLowerCase() === catName.toLowerCase());
      const budget = catDef ? catDef.budgetTargetBase : 0;
      const pct = budget > 0 ? (data.actual / budget) * 100 : 0;
      return {
        category: catName,
        type: data.type,
        actual: Number(data.actual.toFixed(2)),
        budget: Number(budget.toFixed(2)),
        percentage: Number(pct.toFixed(1))
      };
    });

    // Person Breakdown
    const personMap = new Map<string, number>();
    filtered.filter(t => t.type === 'Expense').forEach(t => {
      const p = t.person || 'Unassigned';
      personMap.set(p, (personMap.get(p) || 0) + t.valueBase);
    });

    const personBreakdown = Array.from(personMap.entries()).map(([person, amount]) => ({
      person,
      amount: Number(amount.toFixed(2)),
      percentage: totalExpenses > 0 ? Number(((amount / totalExpenses) * 100).toFixed(1)) : 0
    }));

    // Daily trends
    const dateMap = new Map<string, { income: number; expenses: number; savings: number }>();
    filtered.forEach(t => {
      const cur = dateMap.get(t.date) || { income: 0, expenses: 0, savings: 0 };
      if (t.type === 'Income') cur.income += t.valueBase;
      if (t.type === 'Expense') cur.expenses += t.valueBase;
      if (t.type === 'Savings') cur.savings += t.valueBase;
      dateMap.set(t.date, cur);
    });

    const dailyTrends = Array.from(dateMap.entries())
      .map(([date, vals]) => ({
        date,
        income: Number(vals.income.toFixed(2)),
        expenses: Number(vals.expenses.toFixed(2)),
        savings: Number(vals.savings.toFixed(2))
      }))
      .sort((a, b) => a.date.localeCompare(b.date));

    res.json({
      periodType: cycleId ? 'cycle' : 'custom',
      periodLabel: label,
      startDate,
      endDate,
      activeFilters: {
        person: person ? String(person) : 'all',
        category: category ? String(category) : 'all',
        type: type ? String(type) : 'all',
        search: search ? String(search) : ''
      },
      totalIncome: Number(totalIncome.toFixed(2)),
      totalExpenses: Number(totalExpenses.toFixed(2)),
      totalSavings: Number(totalSavings.toFixed(2)),
      net: Number(net.toFixed(2)),
      unaccounted: Number(unaccounted.toFixed(2)),
      categoryBreakdown,
      personBreakdown,
      dailyTrends
    });
  });

  // Drafts
  app.get('/api/drafts', (req: Request, res: Response) => {
    res.json(store.drafts);
  });

  app.post('/api/drafts', (req: Request, res: Response) => {
    const { sourceName, sourceType, rows } = req.body;
    const newDraft: BulkImportDraft = {
      id: 'draft-' + Date.now(),
      createdAt: new Date().toISOString(),
      sourceName: sourceName || 'Imported Draft',
      sourceType: sourceType || 'text',
      rows: Array.isArray(rows) ? rows : []
    };
    store.drafts.unshift(newDraft);
    saveStore();
    res.json(newDraft);
  });

  app.delete('/api/drafts/:id', (req: Request, res: Response) => {
    const id = req.params.id;
    store.drafts = store.drafts.filter(d => d.id !== id);
    saveStore();
    res.json({ success: true, id });
  });

  // Gemini AI parsing endpoint
  app.post('/api/ai/parse', async (req: Request, res: Response) => {
    try {
      const apiKey = process.env.GEMINI_API_KEY;
      if (!apiKey) {
        res.status(400).json({ error: 'GEMINI_API_KEY is not configured in server environment' });
        return;
      }

      const ai = new GoogleGenAI({ apiKey });
      const { textInput, imageBase64, mimeType } = req.body;

      const categoriesList = store.categories.map(c => `${c.name} (${c.type})`).join(', ');
      const currenciesList = store.currencies.map(c => c.code).join(', ');
      const personsList = store.settings.persons.join(', ');

      const prompt = `You are an expert financial receipt and bank statement parser for a family budget app.
Extract all transaction items from the provided text or image.

Available Categories: [${categoriesList}]
Available Currencies: [${currenciesList}] (Default: ${store.settings.baseCurrency})
Available Family Members / Persons: [${personsList}] (Default: ${store.settings.persons[0] || 'Fuad'})

For EACH extracted transaction, output a valid JSON object matching this schema:
{
  "date": "YYYY-MM-DD",
  "value": number (positive float),
  "type": "Expense" | "Income" | "Savings",
  "category": "one of the available categories or best fit",
  "person": "one of the available persons",
  "description": "merchant or short description",
  "currency": "3-letter currency code e.g. USD, EUR, AZN, PLN"
}

Return ONLY a JSON array of transaction objects. No markdown backticks, no markdown formatting.`;

      let contents: any[] = [prompt];

      if (imageBase64) {
        const cleanBase64 = imageBase64.replace(/^data:image\/\w+;base64,/, '');
        contents.push({
          inlineData: {
            mimeType: mimeType || 'image/jpeg',
            data: cleanBase64
          }
        });
      } else if (textInput) {
        contents.push(`\n\nInput Data to parse:\n${textInput}`);
      } else {
        res.status(400).json({ error: 'Either textInput or imageBase64 is required' });
        return;
      }

      const response = await ai.models.generateContent({
        model: 'gemini-2.5-flash',
        contents
      });

      const responseText = response.text || '[]';
      // Clean JSON formatting
      const jsonClean = responseText
        .replace(/```json/gi, '')
        .replace(/```/g, '')
        .trim();

      let parsedRows = [];
      try {
        parsedRows = JSON.parse(jsonClean);
      } catch (pErr) {
        console.error('Failed to parse Gemini output as JSON:', responseText);
        parsedRows = [];
      }

      // Check duplicates against existing store
      const rowsWithDupCheck = parsedRows.map((r: any, idx: number) => {
        const date = r.date || new Date().toISOString().slice(0, 10);
        const val = Number(r.value) || 0;
        const desc = r.description || 'Imported item';
        const cur = r.currency || store.settings.baseCurrency;

        const isDup = store.transactions.some(
          t => t.date === date && Math.abs(t.value - val) < 0.01 && t.description.toLowerCase() === desc.toLowerCase()
        );

        return {
          id: 'draft-row-' + Date.now() + '-' + idx,
          date,
          value: val,
          type: r.type || 'Expense',
          category: r.category || 'Other Expense',
          person: r.person || store.settings.persons[0] || 'Fuad',
          description: desc,
          currency: cur,
          valueBase: convertToBase(val, cur, store.currencies, store.settings.baseCurrency),
          isDuplicate: isDup
        };
      });

      res.json({ rows: rowsWithDupCheck, count: rowsWithDupCheck.length });
    } catch (err: any) {
      console.error('AI Parse Error:', err);
      res.status(500).json({ error: err.message || 'Error processing request with Gemini AI' });
    }
  });

  // Export
  app.get('/api/export', (req: Request, res: Response) => {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Content-Disposition', 'attachment; filename="family_budget_export.json"');
    res.json(store);
  });

  // --- VITE / STATIC SERVING ---
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa'
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req: Request, res: Response) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Family Budget App running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
