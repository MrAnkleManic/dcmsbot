import { X, ChevronDown, ChevronRight } from 'lucide-react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchStatus, fetchKbStats } from '../lib/api';

// Hierarchy mapping: group name -> { icon, types[] }
// Each type string must match the canonical doc_type from the backend
const CATEGORY_HIERARCHY = [
  {
    group: 'Legislation',
    icon: '\u{1F4DC}',
    types: [
      'Act',
      'Draft Bill & Amendments',
      'SI / Statutory Instrument',
      'Explanatory Notes',
      'Explanatory Memorandum',
      'Impact Assessment',
      'Delegated Powers Memo',
    ],
  },
  {
    group: 'Parliamentary Evidence & Debates',
    icon: '\u{1F3DB}\uFE0F',
    types: [
      'Written Evidence',
      'Oral Evidence Transcript',
      'Public Bill Committee Debate',
      'Public Bill Committee Evidence',
      'Commons',
      'Lords',
      'Parliamentary Research',
    ],
  },
  {
    group: 'Regulator - Ofcom',
    icon: '\u2696\uFE0F',
    types: [
      'Regulator Guidance',
      'Consultations and Statements',
      'Enforcement',
      'Information for Industry',
      'Research',
    ],
  },
  {
    group: 'Government',
    icon: '\u{1F3DB}\uFE0F',
    types: [
      'Government Response',
      'Ministerial Correspondence',
      'Correspondence',
    ],
  },
  {
    group: 'Other',
    icon: '\u{1F4F0}',
    types: [
      'News',
    ],
  },
];

