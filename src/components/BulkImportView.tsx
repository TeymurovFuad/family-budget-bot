import React, { useState } from 'react';
import { Category, AppSettings, DraftTransactionRow } from '../types';
import {
  UploadCloud,
  FileText,
  Image as ImageIcon,
  Sparkles,
  CheckCircle,
  AlertTriangle,
  Trash2,
  Save,
  FileSpreadsheet
} from 'lucide-react';

interface BulkImportViewProps {
  categories: Category[];
  settings: AppSettings;
  onSaveBatch: (rows: DraftTransactionRow[]) => Promise<void>;
}

export const BulkImportView: React.FC<BulkImportViewProps> = ({
  categories,
  settings,
  onSaveBatch
}) => {
  const [importMode, setImportMode] = useState<'text' | 'image'>('text');
  const [textInput, setTextInput] = useState('');
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [draftRows, setDraftRows] = useState<DraftTransactionRow[]>([]);
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set());
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);

  // Handle Image File Selection
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onloadend = () => {
      setSelectedImage(reader.result as string);
    };
    reader.readAsDataURL(file);
  };

  // Run AI Parse via Gemini Backend
  const handleParseAI = async () => {
    if (!textInput.trim() && !selectedImage) return;

    setLoading(true);
    setSaveSuccessMsg(null);

    try {
      const payload: any = {};
      if (importMode === 'image' && selectedImage) {
        payload.imageBase64 = selectedImage;
        payload.mimeType = selectedImage.split(';')[0].replace('data:', '') || 'image/jpeg';
      } else {
        payload.textInput = textInput;
      }

      const res = await fetch('/api/ai/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (res.ok && Array.isArray(data.rows)) {
        setDraftRows(data.rows);
        setSelectedRowIds(new Set(data.rows.map((r: any) => r.id)));
      } else {
        alert('Error parsing data: ' + (data.error || 'Unknown error'));
      }
    } catch (err: any) {
      console.error('Parse error:', err);
      alert('Failed to execute AI parse request.');
    } finally {
      setLoading(false);
    }
  };

  // Row edit handler
  const handleUpdateRow = (id: string, field: keyof DraftTransactionRow, value: any) => {
    setDraftRows(prev =>
      prev.map(r => (r.id === id ? { ...r, [field]: value } : r))
    );
  };

  // Toggle selection
  const toggleSelectRow = (id: string) => {
    const next = new Set(selectedRowIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedRowIds(next);
  };

  // Select/Deselect All
  const toggleSelectAll = () => {
    if (selectedRowIds.size === draftRows.length) {
      setSelectedRowIds(new Set());
    } else {
      setSelectedRowIds(new Set(draftRows.map(r => r.id)));
    }
  };

  // Delete row from draft
  const handleDeleteRow = (id: string) => {
    setDraftRows(prev => prev.filter(r => r.id !== id));
    const next = new Set(selectedRowIds);
    next.delete(id);
    setSelectedRowIds(next);
  };

  // Save selected batch to ledger
  const handleSaveSelected = async () => {
    const toSave = draftRows.filter(r => selectedRowIds.has(r.id));
    if (toSave.length === 0) return;

    await onSaveBatch(toSave);
    setSaveSuccessMsg(`Successfully saved ${toSave.length} transactions to ledger!`);
    setDraftRows([]);
    setSelectedRowIds(new Set());
    setTextInput('');
    setSelectedImage(null);
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
          <UploadCloud className="w-5 h-5 text-emerald-400" />
          Bulk AI Statement & Receipt Import
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Paste bank SMS, raw CSV text, or upload receipt photos. Gemini AI will automatically extract transaction details, categorise items, detect duplicate entries, and let you review before saving to the ledger.
        </p>
      </div>

      {saveSuccessMsg && (
        <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl text-xs font-semibold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          {saveSuccessMsg}
        </div>
      )}

      {/* Input Section */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        {/* Mode Switcher */}
        <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
          <button
            onClick={() => setImportMode('text')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              importMode === 'text'
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Text / CSV Paste</span>
          </button>
          <button
            onClick={() => setImportMode('image')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              importMode === 'image'
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <ImageIcon className="w-4 h-4" />
            <span>Receipt Photo Upload</span>
          </button>
        </div>

        {/* Input Controls */}
        {importMode === 'text' ? (
          <div>
            <textarea
              rows={5}
              placeholder="Paste bank notification SMS messages, statement text, or CSV rows here...
Example:
2026-08-05 Organic Grocery Store -65.20 USD
2026-08-06 Coffee Shop -12.50 USD
2026-08-07 Salary Credit +5200.00 USD"
              value={textInput}
              onChange={e => setTextInput(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700/80 rounded-lg p-3 text-xs text-slate-100 placeholder-slate-500 focus:outline-hidden focus:border-emerald-500 transition-colors font-mono"
            />
          </div>
        ) : (
          <div className="space-y-3">
            <div className="border-2 border-dashed border-slate-700 hover:border-emerald-500/50 rounded-xl p-6 text-center transition-colors">
              <input
                type="file"
                accept="image/*"
                onChange={handleImageUpload}
                className="hidden"
                id="receiptUpload"
              />
              <label htmlFor="receiptUpload" className="cursor-pointer space-y-2 block">
                <ImageIcon className="w-8 h-8 text-slate-500 mx-auto" />
                <p className="text-xs font-medium text-slate-300">
                  Click to choose a receipt photo or drag and drop image file
                </p>
                <p className="text-[11px] text-slate-500">Supports PNG, JPG, WEBP formats</p>
              </label>
            </div>

            {selectedImage && (
              <div className="relative w-40 h-40 rounded-lg overflow-hidden border border-slate-700">
                <img src={selectedImage} alt="Receipt preview" className="w-full h-full object-cover" />
                <button
                  onClick={() => setSelectedImage(null)}
                  className="absolute top-1 right-1 p-1 bg-slate-900/80 text-rose-400 rounded-md hover:bg-slate-900"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-end pt-2">
          <button
            onClick={handleParseAI}
            disabled={loading || (!textInput.trim() && !selectedImage)}
            className="flex items-center space-x-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg shadow-sm transition-all cursor-pointer"
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Parsing with Gemini AI...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                <span>Parse Transactions with Gemini AI</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Editable Draft Preview Section */}
      {draftRows.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden space-y-4 p-5">
          <div className="flex items-center justify-between flex-wrap gap-3 pb-3 border-b border-slate-800">
            <div>
              <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
                Extracted Draft Preview ({draftRows.length} items)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Review and edit fields before committing to your live budget ledger.
              </p>
            </div>

            <div className="flex items-center space-x-3">
              <button
                onClick={toggleSelectAll}
                className="text-xs text-slate-400 hover:text-slate-200 underline"
              >
                {selectedRowIds.size === draftRows.length ? 'Deselect All' : 'Select All'}
              </button>

              <button
                onClick={handleSaveSelected}
                disabled={selectedRowIds.size === 0}
                className="flex items-center space-x-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-bold shadow-xs cursor-pointer"
              >
                <Save className="w-4 h-4" />
                <span>Save {selectedRowIds.size} Selected to Ledger</span>
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-800/80 text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-3 py-2 w-8">
                    <input
                      type="checkbox"
                      checked={selectedRowIds.size === draftRows.length}
                      onChange={toggleSelectAll}
                      className="rounded-xs border-slate-700 bg-slate-800 text-emerald-500"
                    />
                  </th>
                  <th className="px-3 py-2 font-semibold">Date</th>
                  <th className="px-3 py-2 font-semibold">Amount</th>
                  <th className="px-3 py-2 font-semibold">Currency</th>
                  <th className="px-3 py-2 font-semibold">Type</th>
                  <th className="px-3 py-2 font-semibold">Category</th>
                  <th className="px-3 py-2 font-semibold">Member</th>
                  <th className="px-3 py-2 font-semibold">Description</th>
                  <th className="px-3 py-2 font-semibold text-center">Status</th>
                  <th className="px-3 py-2 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {draftRows.map(row => (
                  <tr
                    key={row.id}
                    className={`hover:bg-slate-800/30 transition-colors ${
                      row.isDuplicate ? 'bg-amber-500/5' : ''
                    }`}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selectedRowIds.has(row.id)}
                        onChange={() => toggleSelectRow(row.id)}
                        className="rounded-xs border-slate-700 bg-slate-800 text-emerald-500"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="date"
                        value={row.date}
                        onChange={e => handleUpdateRow(row.id, 'date', e.target.value)}
                        className="bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        step="0.01"
                        value={row.value}
                        onChange={e => handleUpdateRow(row.id, 'value', parseFloat(e.target.value) || 0)}
                        className="w-24 bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs font-bold"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={row.currency}
                        onChange={e => handleUpdateRow(row.id, 'currency', e.target.value)}
                        className="bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs"
                      >
                        {settings.allowedCurrencies.map(c => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={row.type}
                        onChange={e => handleUpdateRow(row.id, 'type', e.target.value as any)}
                        className="bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs"
                      >
                        <option value="Expense">Expense</option>
                        <option value="Income">Income</option>
                        <option value="Savings">Savings</option>
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={row.category}
                        onChange={e => handleUpdateRow(row.id, 'category', e.target.value)}
                        className="bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs"
                      >
                        {categories.map(c => (
                          <option key={c.name} value={c.name}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={row.person}
                        onChange={e => handleUpdateRow(row.id, 'person', e.target.value)}
                        className="bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs"
                      >
                        {settings.persons.map(p => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="text"
                        value={row.description}
                        onChange={e => handleUpdateRow(row.id, 'description', e.target.value)}
                        className="w-full min-w-[140px] bg-slate-800 border border-slate-700/70 rounded-md px-2 py-1 text-slate-200 text-xs"
                      />
                    </td>
                    <td className="px-3 py-2 text-center">
                      {row.isDuplicate ? (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px]">
                          <AlertTriangle className="w-3 h-3 mr-1" /> Duplicate
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                          <CheckCircle className="w-3 h-3 mr-1" /> Ready
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => handleDeleteRow(row.id)}
                        className="p-1 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded-md transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
