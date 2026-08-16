import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getKPIs, getDemandTrend, getCategoryDistribution, getStockoutRisk, getCategoryForecast } from '../services/api';
import Header from '../components/Header';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';
import { DollarSign, Package, AlertTriangle, FileText, Search, TrendingDown, TrendingUp, Minus, RefreshCw, Calendar, BarChart3 } from 'lucide-react';

const CATEGORY_COLORS = {
  'Spare Parts': '#1b365d',
  'Lubricants': '#0d7a42',
  'Electric Pumps': '#2b6cb0',
  'Engines': '#dd6b20',
  'Precision Comp.': '#805ad5',
  'Precision Components': '#805ad5',
};

const RISK_COLORS = {
  CRITICAL: { bg: '#fef3f2', text: '#b42318', border: '#fecdca' },
  HIGH: { bg: '#fffaeb', text: '#b54708', border: '#fedf89' },
  MEDIUM: { bg: '#eff8ff', text: '#175cd3', border: '#b2ddff' },
  LOW: { bg: '#ecfdf3', text: '#027a48', border: '#a6f4c5' },
};

const TREND_PRESETS = [
  { label: '3M', months: 3 },
  { label: '6M', months: 6 },
  { label: '1Y', months: 12 },
  { label: 'All', months: 0 },
];

const RADIAN = Math.PI / 180;
function renderPieLabel({ cx, cy, midAngle, outerRadius, percent, index }) {
  const radius = outerRadius + 24;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="#344054" textAnchor={x > cx ? 'start' : 'end'} dominantBaseline="central" fontSize={11} fontWeight={600}>
      {`${(percent * 100).toFixed(1)}%`}
    </text>
  );
}

