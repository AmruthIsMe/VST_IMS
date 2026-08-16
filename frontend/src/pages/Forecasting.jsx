import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  getSkuExplorer, getForecastProducts, getReorderRecommendations,
} from '../services/api';
import Header from '../components/Header';
import {
  Line, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
  ComposedChart,
} from 'recharts';
import {
  TrendingUp, Target, RefreshCw, Clock,
  Search, ShoppingCart, AlertTriangle, DollarSign
} from 'lucide-react';

const TABS = [
  { id: 'sku-explorer', label: 'SKU Explorer', icon: Search },
  { id: 'reorder', label: 'Reorder Panel', icon: ShoppingCart },
];

export default function Forecasting() {
  const [activeTab, setActiveTab] = useState('sku-explorer');
  const [skuSearch, setSkuSearch] = useState('');
  const [selectedSku, setSelectedSku] = useState('');
  const [skuCategory, setSkuCategory] = useState('');
  const [skuSubCategory, setSkuSubCategory] = useState('');
  const [skuCriticality, setSkuCriticality] = useState('');
  // ── Queries ──
  // ── SKU Explorer Queries ──
  const { data: productsData, isLoading: productsLoading } = useQuery({
    queryKey: ['forecast-products', skuCategory, skuSubCategory, skuCriticality, skuSearch],
    queryFn: () => getForecastProducts({
      category: skuCategory || undefined,
      sub_category: skuSubCategory || undefined,
      criticality_min: skuCriticality ? parseFloat(skuCriticality) : undefined,
      search: skuSearch || undefined,
    }).then(r => r.data),
    enabled: activeTab === 'sku-explorer',
  });

  const { data: skuData, isLoading: skuLoading } = useQuery({
    queryKey: ['sku-explorer', selectedSku],
    queryFn: () => getSkuExplorer({ sku_id: selectedSku, horizon_weeks: 12 }).then(r => r.data),
    enabled: activeTab === 'sku-explorer' && !!selectedSku,
  });

  const { data: reorderData, isLoading: reorderLoading } = useQuery({
    queryKey: ['reorder-recs'],
    queryFn: () => getReorderRecommendations().then(r => r.data),
    enabled: activeTab === 'reorder',
  });

  return (
    <div>
      <Header locationText="Demand Forecasting Engine — Multi-Model Ensemble" />

      <div className="page-container">
        {/* Page Banner */}
        <div className="page-banner">
          <div className="page-banner-icon">
            <TrendingUp size={24} />
          </div>
          <h1 className="page-banner-title">Demand Forecasting</h1>
        </div>

        {/* Tabs */}
        <div className="page-tabs">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`tab-btn ${activeTab === id ? 'active' : ''}`}
              onClick={() => setActiveTab(id)}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>

        {/* ═══════ TAB 1: SKU EXPLORER ═══════ */}
        {activeTab === 'sku-explorer' && (
          <div className="forecast-overview">
            {/* ── Two-Column Layout: Filters + Products List | Forecast Detail ── */}
            <div style={{ display: 'grid', gridTemplateColumns: selectedSku ? '380px 1fr' : '1fr', gap: 20 }}>

              {/* ═══ LEFT PANEL: Filters + Product List ═══ */}
              <div>
                {/* Slicers Bar */}
                <div style={{
                  padding: '16px',
                  borderRadius: 12,
                  border: '1px solid #eaecf0',
                  backgroundColor: '#fff',
                  marginBottom: 16,
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#1a1d1a', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Search size={14} /> Filter Products
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {/* Search */}
                    <div style={{ gridColumn: '1 / -1' }}>
                      <label style={labelStyle}>Search SKU</label>
                      <div className="search-wrapper" style={{ width: '100%' }}>
                        <Search className="search-icon" size={14} />
                        <input
                          className="search-input"
                          placeholder="Type SKU ID or name..."
                          value={skuSearch}
                          onChange={(e) => setSkuSearch(e.target.value)}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>
                    {/* Category */}
                    <div>
                      <label style={labelStyle}>Category</label>
                      <select className="filter-select" style={{ width: '100%' }} value={skuCategory} onChange={(e) => { setSkuCategory(e.target.value); setSkuSubCategory(''); }}>
                        <option value="">All Categories</option>
                        {productsData?.filter_options?.categories?.map(c => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                    {/* Sub-Category */}
                    <div>
                      <label style={labelStyle}>Sub-Category</label>
                      <select className="filter-select" style={{ width: '100%' }} value={skuSubCategory} onChange={(e) => setSkuSubCategory(e.target.value)}>
                        <option value="">All Sub-Categories</option>
                        {productsData?.filter_options?.sub_categories?.map(sc => (
                          <option key={sc} value={sc}>{sc}</option>
                        ))}
                      </select>
                    </div>
                    {/* Criticality */}
                    <div>
                      <label style={labelStyle}>Criticality</label>
                      <select className="filter-select" style={{ width: '100%' }} value={skuCriticality} onChange={(e) => setSkuCriticality(e.target.value)}>
                        <option value="">All Levels</option>
                        <option value="4">4 - Critical</option>
                        <option value="3">3 - High</option>
                        <option value="2">2 - Medium</option>
                        <option value="1">1 - Low</option>
                      </select>
                    </div>
                    {/* Results count */}
                    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end' }}>
                      <span style={{ fontSize: 12, color: '#667085' }}>
                        <strong>{productsData?.total || 0}</strong> products found
                      </span>
                    </div>
                  </div>
                </div>

                {/* Product List Table */}
                <div style={{
                  borderRadius: 12,
                  border: '1px solid #eaecf0',
                  backgroundColor: '#fff',
                  overflow: 'hidden',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                  maxHeight: selectedSku ? 'calc(100vh - 320px)' : 'calc(100vh - 280px)',
                  overflowY: 'auto',
                }}>
                  {productsLoading ? (
                    <div className="loading" style={{ padding: 40 }}><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Loading products...</div>
                  ) : (
                    <table className="data-table" style={{ margin: 0 }}>
                      <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                        <tr>
                          <th style={{ width: 40 }}>#</th>
                          <th>SKU ID</th>
                          <th>Category</th>
                          <th>Sub-Category</th>
                          <th>Crit.</th>
                          <th>Avg/Wk</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {productsData?.products?.map((p, i) => (
                          <tr
                            key={p.sku_id}
                            onClick={() => setSelectedSku(p.sku_id)}
                            style={{
                              cursor: 'pointer',
                              backgroundColor: selectedSku === p.sku_id ? '#eff8ff' : (i % 2 === 0 ? '#fff' : '#f9fafb'),
                              borderLeft: selectedSku === p.sku_id ? '3px solid #2563eb' : '3px solid transparent',
                              transition: 'background-color 0.15s',
                            }}
                            onMouseEnter={(e) => { if (selectedSku !== p.sku_id) e.currentTarget.style.backgroundColor = '#f5f5f5'; }}
                            onMouseLeave={(e) => { if (selectedSku !== p.sku_id) e.currentTarget.style.backgroundColor = i % 2 === 0 ? '#fff' : '#f9fafb'; }}
                          >
                            <td style={{ textAlign: 'center', color: '#667085', fontSize: 11 }}>{i + 1}</td>
                            <td>
                              <strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{p.sku_id}</strong>
                            </td>
                            <td>
                              <span className={`badge-pill badge-${getCategoryBadge(p.category)}`} style={{ fontSize: 10 }}>
                                {p.category}
                              </span>
                            </td>
                            <td style={{ fontSize: 12 }}>{p.sub_category}</td>
                            <td style={{ textAlign: 'center' }}>
                              <span style={{
                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                width: 22, height: 22, borderRadius: '50%', fontSize: 10, fontWeight: 700,
                                backgroundColor: p.criticality_score >= 4 ? '#dc2626' : p.criticality_score >= 3 ? '#f59e0b' : p.criticality_score >= 2 ? '#3b82f6' : '#16a34a',
                                color: '#fff',
                              }}>
                                {p.criticality_score}
                              </span>
                            </td>
                            <td style={{ fontWeight: 600, fontSize: 12 }}>{p.avg_weekly_demand}</td>
                            <td>
                              {selectedSku === p.sku_id && <span style={{ color: '#2563eb', fontWeight: 700, fontSize: 11 }}>SELECTED</span>}
                            </td>
                          </tr>
                        ))}
                        {productsData?.products?.length === 0 && (
                          <tr><td colSpan={7} style={{ textAlign: 'center', padding: 30, color: '#667085' }}>No products match filters</td></tr>
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* ═══ RIGHT PANEL: Forecast Detail ═══ */}
              <div>
                {!selectedSku ? (
                  <div style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    height: 'calc(100vh - 280px)', color: '#667085',
                    border: '2px dashed #eaecf0', borderRadius: 12, backgroundColor: '#fafafa',
                  }}>
                    <Search size={48} strokeWidth={1.5} style={{ marginBottom: 16, opacity: 0.4 }} />
                    <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Select a SKU to explore</h3>
                    <p style={{ fontSize: 13, textAlign: 'center', maxWidth: 320 }}>
                      Click any product in the list to view its 12-week demand forecast, confidence band, and stockout risk.
                    </p>
                  </div>
                ) : skuLoading ? (
                  <div className="loading" style={{ padding: 60 }}><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Loading forecast for {selectedSku}...</div>
                ) : skuData?.status === 'error' ? (
                  <div style={{ padding: 20, color: '#dc2626', backgroundColor: '#fef3f2', borderRadius: 10 }}>{skuData.message}</div>
                ) : skuData?.status === 'success' ? (
                  <>
                    {/* Header with back button */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                      <button
                        onClick={() => setSelectedSku('')}
                        style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #eaecf0', backgroundColor: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                      >
                        ← Back to list
                      </button>
                      <div>
                        <h2 style={{ fontSize: 18, fontWeight: 800, margin: 0, fontFamily: 'monospace' }}>{selectedSku}</h2>
                        <span style={{ fontSize: 12, color: '#667085' }}>{skuData.product?.category} › {skuData.product?.sub_category}</span>
                      </div>
                    </div>

                    {/* KPI Cards */}
                    <div className="kpi-grid" style={{ marginBottom: 16 }}>
                      <div className="kpi-card">
                        <div className="kpi-top-row">
                          <div className="kpi-icon-box kpi-icon-green"><TrendingUp size={22} /></div>
                          <span className="kpi-badge" style={{ backgroundColor: skuData.stats?.trend_pct > 0 ? '#ecfdf3' : '#fef3f2', color: skuData.stats?.trend_pct > 0 ? '#027a48' : '#b42318' }}>
                            {skuData.stats?.trend_pct > 0 ? '+' : ''}{skuData.stats?.trend_pct}%
                          </span>
                        </div>
                        <div>
                          <div className="kpi-label">Avg Weekly Demand</div>
                          <div className="kpi-value">{skuData.stats?.avg_weekly_demand}</div>
                          <div className="kpi-sub">Forecast: {skuData.stats?.forecast_weekly}/wk</div>
                        </div>
                      </div>
                      <div className="kpi-card">
                        <div className="kpi-top-row">
                          <div className="kpi-icon-box kpi-icon-orange"><Clock size={22} /></div>
                        </div>
                        <div>
                          <div className="kpi-label">Coverage</div>
                          <div className="kpi-value" style={{ color: skuData.stats?.coverage_weeks < 6 ? '#dc2626' : '#1a1d1a' }}>
                            {skuData.stats?.coverage_weeks} weeks
                          </div>
                          <div className="kpi-sub">Est. stock: {skuData.stats?.estimated_stock}</div>
                        </div>
                      </div>
                      <div className="kpi-card">
                        <div className="kpi-top-row">
                          <div className="kpi-icon-box" style={{ backgroundColor: '#eff8ff', color: '#175cd3' }}><Target size={22} /></div>
                        </div>
                        <div>
                          <div className="kpi-label">12-Week Forecast</div>
                          <div className="kpi-value">{skuData.stats?.total_12w_forecast?.toLocaleString()}</div>
                          <div className="kpi-sub">Total predicted demand</div>
                        </div>
                      </div>
                    </div>

                    {/* Stockout Alert */}
                    {skuData.stockout_alert && (
                      <div style={{
                        padding: '12px 16px', borderRadius: 10, marginBottom: 16,
                        backgroundColor: skuData.stockout_alert.severity === 'CRITICAL' ? '#fef3f2' : '#fffaeb',
                        border: `1px solid ${skuData.stockout_alert.severity === 'CRITICAL' ? '#fecdca' : '#fedf89'}`,
                        display: 'flex', alignItems: 'center', gap: 10,
                      }}>
                        <AlertTriangle size={18} color={skuData.stockout_alert.severity === 'CRITICAL' ? '#b42318' : '#b54708'} />
                        <span style={{ fontSize: 13, fontWeight: 600, color: skuData.stockout_alert.severity === 'CRITICAL' ? '#b42318' : '#b54708' }}>
                          {skuData.stockout_alert.message}
                        </span>
                      </div>
                    )}

                    {/* Forecast Chart */}
                    <div className="chart-card">
                      <div className="chart-header">
                        <div className="chart-title">
                          <span className="chart-title-dot" style={{ backgroundColor: '#2563eb' }} />
                          12-Week Forecast with Confidence Band (±2σ)
                        </div>
                      </div>
                      <ResponsiveContainer width="100%" height={350}>
                        <ComposedChart margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#667085' }} type="category" allowDuplicatedCategory={false} />
                          <YAxis tick={{ fontSize: 11, fill: '#667085' }} />
                          <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12 }} />
                          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
                          <Line
                            data={skuData.history?.dates?.map((d, i) => ({ date: d, actual: skuData.history.values[i] })) || []}
                            type="monotone" dataKey="actual" name="Actual Demand"
                            stroke="#1a1d1a" strokeWidth={2} dot={{ r: 2 }}
                          />
                          <Area
                            data={skuData.forecast?.dates?.map((d, i) => ({ date: d, upper: skuData.forecast.upper_bound[i], lower: skuData.forecast.lower_bound[i] })) || []}
                            type="monotone" dataKey="upper" name="Upper Bound"
                            stroke="none" fill="#2563eb" fillOpacity={0.1} legendType="none"
                          />
                          <Area
                            data={skuData.forecast?.dates?.map((d, i) => ({ date: d, upper: skuData.forecast.upper_bound[i], lower: skuData.forecast.lower_bound[i] })) || []}
                            type="monotone" dataKey="lower" name="Lower Bound"
                            stroke="none" fill="#fff" fillOpacity={1} legendType="none"
                          />
                          <Line
                            data={skuData.forecast?.dates?.map((d, i) => ({ date: d, forecast: skuData.forecast.values[i] })) || []}
                            type="monotone" dataKey="forecast" name="Ensemble Forecast"
                            stroke="#2563eb" strokeWidth={2.5} strokeDasharray="6 3" dot={false}
                          />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {/* ═══════ TAB 6: REORDER RECOMMENDATIONS ═══════ */}
        {activeTab === 'reorder' && (
          <div className="forecast-overview">
            {reorderLoading ? (
              <div className="loading"><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Generating reorder recommendations...</div>
            ) : reorderData?.status === 'success' ? (
              <>
                {/* Summary KPIs */}
                <div className="kpi-grid" style={{ marginBottom: 24 }}>
                  <div className="kpi-card">
                    <div className="kpi-top-row">
                      <div className="kpi-icon-box kpi-icon-orange"><ShoppingCart size={22} /></div>
                    </div>
                    <div>
                      <div className="kpi-label">SKUs Needing Reorder</div>
                      <div className="kpi-value kpi-value-orange">{reorderData.total_recommendations}</div>
                      <div className="kpi-sub">Coverage {'<'} 8 weeks</div>
                    </div>
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-top-row">
                      <div className="kpi-icon-box kpi-icon-green"><DollarSign size={22} /></div>
                    </div>
                    <div>
                      <div className="kpi-label">Total Estimated Cost</div>
                      <div className="kpi-value">₹{formatINR(reorderData.total_estimated_cost_inr)}</div>
                      <div className="kpi-sub">Reorder budget needed</div>
                    </div>
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-top-row">
                      <div className="kpi-icon-box" style={{ backgroundColor: '#fef3f2', color: '#b42318' }}><AlertTriangle size={22} /></div>
                    </div>
                    <div>
                      <div className="kpi-label">Critical Urgency</div>
                      <div className="kpi-value" style={{ color: '#b42318' }}>
                        {reorderData.recommendations?.filter(r => r.urgency === 'CRITICAL').length || 0}
                      </div>
                      <div className="kpi-sub">Order within 7 days</div>
                    </div>
                  </div>
                </div>

                {/* Recommendations Table */}
                <div className="card-table-container">
                  <div className="table-card-header">
                    <div className="table-card-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <ShoppingCart size={20} color="#b54708" />
                      Reorder Recommendations
                      <span style={{ fontSize: 12, color: '#667085', fontWeight: 400 }}>— based on 12-week demand forecast</span>
                    </div>
                  </div>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>S.No</th>
                        <th>SKU ID</th>
                        <th>Category</th>
                        <th>Criticality</th>
                        <th>Forecast/Wk</th>
                        <th>Est. Stock</th>
                        <th>Coverage</th>
                        <th>Lead Time</th>
                        <th>Order By</th>
                        <th>Qty</th>
                        <th>Est. Cost</th>
                        <th>Urgency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reorderData.recommendations?.slice(0, 50).map((r, i) => (
                        <tr key={r.sku_id} style={r.urgency === 'CRITICAL' ? { backgroundColor: '#fef3f2' } : r.urgency === 'HIGH' ? { backgroundColor: '#fffaeb' } : {}}>
                          <td style={{ textAlign: 'center', color: '#667085', fontWeight: 500 }}>{i + 1}</td>
                          <td><strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{r.sku_id}</strong></td>
                          <td><span className={`badge-pill badge-${getCategoryBadge(r.category)}`}>{r.category}</span></td>
                          <td style={{ textAlign: 'center' }}>
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                              width: 24, height: 24, borderRadius: '50%',
                              backgroundColor: r.criticality >= 0.8 ? '#dc2626' : r.criticality >= 0.5 ? '#f59e0b' : '#16a34a',
                              color: '#fff', fontSize: 11, fontWeight: 700,
                            }}>
                              {r.criticality}
                            </span>
                          </td>
                          <td style={{ fontWeight: 600 }}>{r.forecast_weekly}</td>
                          <td style={{ fontWeight: 600 }}>{r.estimated_stock}</td>
                          <td>
                            <span style={{ fontWeight: 600, color: r.coverage_weeks < 4 ? '#dc2626' : r.coverage_weeks < 6 ? '#b54708' : '#1a1d1a' }}>
                              {r.coverage_weeks}w
                            </span>
                          </td>
                          <td>{r.lead_time_days}d</td>
                          <td>
                            <span style={{ fontWeight: 600, color: r.order_by_days_from_now <= 7 ? '#dc2626' : '#1a1d1a' }}>
                              {r.order_by_date}
                              {r.order_by_days_from_now <= 7 && <span style={{ fontSize: 10, color: '#dc2626', marginLeft: 4 }}>({r.order_by_days_from_now}d)</span>}
                            </span>
                          </td>
                          <td><strong>{r.qty_recommended}</strong></td>
                          <td style={{ fontWeight: 600 }}>₹{formatINR(r.estimated_cost_inr)}</td>
                          <td>
                            <span style={{
                              padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 700,
                              backgroundColor: r.urgency === 'CRITICAL' ? '#fef3f2' : r.urgency === 'HIGH' ? '#fffaeb' : '#eff8ff',
                              color: r.urgency === 'CRITICAL' ? '#b42318' : r.urgency === 'HIGH' ? '#b54708' : '#175cd3',
                              border: `1px solid ${r.urgency === 'CRITICAL' ? '#fecdca' : r.urgency === 'HIGH' ? '#fedf89' : '#b2ddff'}`,
                            }}>
                              {r.urgency}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="forecast-empty-state">
                <ShoppingCart size={48} strokeWidth={1.5} />
                <h3>No Reorder Recommendations</h3>
                <p>All SKUs have adequate stock coverage.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const labelStyle = {
  display: 'block',
  fontSize: 11,
  fontWeight: 600,
  color: '#667085',
  marginBottom: 4,
  textTransform: 'uppercase',
  letterSpacing: '0.03em',
};

function getCategoryBadge(cat) {
  if (!cat) return 'spare';
  if (cat.includes('Spare')) return 'spare';
  if (cat.includes('Pump')) return 'pumps';
  if (cat.includes('Lubricant')) return 'lubricants';
  if (cat.includes('Engine')) return 'engines';
  return 'precision';
}

function formatINR(num) {
  if (num == null || isNaN(num)) return '0';
  const s = Math.round(num).toString();
  if (s.length <= 3) return s;
  let last3 = s.slice(-3);
  let rest = s.slice(0, -3);
  rest = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return rest + ',' + last3;
}