function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center justify-between py-2 cursor-pointer">
      <span className="text-sm dark:text-warm-200 light:text-dark-700">{label}</span>
      <div
        className={`relative w-9 h-5 rounded-full transition-colors ${
          checked
            ? 'bg-accent'
            : 'dark:bg-dark-500 light:bg-warm-300'
        }`}
        onClick={onChange}
      >
        <div
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0.5'
          }`}
        />
      </div>
    </label>
  );
}

function GroupCheckbox({ label, checked, indeterminate, onChange, count, icon }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = indeterminate;
    }
  }, [indeterminate]);

  return (
    <label className="flex items-center gap-2 py-1 cursor-pointer">
      <input
        ref={ref}
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="w-4 h-4 rounded border dark:border-dark-400 dark:bg-dark-600 accent-accent shrink-0"
      />
      {icon && <span className="text-sm">{icon}</span>}
      <span className="text-sm font-medium dark:text-warm-100 light:text-dark-800 flex-1">
        {label}
      </span>
      {count != null && (
        <span className="text-xs font-mono dark:text-dark-400 light:text-warm-400 tabular-nums">
          {count.toLocaleString()}
        </span>
      )}
    </label>
  );
}

function CategoryCheckbox({ label, checked, onChange, count }) {
  return (
    <label className="flex items-center gap-3 py-1 cursor-pointer pl-6">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="w-3.5 h-3.5 rounded border dark:border-dark-400 dark:bg-dark-600 accent-accent shrink-0"
      />
      <span className="text-xs dark:text-warm-200 light:text-dark-700 flex-1">{label}</span>
      {count != null && (
        <span className="text-xs font-mono dark:text-dark-400 light:text-warm-400 tabular-nums">
          {count.toLocaleString()}
        </span>
      )}
    </label>
  );
}

function CategoryGroup({
  group,
  icon,
  types,
  chunkCounts,
  enabledSet,
  onToggleType,
  onToggleGroup,
  expanded,
  onToggleExpand,
}) {
  // Compute group totals from actual data
  const groupChunks = types.reduce((sum, t) => sum + (chunkCounts[t] || 0), 0);
  const checkedCount = types.filter(t => enabledSet.has(t)).length;
  const allChecked = checkedCount === types.length;
  const someChecked = checkedCount > 0 && checkedCount < types.length;

  return (
    <div className="mb-1">
      {/* Group header row */}
      <div className="flex items-center">
        <button
          onClick={onToggleExpand}
          className="p-0.5 mr-1 dark:text-dark-400 light:text-warm-400 shrink-0"
          aria-label={expanded ? 'Collapse group' : 'Expand group'}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <div className="flex-1">
          <GroupCheckbox
            label={group}
            icon={icon}
            checked={allChecked}
            indeterminate={someChecked}
            onChange={() => onToggleGroup(types, allChecked)}
            count={groupChunks}
          />
        </div>
      </div>

      {/* Children */}
      {expanded && (
        <div className="ml-5 space-y-0">
          {types
            .filter(t => chunkCounts[t] != null)
            .map(t => (
              <CategoryCheckbox
                key={t}
                label={t}
                checked={enabledSet.has(t)}
                onChange={() => onToggleType(t)}
                count={chunkCounts[t]}
              />
            ))}
        </div>
      )}
    </div>
  );
}

const GROUP_EXPAND_STORAGE_KEY = 'settingsGroupExpanded';

function loadGroupExpandState() {
  try {
    const stored = localStorage.getItem(GROUP_EXPAND_STORAGE_KEY);
    return stored ? JSON.parse(stored) : {};
  } catch {
    return {};
  }
}

function saveGroupExpandState(state) {
  try {
    localStorage.setItem(GROUP_EXPAND_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

export default function SettingsDrawer({
  isOpen,
  onClose,
  theme,
  toggleTheme,
  filters,
  onFiltersChange,
  debug,
  onDebugChange,
  scrollToFilters,
}) {
  const [devExpanded, setDevExpanded] = useState(false);
  const [kbStatus, setKbStatus] = useState(null);
  const [kbStats, setKbStats] = useState(null);
  const [groupExpanded, setGroupExpanded] = useState(loadGroupExpandState);
  const filtersRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      fetchKbStats().then(setKbStats).catch(() => {});
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && devExpanded) {
      fetchStatus().then(setKbStatus).catch(() => {});
    }
  }, [isOpen, devExpanded]);

  // Scroll to filters section when requested
  useEffect(() => {
    if (isOpen && scrollToFilters && filtersRef.current) {
      // Small delay to let the drawer animate open
      const timer = setTimeout(() => {
        filtersRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
        // Expand all groups when navigating from KB stats panel
        const allExpanded = {};
        CATEGORY_HIERARCHY.forEach(h => { allExpanded[h.group] = true; });
        setGroupExpanded(allExpanded);
        saveGroupExpandState(allExpanded);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [isOpen, scrollToFilters]);

  // Build chunk counts lookup from stats
  const chunkCounts = kbStats?.chunk_counts_by_type || {};

  // All known types from hierarchy
  const allTypes = CATEGORY_HIERARCHY.flatMap(h => h.types).filter(t => chunkCounts[t] != null);

  // Also include any types from the backend that aren't in the hierarchy
  const knownTypes = new Set(CATEGORY_HIERARCHY.flatMap(h => h.types));
  const unmappedTypes = Object.keys(chunkCounts).filter(t => !knownTypes.has(t));

  // The enabled set from filters - default to all if not set
  const enabledSet = new Set(
    filters.enabled_categories || [...allTypes, ...unmappedTypes]
  );

  const allSelected = allTypes.length > 0 && allTypes.every(t => enabledSet.has(t)) && unmappedTypes.every(t => enabledSet.has(t));
  const noneSelected = allTypes.length > 0 && ![...allTypes, ...unmappedTypes].some(t => enabledSet.has(t));

  const updateFilters = useCallback((newSet) => {
    onFiltersChange({
      ...filters,
      enabled_categories: [...newSet],
    });
  }, [filters, onFiltersChange]);

  const toggleType = useCallback((type) => {
    const next = new Set(enabledSet);
    if (next.has(type)) {
      next.delete(type);
    } else {
      next.add(type);
    }
    updateFilters(next);
  }, [enabledSet, updateFilters]);

  const toggleGroup = useCallback((types, allChecked) => {
    const next = new Set(enabledSet);
    types.forEach(t => {
      if (allChecked) {
        next.delete(t);
      } else {
        next.add(t);
      }
    });
    updateFilters(next);
  }, [enabledSet, updateFilters]);

  const selectAll = () => {
    updateFilters(new Set([...allTypes, ...unmappedTypes]));
  };

  const clearAll = () => {
    updateFilters(new Set());
  };

  const toggleGroupExpand = (groupName) => {
    setGroupExpanded(prev => {
      const next = { ...prev, [groupName]: !prev[groupName] };
      saveGroupExpandState(next);
      return next;
    });
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-80 z-50 shadow-xl overflow-y-auto
        dark:bg-dark-800 dark:border-l dark:border-dark-600
        light:bg-white light:border-l light:border-warm-200">
        <div className="p-5">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-base font-semibold dark:text-warm-100 light:text-dark-800">
              Settings
            </h2>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600 light:text-warm-400 light:hover:text-dark-800 light:hover:bg-warm-100 transition-colors"
            >
              <X size={18} />
            </button>
          </div>

          {/* Theme */}
          <div className="mb-6">
            <h3 className="text-xs font-semibold uppercase tracking-wider dark:text-dark-300 light:text-warm-400 mb-3">
              Appearance
            </h3>
            <Toggle
              label={theme === 'dark' ? 'Dark mode' : 'Light mode'}
              checked={theme === 'dark'}
              onChange={toggleTheme}
            />
          </div>

          {/* Document Source Filters - Hierarchical */}
          <div className="mb-6" ref={filtersRef}>
            <h3 className="text-xs font-semibold uppercase tracking-wider dark:text-dark-300 light:text-warm-400 mb-2">
              Source Filters
            </h3>

            {allTypes.length > 0 ? (
              <>
                {/* Select All / Clear All */}
                <div className="flex gap-2 mb-3">
                  <button
                    onClick={selectAll}
                    disabled={allSelected}
                    className={`text-xs px-2 py-1 rounded transition-colors ${
                      allSelected
                        ? 'dark:text-dark-500 light:text-warm-300 cursor-default'
                        : 'dark:text-accent light:text-accent hover:underline'
                    }`}
                  >
                    Select All
                  </button>
                  <span className="dark:text-dark-500 light:text-warm-300 text-xs py-1">/</span>
                  <button
                    onClick={clearAll}
                    disabled={noneSelected}
                    className={`text-xs px-2 py-1 rounded transition-colors ${
                      noneSelected
                        ? 'dark:text-dark-500 light:text-warm-300 cursor-default'
                        : 'dark:text-accent light:text-accent hover:underline'
                    }`}
                  >
                    Clear All
                  </button>
                </div>

                {/* Hierarchical groups */}
                <div className="space-y-0.5">
                  {CATEGORY_HIERARCHY.map(({ group, icon, types }) => {
                    // Only render groups that have at least one type in the data
                    const activeTypes = types.filter(t => chunkCounts[t] != null);
                    if (activeTypes.length === 0) return null;

                    return (
                      <CategoryGroup
                        key={group}
                        group={group}
                        icon={icon}
                        types={activeTypes}
                        chunkCounts={chunkCounts}
                        enabledSet={enabledSet}
                        onToggleType={toggleType}
                        onToggleGroup={toggleGroup}
                        expanded={groupExpanded[group] ?? false}
                        onToggleExpand={() => toggleGroupExpand(group)}
                      />
                    );
                  })}

                  {/* Unmapped types (if backend has types not in our hierarchy) */}
                  {unmappedTypes.length > 0 && (
                    <CategoryGroup
                      group="Uncategorized"
                      icon="\u{1F4C4}"
                      types={unmappedTypes}
                      chunkCounts={chunkCounts}
                      enabledSet={enabledSet}
                      onToggleType={toggleType}
                      onToggleGroup={toggleGroup}
                      expanded={groupExpanded['Uncategorized'] ?? false}
                      onToggleExpand={() => toggleGroupExpand('Uncategorized')}
                    />
                  )}
                </div>

                {/* Total */}
                <div className="mt-3 pt-2 border-t dark:border-dark-600 light:border-warm-200">
                  <div className="flex justify-between text-xs dark:text-dark-400 light:text-warm-400">
                    <span>Total chunks</span>
                    <span className="font-mono">{kbStats?.total_chunks?.toLocaleString()}</span>
                  </div>
                </div>
              </>
            ) : (
              <p className="text-xs dark:text-dark-400 light:text-warm-400 italic">
                Loading document categories...
              </p>
            )}
          </div>

          {/* Developer Tools */}
          <div className="border-t dark:border-dark-600 light:border-warm-200 pt-4">
            <button
              onClick={() => setDevExpanded(!devExpanded)}
              className="flex items-center gap-2 w-full text-left"
            >
              {devExpanded ? (
                <ChevronDown size={14} className="dark:text-dark-400 light:text-warm-400" />
              ) : (
                <ChevronRight size={14} className="dark:text-dark-400 light:text-warm-400" />
              )}
              <span className="text-xs font-semibold uppercase tracking-wider dark:text-dark-400 light:text-warm-400">
                Developer Tools
              </span>
            </button>

            {devExpanded && (
              <div className="mt-3 space-y-3">
                <div className="space-y-0.5">
                  <Toggle
                    label="Show KB inventory"
                    checked={debug.include_kb_status}
                    onChange={() => onDebugChange({ ...debug, include_kb_status: !debug.include_kb_status })}
                  />
                  <Toggle
                    label="Show retrieval debug"
                    checked={debug.include_retrieval_debug}
                    onChange={() => onDebugChange({ ...debug, include_retrieval_debug: !debug.include_retrieval_debug })}
                  />
                </div>

                {kbStatus && (
                  <div className="rounded-lg p-3 dark:bg-dark-700 light:bg-warm-50 border dark:border-dark-500 light:border-warm-200">
                    <h4 className="text-xs font-semibold dark:text-dark-300 light:text-warm-400 mb-2">
                      Knowledge Base
                    </h4>
                    <div className="space-y-1 text-xs dark:text-warm-300 light:text-dark-600">
                      <div className="flex justify-between">
                        <span>Total chunks</span>
                        <span className="font-mono">{kbStatus.total_chunks?.toLocaleString()}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Last refreshed</span>
                        <span className="font-mono">
                          {kbStatus.last_refreshed
                            ? new Date(kbStatus.last_refreshed).toLocaleDateString()
                            : 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Retrieval mode</span>
                        <span className="font-mono">{kbStatus.retrieval_mode || 'N/A'}</span>
                      </div>
                      {kbStatus.chunk_counts_by_type && (
                        <div className="mt-2 pt-2 border-t dark:border-dark-500 light:border-warm-200">
                          {Object.entries(kbStatus.chunk_counts_by_type).map(([type, count]) => (
                            <div key={type} className="flex justify-between">
                              <span>{type}</span>
                              <span className="font-mono">{count.toLocaleString()}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