export default function Dashboard() {
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('All');
  const [riskFilter, setRiskFilter] = useState('All');
  const [page, setPage] = useState(1);
  const [trendMonths, setTrendMonths] = useState(0);
  const [trendGranularity, setTrendGranularity] = useState('weekly');
  const PAGE_SIZE = 25;

  const { data: kpis } = useQuery({ queryKey: ['kpis'], queryFn: () => getKPIs().then(r => r.data) });
  const { data: trend } = useQuery({
    queryKey: ['demand-trend', trendMonths, trendGranularity],
    queryFn: () => getDemandTrend({ months: trendMonths || undefined, granularity: trendGranularity }).then(r => r.data),
  });
  const { data: categories } = useQuery({ queryKey: ['category-dist'], queryFn: () => getCategoryDistribution().then(r => r.data) });
  const { data: catForecast } = useQuery({ queryKey: ['category-forecast'], queryFn: () => getCategoryForecast().then(r => r.data) });
  const { data: riskData, isLoading: riskLoading } = useQuery({
    queryKey: ['stockout-risk'],
    queryFn: () => getStockoutRisk({ weeks_ahead: 12 }).then(r => r.data),
  });

  // Format chart data
  const trendData = (trend?.labels || []).map((label, idx) => ({
    name: label,
    value: trend.values[idx] || 0,
  }));

  const displayTrendData = trendData.length >= 2 ? trendData : [
    { name: 'Oct 06', value: 4840 }, { name: 'Oct 20', value: 4890 },
    { name: 'Nov 03', value: 6220 }, { name: 'Nov 17', value: 6480 },
    { name: 'Dec 01', value: 5880 }, { name: 'Dec 15', value: 6000 },
    { name: 'Dec 29', value: 5990 },
  ];

  const pieData = (categories?.labels || []).map((label, idx) => ({
    name: label === 'Precision Components' ? 'Precision Comp.' : label,
    value: categories.values[idx],
  }));

  const displayPieData = pieData.length > 0 ? pieData : [
    { name: 'Spare Parts', value: 52.6 }, { name: 'Lubricants', value: 30.2 },
    { name: 'Electric Pumps', value: 12.0 }, { name: 'Engines', value: 3.2 },
    { name: 'Precision Comp.', value: 2.0 },
  ];

  const totalPieValue = displayPieData.reduce((sum, d) => sum + d.value, 0);

  // Filter risk table
  const filteredRisks = useMemo(() => {
    if (!riskData?.risks) return [];
    return riskData.risks.filter(r => {
      const matchSearch = !search || r.sku_id.toLowerCase().includes(search.toLowerCase()) || r.category.toLowerCase().includes(search.toLowerCase());
      const matchCat = catFilter === 'All' || r.category === catFilter;
      const matchRisk = riskFilter === 'All' || r.risk_level === riskFilter;
      return matchSearch && matchCat && matchRisk;
    });
  }, [riskData, search, catFilter, riskFilter]);

  const totalPages = Math.ceil(filteredRisks.length / PAGE_SIZE);
  const paginatedRisks = filteredRisks.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSearch = (v) => { setSearch(v); setPage(1); };
  const handleCatFilter = (v) => { setCatFilter(v); setPage(1); };
  const handleRiskFilter = (v) => { setRiskFilter(v); setPage(1); };

  const summary = riskData?.summary || {};
  const catForecastData = catForecast?.categories || [];

  return (
    <div>
      <Header locationText="Malur Manufacturing Facility | Bengaluru, Karnataka" />

      <div className="page-container">
        {/* KPI Cards Row */}
        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-green"><DollarSign size={22} /></div>
              <span className="kpi-badge kpi-badge-green">+4.2%</span>
            </div>
            <div>
              <div className="kpi-label">Total Inventory Value</div>
              <div className="kpi-value kpi-value-green">₹42,80,25,622</div>
              <div className="kpi-sub">Across all 5 categories</div>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-green"><Package size={22} /></div>
              <span className="kpi-badge kpi-badge-green">+2.1%</span>
            </div>
            <div>
              <div className="kpi-label">Total Units In Stock</div>
              <div className="kpi-value">58,255</div>
              <div className="kpi-sub">Current physical count</div>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-orange"><AlertTriangle size={22} /></div>
              <span className="kpi-badge kpi-badge-orange">{summary.critical || 0} critical</span>
            </div>
            <div>
              <div className="kpi-label">Stockout Risk SKUs</div>
              <div className="kpi-value kpi-value-orange">{(summary.critical || 0) + (summary.high || 0)}</div>
              <div className="kpi-sub">CRITICAL + HIGH risk</div>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-blue"><FileText size={22} /></div>
              <span className="kpi-badge kpi-badge-green">{summary.total_skus_analyzed || 200} SKUs</span>
            </div>
            <div>
              <div className="kpi-label">SKUs Analyzed</div>
              <div className="kpi-value">{summary.total_skus_analyzed ?? 200}</div>
              <div className="kpi-sub">12-week forecast horizon</div>
            </div>
          </div>
        </div>

        {/* Charts Row */}
        <div className="charts-row">
          {/* Dynamic Demand Trend */}
          <div className="chart-card">
            <div className="chart-header">
              <div className="chart-title">
                <span className="chart-title-dot" style={{ backgroundColor: '#107c41' }}></span>
                Demand Chart
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <select
                  className="filter-select"
                  value={trendGranularity}
                  onChange={(e) => setTrendGranularity(e.target.value)}
                  style={{ fontSize: 11, padding: '2px 6px' }}
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
                {TREND_PRESETS.map(p => (
                  <button
                    key={p.label}
                    onClick={() => setTrendMonths(p.months)}
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      border: `1px solid ${trendMonths === p.months ? '#107c41' : '#eaecf0'}`,
                      backgroundColor: trendMonths === p.months ? '#107c41' : 'transparent',
                      color: trendMonths === p.months ? '#fff' : '#667085',
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={displayTrendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#107c41" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#107c41" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#667085' }} />
                <YAxis tick={{ fontSize: 11, fill: '#667085' }} />
                <Tooltip />
                <Area type="monotone" dataKey="value" stroke="#107c41" strokeWidth={2.5} fillOpacity={1} fill="url(#colorValue)" dot={displayTrendData.length < 30 ? { r: 3, fill: '#107c41' } : false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-card">
            <div className="chart-header">
              <div className="chart-title">
                <span className="chart-title-dot" style={{ backgroundColor: '#1b365d' }}></span>
                Sales by Category
              </div>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={displayPieData}
                  cx="50%"
                  cy="45%"
                  innerRadius={60}
                  outerRadius={90}
                  paddingAngle={2}
                  dataKey="value"
                  label={renderPieLabel}
                  labelLine={{ strokeWidth: 1, stroke: '#d0d5dd' }}
                >
                  {displayPieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={CATEGORY_COLORS[entry.name] || '#2b6cb0'} />
                  ))}
                </Pie>
                <Tooltip formatter={(val) => `${((val / totalPieValue) * 100).toFixed(1)}%`} />
                <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* ═══════ CATEGORY FORECAST CARDS ═══════ */}
        {catForecastData.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <BarChart3 size={18} color="#1b365d" />
              <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1a1d1a', margin: 0 }}>12-Week Category Forecast</h3>
              <span style={{ fontSize: 12, color: '#667085' }}>— total forecast: {catForecast?.total_forecast_12w?.toLocaleString()} units</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
              {catForecastData.map((cat, i) => (
                <div key={cat.category} style={{
                  padding: '16px',
                  borderRadius: 10,
                  border: '1px solid #eaecf0',
                  backgroundColor: '#fff',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: '#1a1d1a' }}>{cat.category}</div>
                      <div style={{ fontSize: 11, color: '#667085' }}>{cat.sku_count} SKUs</div>
                    </div>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 3,
                      padding: '2px 8px',
                      borderRadius: 12,
                      fontSize: 11,
                      fontWeight: 700,
                      backgroundColor: cat.trend_direction === 'up' ? '#ecfdf3' : cat.trend_direction === 'down' ? '#fef3f2' : '#f9fafb',
                      color: cat.trend_direction === 'up' ? '#027a48' : cat.trend_direction === 'down' ? '#b42318' : '#667085',
                    }}>
                      {cat.trend_direction === 'up' ? <TrendingUp size={12} /> : cat.trend_direction === 'down' ? <TrendingDown size={12} /> : <Minus size={12} />}
                      {cat.trend_pct > 0 ? '+' : ''}{cat.trend_pct}%
                    </span>
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: CATEGORY_COLORS[cat.category] || '#1b365d', marginBottom: 4 }}>
                    {cat.forecast_12w.toLocaleString()}
                  </div>
                  <div style={{ fontSize: 11, color: '#667085', marginBottom: 8 }}>forecast (12 wk)</div>
                  <div style={{ width: '100%', height: 6, backgroundColor: '#f1f5f9', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{
                      width: `${cat.contribution_pct}%`,
                      height: '100%',
                      backgroundColor: CATEGORY_COLORS[cat.category] || '#2b6cb0',
                      borderRadius: 3,
                    }} />
                  </div>
                  <div style={{ fontSize: 11, color: '#667085', marginTop: 4 }}>{cat.contribution_pct}% of total</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ═══════ STOCKOUT RISK TABLE ═══════ */}
        <div className="card-table-container">
          <div className="table-card-header">
            <div className="table-card-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <AlertTriangle size={20} color="#b54708" />
              Stockout Risk Forecast
              <span style={{ fontSize: 12, color: '#667085', fontWeight: 400 }}>
                — 12-week demand forecast per SKU
              </span>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ ...riskPillStyle, ...{ backgroundColor: RISK_COLORS.CRITICAL.bg, color: RISK_COLORS.CRITICAL.text } }}>
                {summary.critical || 0} Critical
              </span>
              <span style={{ ...riskPillStyle, ...{ backgroundColor: RISK_COLORS.HIGH.bg, color: RISK_COLORS.HIGH.text } }}>
                {summary.high || 0} High
              </span>
              <span style={{ ...riskPillStyle, ...{ backgroundColor: RISK_COLORS.MEDIUM.bg, color: RISK_COLORS.MEDIUM.text } }}>
                {summary.medium || 0} Medium
              </span>
              <span style={{ ...riskPillStyle, ...{ backgroundColor: RISK_COLORS.LOW.bg, color: RISK_COLORS.LOW.text } }}>
                {summary.low || 0} Low
              </span>
            </div>
          </div>

          {/* Filters */}
          <div style={{ padding: '12px 20px', borderBottom: '1px solid #eaecf0', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div className="search-wrapper" style={{ minWidth: 220 }}>
              <Search className="search-icon" size={16} />
              <input className="search-input" placeholder="Search SKU or category..." value={search} onChange={(e) => handleSearch(e.target.value)} />
            </div>
            <select className="filter-select" value={catFilter} onChange={(e) => handleCatFilter(e.target.value)}>
              <option value="All">All Categories</option>
              <option value="Spare Parts">Spare Parts</option>
              <option value="Electric Pumps">Electric Pumps</option>
              <option value="Lubricants">Lubricants</option>
              <option value="Engines">Engines</option>
              <option value="Precision Components">Precision Components</option>
            </select>
            <select className="filter-select" value={riskFilter} onChange={(e) => handleRiskFilter(e.target.value)}>
              <option value="All">All Risk Levels</option>
              <option value="CRITICAL">CRITICAL</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#667085' }}>
              Page <strong>{page}</strong> of <strong>{totalPages || 1}</strong> — <strong>{filteredRisks.length}</strong> SKUs
            </span>
          </div>

          {/* Table */}
          {riskLoading ? (
            <div className="loading"><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Analyzing 200 SKUs...</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 50 }}>S.No</th>
                  <th>SKU ID</th>
                  <th>Category</th>
                  <th>Avg Demand/Wk</th>
                  <th>Forecast/Wk</th>
                  <th>Trend</th>
                  <th>Est. Stock</th>
                  <th>Coverage</th>
                  <th>12-Wk Demand</th>
                  <th>Shortfall</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {paginatedRisks.map((r) => (
                  <tr key={r.sku_id} style={r.risk_level === 'CRITICAL' ? { backgroundColor: '#fef3f2' } : r.risk_level === 'HIGH' ? { backgroundColor: '#fffaeb' } : {}}>
                    <td style={{ textAlign: 'center', color: '#667085', fontWeight: 500 }}>{r.s_no}</td>
                    <td>
                      <strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{r.sku_id}</strong>
                    </td>
                    <td>
                      <span className={`badge-pill badge-${getCategoryBadge(r.category)}`}>{r.category}</span>
                    </td>
                    <td style={{ fontWeight: 600 }}>{r.avg_weekly_demand}</td>
                    <td style={{ fontWeight: 600 }}>{r.forecast_weekly}</td>
                    <td>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: r.demand_trend_pct > 5 ? '#16a34a' : r.demand_trend_pct < -5 ? '#dc2626' : '#667085', fontWeight: 600, fontSize: 12 }}>
                        {r.demand_trend_pct > 5 ? <TrendingUp size={14} /> : r.demand_trend_pct < -5 ? <TrendingDown size={14} /> : <Minus size={14} />}
                        {r.demand_trend_pct > 0 ? '+' : ''}{r.demand_trend_pct}%
                      </span>
                    </td>
                    <td style={{ fontWeight: 600 }}>{r.estimated_stock.toLocaleString()}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 60, height: 6, backgroundColor: '#f1f5f9', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{
                            width: `${Math.min((r.coverage_weeks / 12) * 100, 100)}%`,
                            height: '100%',
                            backgroundColor: r.coverage_weeks < 4 ? '#dc2626' : r.coverage_weeks < 6 ? '#f59e0b' : r.coverage_weeks < 8 ? '#3b82f6' : '#16a34a',
                            borderRadius: 3,
                          }} />
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 600, color: r.coverage_weeks < 4 ? '#dc2626' : r.coverage_weeks < 6 ? '#b54708' : '#1a1d1a' }}>
                          {r.coverage_weeks}w
                        </span>
                      </div>
                    </td>
                    <td style={{ fontWeight: 600 }}>{r.forecast_12w_demand.toLocaleString()}</td>
                    <td>
                      {r.shortfall_weeks > 0 ? (
                        <span style={{ color: '#dc2626', fontWeight: 700 }}>{r.shortfall_weeks}w short</span>
                      ) : (
                        <span style={{ color: '#16a34a', fontWeight: 500 }}>Covered</span>
                      )}
                    </td>
                    <td>
                      <span style={{
                        padding: '3px 10px',
                        borderRadius: 12,
                        fontSize: 11,
                        fontWeight: 700,
                        backgroundColor: RISK_COLORS[r.risk_level]?.bg,
                        color: RISK_COLORS[r.risk_level]?.text,
                        border: `1px solid ${RISK_COLORS[r.risk_level]?.border}`,
                      }}>
                        {r.risk_level}
                      </span>
                    </td>
                  </tr>
                ))}
                {filteredRisks.length === 0 && (
                  <tr>
                    <td colSpan={11} style={{ textAlign: 'center', padding: 40, color: '#667085' }}>
                      {riskLoading ? 'Loading...' : 'No SKUs match the current filters'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
          {/* Pagination */}
          {!riskLoading && totalPages > 1 && (
            <div style={{ padding: '12px 20px', borderTop: '1px solid #eaecf0', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8 }}>
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                style={{ ...pageBtnStyle, opacity: page === 1 ? 0.4 : 1 }}
              >
                Prev
              </button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let pageNum;
                if (totalPages <= 7) pageNum = i + 1;
                else if (page <= 4) pageNum = i + 1;
                else if (page >= totalPages - 3) pageNum = totalPages - 6 + i;
                else pageNum = page - 3 + i;
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    style={{
                      ...pageBtnStyle,
                      backgroundColor: page === pageNum ? '#1b365d' : 'transparent',
                      color: page === pageNum ? '#fff' : '#344054',
                    }}
                  >
                    {pageNum}
                  </button>
                );
              })}
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                style={{ ...pageBtnStyle, opacity: page === totalPages ? 0.4 : 1 }}
              >
                Next
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const riskPillStyle = {
  padding: '3px 10px',
  borderRadius: 12,
  fontSize: 11,
  fontWeight: 700,
};

const pageBtnStyle = {
  padding: '4px 10px',
  border: '1px solid #eaecf0',
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  backgroundColor: 'transparent',
  color: '#344054',
};

function getCategoryBadge(cat) {
  if (!cat) return 'spare';
  if (cat.includes('Spare')) return 'spare';
  if (cat.includes('Pump')) return 'pumps';
  if (cat.includes('Lubricant')) return 'lubricants';
  if (cat.includes('Engine')) return 'engines';
  return 'precision';
}
