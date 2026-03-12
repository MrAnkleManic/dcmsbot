import { useState, useEffect } from 'react';
import { AlertTriangle, CheckCircle, AlertCircle, Info, X, RefreshCw, ExternalLink } from 'lucide-react';

const API_BASE = '/api';

const severityConfig = {
  high:   { icon: AlertTriangle, color: 'text-red-400',    bg: 'bg-red-900/20',    label: 'High' },
  medium: { icon: AlertCircle,   color: 'text-amber-400',  bg: 'bg-amber-900/20',  label: 'Medium' },
  low:    { icon: Info,          color: 'text-blue-400',   bg: 'bg-blue-900/20',   label: 'Low' },
  clean:  { icon: CheckCircle,   color: 'text-emerald-400', bg: 'bg-emerald-900/20', label: 'Clean' },
};

function SeverityBadge({ severity }) {
  const cfg = severityConfig[severity] || severityConfig.clean;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.bg} ${cfg.color}`}>
      <Icon size={12} />
      {cfg.label}
    </span>
  );
}

function SummaryCard({ label, value, sublabel, color }) {
  return (
    <div className="rounded-lg p-3 dark:bg-dark-700 light:bg-white border dark:border-dark-500 light:border-warm-300">
      <div className={`text-2xl font-bold ${color || 'dark:text-warm-100 light:text-dark-800'}`}>
        {value}
      </div>
      <div className="text-xs dark:text-dark-300 light:text-warm-400 mt-0.5">{label}</div>
      {sublabel && (
        <div className="text-xs dark:text-dark-400 light:text-warm-500 mt-0.5">{sublabel}</div>
      )}
    </div>
  );
}

export default function KbHealthPanel({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all'); // all | high | medium | low | clean
  const [sortBy, setSortBy] = useState('score'); // score | title | chunks

  useEffect(() => {
    fetchHealth();
  }, []);

  const fetchHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/kb-health`);
      if (!res.ok) throw new Error(`Failed to fetch KB health (${res.status})`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 dark:bg-dark-800 light:bg-warm-50 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-6 py-8">
          <div className="animate-pulse space-y-4">
            <div className="h-8 w-48 dark:bg-dark-600 light:bg-warm-200 rounded" />
            <div className="h-4 w-96 dark:bg-dark-600 light:bg-warm-200 rounded" />
            <div className="grid grid-cols-4 gap-4 mt-8">
              {[1,2,3,4].map(i => (
                <div key={i} className="h-20 dark:bg-dark-600 light:bg-warm-200 rounded-lg" />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fixed inset-0 z-50 dark:bg-dark-800 light:bg-warm-50 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="mx-auto text-red-400 mb-2" size={32} />
          <p className="dark:text-warm-200 light:text-dark-700">{error}</p>
          <button onClick={fetchHealth} className="mt-4 px-4 py-2 rounded bg-accent text-white text-sm">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const { total_docs, total_chunks, severity_counts, format_counts, url_coverage, documents } = data;

  // Filter & sort documents
  let filtered = documents;
  if (filter !== 'all') {
    filtered = documents.filter(d => d.severity === filter);
  }

  filtered = [...filtered].sort((a, b) => {
    if (sortBy === 'score') return (b.artifact_score || 0) - (a.artifact_score || 0);
    if (sortBy === 'title') return (a.title || '').localeCompare(b.title || '');
    if (sortBy === 'chunks') return b.total_chunks - a.total_chunks;
    return 0;
  });

  return (
    <div className="fixed inset-0 z-50 dark:bg-dark-800 light:bg-warm-50 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold dark:text-warm-100 light:text-dark-800">
              KB Health Dashboard
            </h1>
            <p className="text-sm dark:text-dark-300 light:text-warm-400 mt-1">
              Document quality metrics and extraction diagnostics
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchHealth}
              className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600
                light:text-warm-400 light:hover:text-warm-600 light:hover:bg-warm-100 transition-colors"
              title="Refresh"
            >
              <RefreshCw size={18} />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600
                light:text-warm-400 light:hover:text-warm-600 light:hover:bg-warm-100 transition-colors"
              title="Close"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <SummaryCard label="Total Documents" value={total_docs} />
          <SummaryCard label="Total Chunks" value={total_chunks.toLocaleString()} />
          <SummaryCard
            label="Need Attention"
            value={(severity_counts.high || 0) + (severity_counts.medium || 0)}
            color="text-amber-400"
            sublabel={`${severity_counts.high || 0} high, ${severity_counts.medium || 0} medium`}
          />
          <SummaryCard
            label="URL Coverage"
            value={`${Math.round(url_coverage / total_docs * 100)}%`}
            sublabel={`${url_coverage} of ${total_docs} docs`}
          />
        </div>

        {/* Format breakdown */}
        <div className="flex flex-wrap gap-2 mb-6">
          {Object.entries(format_counts).map(([fmt, count]) => (
            <span key={fmt} className="text-xs px-2 py-1 rounded
              dark:bg-dark-700 dark:text-dark-300 dark:border dark:border-dark-500
              light:bg-warm-100 light:text-warm-500 light:border light:border-warm-300">
              {fmt}: {count}
            </span>
          ))}
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <span className="text-xs dark:text-dark-400 light:text-warm-400 mr-1">Filter:</span>
          {['all', 'high', 'medium', 'low', 'clean'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-xs px-3 py-1 rounded-full transition-colors ${
                filter === f
                  ? 'bg-accent text-white'
                  : 'dark:bg-dark-700 dark:text-dark-300 dark:hover:bg-dark-600 light:bg-warm-100 light:text-warm-500 light:hover:bg-warm-200'
              }`}
            >
              {f === 'all' ? `All (${total_docs})` : `${f.charAt(0).toUpperCase() + f.slice(1)} (${severity_counts[f] || 0})`}
            </button>
          ))}

          <span className="text-xs dark:text-dark-400 light:text-warm-400 ml-4 mr-1">Sort:</span>
          {[{key: 'score', label: 'Artifact score'}, {key: 'chunks', label: 'Chunk count'}, {key: 'title', label: 'Title'}].map(s => (
            <button
              key={s.key}
              onClick={() => setSortBy(s.key)}
              className={`text-xs px-3 py-1 rounded-full transition-colors ${
                sortBy === s.key
                  ? 'bg-accent text-white'
                  : 'dark:bg-dark-700 dark:text-dark-300 dark:hover:bg-dark-600 light:bg-warm-100 light:text-warm-500 light:hover:bg-warm-200'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* Document table */}
        <div className="rounded-lg border dark:border-dark-500 light:border-warm-300 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="dark:bg-dark-700 light:bg-warm-100">
                <th className="text-left px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">Status</th>
                <th className="text-left px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">Document</th>
                <th className="text-left px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">Type</th>
                <th className="text-left px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">Format</th>
                <th className="text-right px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">Score</th>
                <th className="text-right px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">Chunks</th>
                <th className="text-center px-4 py-2 dark:text-dark-300 light:text-warm-500 font-medium">URL</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((doc, i) => (
                <tr key={doc.doc_id}
                  className={`border-t dark:border-dark-600 light:border-warm-200
                    ${i % 2 === 0 ? 'dark:bg-dark-800 light:bg-white' : 'dark:bg-dark-750 light:bg-warm-50'}
                    hover:dark:bg-dark-600 hover:light:bg-warm-100 transition-colors`}>
                  <td className="px-4 py-2">
                    <SeverityBadge severity={doc.severity} />
                  </td>
                  <td className="px-4 py-2">
                    <div className="dark:text-warm-200 light:text-dark-700 font-medium truncate max-w-[280px]" title={doc.title}>
                      {doc.title}
                    </div>
                    <div className="text-xs dark:text-dark-400 light:text-warm-400">{doc.doc_id}</div>
                  </td>
                  <td className="px-4 py-2 text-xs dark:text-dark-300 light:text-warm-500 truncate max-w-[120px]">
                    {doc.source_type}
                  </td>
                  <td className="px-4 py-2 text-xs dark:text-dark-300 light:text-warm-500">
                    {doc.source_format || 'Unknown'}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums dark:text-dark-300 light:text-warm-500">
                    {doc.artifact_score != null ? doc.artifact_score.toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums dark:text-dark-300 light:text-warm-500">
                    {doc.total_chunks}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {doc.has_url ? (
                      doc.source_url && doc.source_url.trim() !== '' ? (
                        <a href={doc.source_url} target="_blank" rel="noopener noreferrer"
                          className="text-accent hover:text-accent-light">
                          <ExternalLink size={14} />
                        </a>
                      ) : (
                        <span className="text-emerald-400">—</span>
                      )
                    ) : (
                      <span className="dark:text-dark-500 light:text-warm-300">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-xs dark:text-dark-400 light:text-warm-400 mt-4">
          Showing {filtered.length} of {total_docs} documents.
          Artifact scores are computed during PDF extraction (higher = worse quality).
        </p>
      </div>
    </div>
  );
}
