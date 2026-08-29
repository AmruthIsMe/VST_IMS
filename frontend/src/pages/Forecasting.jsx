import { useState, useEffect, useMemo } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import {
  getSkuExplorer, getForecastProducts, getReorderRecommendations, getYearlyDemand,
} from '../services/api';
import Header from '../components/Header';
import {
  Line, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
  ComposedChart, BarChart, Bar,
} from 'recharts';
import {
  TrendingUp, Target, RefreshCw, Clock,
  Search, ShoppingCart, AlertTriangle, DollarSign, Calendar, Activity,
} from 'lucide-react';
import ModelDrilldown from '../components/ModelDrilldown';

const TABS = [
  { id: 'sku-explorer', label: 'SKU Explorer', icon: Search },
  { id: 'reorder', label: 'Reorder Panel', icon: ShoppingCart },
  { id: 'model-drilldown', label: 'Performance Drill-down', icon: Activity },
];

export default function Forecasting({ onMenuToggle }) {
  const [activeTab, setActiveTab] = useState('sku-explorer');
  const [skuSearch, setSkuSearch] = useState('');
  const [selectedSku, setSelectedSku] = useState('');
  const [skuCategory, setSkuCategory] = useState('');
  const [skuSubCategory, setSkuSubCategory] = useState('');
  const [reorderPage, setReorderPage] = useState(1);
  const REORDER_PAGE_SIZE = 25;
  const currentYear = new Date().getFullYear();
  const [dateFrom, setDateFrom] = useState(`${currentYear}-01-01`);
  const [dateTo, setDateTo] = useState(`${currentYear}-12-31`);
  // ── Queries ──
  // ── SKU Explorer Queries ──
  const { data: productsData, isLoading: productsLoading } = useQuery({
    queryKey: ['forecast-products', skuCategory, skuSubCategory, skuSearch],
    queryFn: () => getForecastProducts({
      category: skuCategory || undefined,
      sub_category: skuSubCategory || undefined,
      search: skuSearch || undefined,
    }).then(r => r.data),
    enabled: activeTab === 'sku-explorer',
    placeholderData: keepPreviousData,
  });

  const { data: skuData, isLoading: skuLoading } = useQuery({
    queryKey: ['sku-explorer', selectedSku],
    queryFn: () => getSkuExplorer({ sku_id: selectedSku, horizon_weeks: 12 }).then(r => r.data),
    placeholderData: (previousData, currentData) => {
      // When switching SKUs, keep the previous SKU's data during the transition
      if (!currentData) return previousData;
      return currentData;
    },
    enabled: activeTab === 'sku-explorer' && !!selectedSku,
    placeholderData: keepPreviousData,
  });

  const { data: yearlyData, isLoading: yearlyLoading } = useQuery({
    queryKey: ['yearly-demand', selectedSku, dateFrom, dateTo],
    queryFn: () => getYearlyDemand({ sku_id: selectedSku, start_date: dateFrom, end_date: dateTo }).then(r => r.data),
    enabled: activeTab === 'sku-explorer' && !!selectedSku,
    placeholderData: keepPreviousData,
  });

  // Clamp date range to available data when SKU changes
  useEffect(() => {
    if (yearlyData?.min_date && yearlyData?.max_date) {
      setDateFrom((prev) => prev < yearlyData.min_date ? yearlyData.min_date : prev);
      setDateTo((prev) => prev > yearlyData.max_date ? yearlyData.max_date : prev);
    }
  }, [yearlyData?.min_date, yearlyData?.max_date, selectedSku]);

  // Auto-select first SKU when products load
  useEffect(() => {
    if (activeTab === 'sku-explorer' && productsData?.products?.length > 0 && !selectedSku) {
      setSelectedSku(productsData.products[0].sku_id);
    }
  }, [activeTab, productsData]);

  const { data: reorderData, isLoading: reorderLoading } = useQuery({
    queryKey: ['reorder-recs'],
    queryFn: () => getReorderRecommendations().then(r => r.data),
    enabled: activeTab === 'reorder',
    placeholderData: keepPreviousData,
  });

  return (
    <div>
      <Header locationText="Demand Forecasting Engine — Multi-Model Ensemble" onMenuToggle={onMenuToggle} />

      <div style={{ padding: '12px 32px 24px 32px' }}>
        {/* Page Banner + Tabs inline */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 20px', borderRadius: 12, marginBottom: 14,
          backgroundColor: '#fff', border: '1px solid #eaecf0',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div className="page-banner-icon" style={{ margin: 0 }}>
              <TrendingUp size={24} />
            </div>
            <h1 style={{ fontSize: 20, fontWeight: 800, margin: 0, color: '#1a1d1a' }}>Demand Forecasting</h1>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                className={`tab-btn ${activeTab === id ? 'active' : ''}`}
                onClick={() => { setActiveTab(id); if (id === 'reorder') setReorderPage(1); }}
                style={{ margin: 0 }}
              >
                <Icon size={16} />
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* ═══════ TAB 1: SKU EXPLORER ═══════ */}
        {activeTab === 'sku-explorer' && (
          <div className="forecast-overview">
            {/* ── Two-Column Layout: Filters + Products List | Forecast Detail ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: 14 }}>

              {/* ═══ LEFT PANEL: Filters + Product List ═══ */}
              <div>
                {/* Slicers Bar */}
                <div style={{
                  padding: '14px',
                  borderRadius: 12,
                  border: '1px solid #eaecf0',
                  backgroundColor: '#fff',
                  marginBottom: 10,
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
                  maxHeight: 'calc(100vh - 220px)',
                  overflowY: 'auto',
                }}>
                  {productsLoading ? (
                    <div className="loading" style={{ padding: 40 }}><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Loading products...</div>
                  ) : (
                    <table className="data-table" style={{ margin: 0 }}>
                      <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                        <tr>
                          <th style={{ width: 32, padding: '8px 10px', fontSize: 11 }}>#</th>
                          <th style={{ padding: '8px 10px', fontSize: 11 }}>SKU ID</th>
                          <th style={{ padding: '8px 10px', fontSize: 11 }}>Category</th>
                          <th style={{ padding: '8px 10px', fontSize: 11 }}>Sub-Category</th>
                          <th style={{ padding: '8px 10px', fontSize: 11 }}>Avg/Wk</th>
                          <th style={{ padding: '8px 10px', fontSize: 11 }}></th>
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
                            <td style={{ textAlign: 'center', color: '#667085', fontSize: 10, padding: '6px 10px' }}>{i + 1}</td>
                            <td style={{ padding: '6px 10px' }}>
                              <strong style={{ fontFamily: 'monospace', fontSize: 11 }}>{p.sku_id}</strong>
                            </td>
                            <td style={{ padding: '6px 10px' }}>
                              <span className={`badge-pill badge-${getCategoryBadge(p.category)}`} style={{ fontSize: 9, padding: '2px 8px' }}>
                                {p.category}
                              </span>
                            </td>
                            <td style={{ fontSize: 11, padding: '6px 10px' }}>{p.sub_category}</td>
                            <td style={{ fontWeight: 600, fontSize: 11, padding: '6px 10px' }}>{p.avg_weekly_demand}</td>
                            <td style={{ padding: '6px 10px' }}>
                              {selectedSku === p.sku_id && <span style={{ color: '#2563eb', fontWeight: 700, fontSize: 10 }}>SELECTED</span>}
                            </td>
                          </tr>
                        ))}
                        {productsData?.products?.length === 0 && (
                          <tr><td colSpan={6} style={{ textAlign: 'center', padding: 20, color: '#667085' }}>No products match filters</td></tr>
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* ═══ RIGHT PANEL: Forecast Detail ═══ */}
              <div>
                {skuLoading ? (
                  <div className="loading" style={{ padding: 60 }}><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Loading forecast for {selectedSku}...</div>
                ) : skuData?.status === 'error' ? (
                  <div style={{ padding: 20, color: '#dc2626', backgroundColor: '#fef3f2', borderRadius: 10 }}>{skuData.message}</div>
                ) : skuData?.status === 'success' ? (
                  <>
                    {/* Header */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                      <div>
                        <h2 style={{ fontSize: 18, fontWeight: 800, margin: 0, fontFamily: 'monospace' }}>{selectedSku}</h2>
                        <span style={{ fontSize: 12, color: '#667085' }}>{skuData.product?.category} › {skuData.product?.sub_category}</span>
                      </div>
                    </div>

                    {/* KPI Cards — compact */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 10 }}>
                      <div style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                          <div style={{ width: 30, height: 30, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#ecfdf3', color: '#027a48' }}><TrendingUp size={16} /></div>
                          <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700, backgroundColor: skuData.stats?.trend_pct > 0 ? '#ecfdf3' : '#fef3f2', color: skuData.stats?.trend_pct > 0 ? '#027a48' : '#b42318' }}>
                            {skuData.stats?.trend_pct > 0 ? '+' : ''}{skuData.stats?.trend_pct}%
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Avg Weekly Demand</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: '#1a1d1a', lineHeight: 1.2 }}>{skuData.stats?.avg_weekly_demand}</div>
                        <div style={{ fontSize: 11, color: '#667085' }}>Forecast: {skuData.stats?.forecast_weekly}/wk</div>
                      </div>
                      <div style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
                        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                          <div style={{ width: 30, height: 30, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#fffaeb', color: '#b54708' }}><Clock size={16} /></div>
                        </div>
                        <div style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Coverage</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: skuData.stats?.coverage_weeks < 6 ? '#dc2626' : '#1a1d1a', lineHeight: 1.2 }}>
                          {skuData.stats?.coverage_weeks} weeks
                        </div>
                        <div style={{ fontSize: 11, color: '#667085' }}>Est. stock: {skuData.stats?.estimated_stock}</div>
                      </div>
                      <div style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
                        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                          <div style={{ width: 30, height: 30, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#eff8ff', color: '#175cd3' }}><Target size={16} /></div>
                        </div>
                        <div style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>12-Week Forecast</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: '#1a1d1a', lineHeight: 1.2 }}>{skuData.stats?.total_12w_forecast?.toLocaleString()}</div>
                        <div style={{ fontSize: 11, color: '#667085' }}>Total predicted demand</div>
                      </div>
                    </div>

                    {/* Stockout Alert */}
                    {skuData.stockout_alert && (
                      <div style={{
                        padding: '10px 14px', borderRadius: 10, marginBottom: 10,
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

                    {/* Forecast Chart — compact */}
                    <div style={{ padding: '12px 14px', borderRadius: 12, border: '1px solid #eaecf0', backgroundColor: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
                      <div style={{ marginBottom: 8, fontSize: 13, fontWeight: 700, color: '#1a1d1a', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#2563eb', display: 'inline-block' }} />
                        12-Week Forecast with Confidence Band
                        {skuData.stats?.cv != null && (
                          <span style={{ fontSize: 10, fontWeight: 500, color: '#667085', marginLeft: 4 }}>
                            (CV: {(skuData.stats.cv * 100).toFixed(0)}% — {skuData.stats.cv > 0.4 ? 'volatile' : skuData.stats.cv > 0.2 ? 'moderate' : 'stable'})
                          </span>
                        )}
                      </div>
                      <ResponsiveContainer width="100%" height={260}>
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
                            stroke="none" fill="#2563eb"
                            fillOpacity={Math.min(0.30, 0.05 + (skuData.stats?.cv || 0) * 0.4)}
                            legendType="none"
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

                    {/* Yearly Demand Chart */}
                    <div style={{ padding: '12px 14px', borderRadius: 12, border: '1px solid #eaecf0', backgroundColor: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.04)', marginTop: 10 }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#1a1d1a', display: 'flex', alignItems: 'center', gap: 6 }}>
                          <Calendar size={14} color="#175cd3" />
                          Demand History
                          {yearlyData?.total_units != null && (
                            <span style={{ fontSize: 11, fontWeight: 500, color: '#667085' }}>
                              — {yearlyData.total_units.toLocaleString()} units total
                            </span>
                          )}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <input
                            type="date"
                            value={dateFrom}
                            min={yearlyData?.min_date || ''}
                            max={dateTo || yearlyData?.max_date || ''}
                            onChange={(e) => setDateFrom(e.target.value)}
                            style={{ fontSize: 11, padding: '4px 8px', border: '1px solid #eaecf0', borderRadius: 6, color: '#344054', backgroundColor: '#fff' }}
                          />
                          <span style={{ fontSize: 11, color: '#667085' }}>to</span>
                          <input
                            type="date"
                            value={dateTo}
                            min={dateFrom || yearlyData?.min_date || ''}
                            max={yearlyData?.max_date || ''}
                            onChange={(e) => setDateTo(e.target.value)}
                            style={{ fontSize: 11, padding: '4px 8px', border: '1px solid #eaecf0', borderRadius: 6, color: '#344054', backgroundColor: '#fff' }}
                          />
                        </div>
                      </div>
                      {yearlyLoading ? (
                        <div style={{ padding: 30, textAlign: 'center', color: '#667085', fontSize: 12 }}>
                          <RefreshCw size={16} className="spin" style={{ marginRight: 6 }} />Loading demand data...
                        </div>
                      ) : yearlyData?.months?.length > 0 ? (
                        <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={yearlyData.months} margin={{ top: 8, right: 10, left: -15, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
                            <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#667085' }} />
                            <YAxis tick={{ fontSize: 10, fill: '#667085' }} />
                            <Tooltip
                              contentStyle={{ borderRadius: 10, fontSize: 12 }}
                              formatter={(value, name) => [value.toLocaleString(), name === 'units_sold' ? 'Units Sold' : name]}
                            />
                            <Bar dataKey="units_sold" name="Units Sold" fill="#2563eb" radius={[4, 4, 0, 0]} barSize={28} />
                          </BarChart>
                        </ResponsiveContainer>
                      ) : (
                        <div style={{ padding: 30, textAlign: 'center', color: '#667085', fontSize: 12 }}>
                          No demand data for selected date range
                        </div>
                      )}
                    </div>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {/* ═══════ TAB: PERFORMANCE DRILL-DOWN ═══════ */}
        {activeTab === 'model-drilldown' && <ModelDrilldown />}

        {/* ═══════ TAB 6: REORDER RECOMMENDATIONS ═══════ */}
        {activeTab === 'reorder' && (
          <div className="forecast-overview">
            {reorderLoading ? (
              <div className="loading"><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />Generating reorder recommendations...</div>
            ) : reorderData?.status === 'success' ? (
              <>
                {/* Summary KPIs — compact */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 14 }}>
                  <div style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                      <div style={{ width: 30, height: 30, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#fffaeb', color: '#b54708' }}><ShoppingCart size={16} /></div>
                    </div>
                    <div style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>SKUs Needing Reorder</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#b54708', lineHeight: 1.2 }}>{reorderData.total_recommendations}</div>
                    <div style={{ fontSize: 11, color: '#667085' }}>Coverage {'<'} 8 weeks</div>
                  </div>
                  <div style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                      <div style={{ width: 30, height: 30, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#ecfdf3', color: '#027a48' }}><DollarSign size={16} /></div>
                    </div>
                    <div style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Total Estimated Cost</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#1a1d1a', lineHeight: 1.2 }}>₹{formatINR(reorderData.total_estimated_cost_inr)}</div>
                    <div style={{ fontSize: 11, color: '#667085' }}>Reorder budget needed</div>
                  </div>
                  <div style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                      <div style={{ width: 30, height: 30, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#fef3f2', color: '#b42318' }}><AlertTriangle size={16} /></div>
                    </div>
                    <div style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Critical Urgency</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#b42318', lineHeight: 1.2 }}>
                      {reorderData.recommendations?.filter(r => r.urgency === 'CRITICAL').length || 0}
                    </div>
                    <div style={{ fontSize: 11, color: '#667085' }}>Order within 7 days</div>
                  </div>
                </div>

                {/* Recommendations Table */}
                <div className="card-table-container">
                  <div className="table-card-header">
                    <div className="table-card-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <ShoppingCart size={20} color="#b54708" />
                      Reorder Recommendations
                      <span style={{ fontSize: 12, color: '#667085', fontWeight: 400 }}>— based on 12-week demand forecast</span>
                      <span style={{ fontSize: 12, color: '#667085', fontWeight: 400, marginLeft: 'auto' }}>
                        Showing {(reorderPage - 1) * REORDER_PAGE_SIZE + 1}–{Math.min(reorderPage * REORDER_PAGE_SIZE, reorderData.total_recommendations)} of {reorderData.total_recommendations}
                      </span>
                    </div>
                  </div>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>S.No</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>SKU ID</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Category</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Forecast/Wk</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Est. Stock</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Coverage</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Lead Time</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Order By</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Qty</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Est. Cost</th>
                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Urgency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reorderData.recommendations?.slice((reorderPage - 1) * REORDER_PAGE_SIZE, reorderPage * REORDER_PAGE_SIZE).map((r, i) => (
                        <tr key={r.sku_id} style={r.urgency === 'CRITICAL' ? { backgroundColor: '#fef3f2' } : r.urgency === 'HIGH' ? { backgroundColor: '#fffaeb' } : {}}>
                          <td style={{ textAlign: 'center', color: '#667085', fontWeight: 500, fontSize: 11, padding: '6px 10px' }}>{(reorderPage - 1) * REORDER_PAGE_SIZE + i + 1}</td>
                          <td style={{ padding: '6px 10px' }}><strong style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.sku_id}</strong></td>
                          <td style={{ padding: '6px 10px' }}><span className={`badge-pill badge-${getCategoryBadge(r.category)}`} style={{ fontSize: 9, padding: '2px 8px' }}>{r.category}</span></td>
                          <td style={{ fontWeight: 600, fontSize: 11, padding: '6px 10px' }}>{r.forecast_weekly}</td>
                          <td style={{ fontWeight: 600, fontSize: 11, padding: '6px 10px' }}>{r.estimated_stock}</td>
                          <td style={{ padding: '6px 10px' }}>
                            <span style={{ fontWeight: 600, fontSize: 11, color: r.coverage_weeks < 4 ? '#dc2626' : r.coverage_weeks < 6 ? '#b54708' : '#1a1d1a' }}>
                              {r.coverage_weeks}w
                            </span>
                          </td>
                          <td style={{ fontSize: 11, padding: '6px 10px' }}>{r.lead_time_days}d</td>
                          <td style={{ padding: '6px 10px' }}>
                            <span style={{ fontWeight: 600, fontSize: 11, color: r.order_by_days_from_now <= 7 ? '#dc2626' : '#1a1d1a' }}>
                              {r.order_by_date}
                              {r.order_by_days_from_now <= 7 && <span style={{ fontSize: 9, color: '#dc2626', marginLeft: 4 }}>({r.order_by_days_from_now}d)</span>}
                            </span>
                          </td>
                          <td style={{ padding: '6px 10px' }}><strong style={{ fontSize: 11 }}>{r.qty_recommended}</strong></td>
                          <td style={{ fontWeight: 600, fontSize: 11, padding: '6px 10px' }}>₹{formatINR(r.estimated_cost_inr)}</td>
                          <td style={{ padding: '6px 10px' }}>
                            <span style={{
                              padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 700,
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
                  {/* Pagination */}
                  {reorderData.total_recommendations > REORDER_PAGE_SIZE && (
                    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, padding: '12px 16px', borderTop: '1px solid #eaecf0' }}>
                      <button
                        disabled={reorderPage === 1}
                        onClick={() => setReorderPage(p => p - 1)}
                        style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid #eaecf0', backgroundColor: reorderPage === 1 ? '#f9fafb' : '#fff', cursor: reorderPage === 1 ? 'default' : 'pointer', fontSize: 12, fontWeight: 600, color: reorderPage === 1 ? '#d0d5dd' : '#344054' }}
                      >
                        ← Prev
                      </button>
                      {Array.from({ length: Math.ceil(reorderData.total_recommendations / REORDER_PAGE_SIZE) }, (_, i) => i + 1)
                        .filter(p => p === 1 || p === Math.ceil(reorderData.total_recommendations / REORDER_PAGE_SIZE) || Math.abs(p - reorderPage) <= 2)
                        .reduce((acc, p, idx, arr) => {
                          if (idx > 0 && p - arr[idx - 1] > 1) acc.push('...');
                          acc.push(p);
                          return acc;
                        }, [])
                        .map((p, idx) => p === '...' ? (
                          <span key={`ellipsis-${idx}`} style={{ padding: '0 4px', fontSize: 12, color: '#667085' }}>…</span>
                        ) : (
                          <button
                            key={p}
                            onClick={() => setReorderPage(p)}
                            style={{ padding: '6px 10px', borderRadius: 6, border: reorderPage === p ? '1px solid #2563eb' : '1px solid #eaecf0', backgroundColor: reorderPage === p ? '#eff8ff' : '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: reorderPage === p ? '#2563eb' : '#344054' }}
                          >
                            {p}
                          </button>
                        ))
                      }
                      <button
                        disabled={reorderPage === Math.ceil(reorderData.total_recommendations / REORDER_PAGE_SIZE)}
                        onClick={() => setReorderPage(p => p + 1)}
                        style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid #eaecf0', backgroundColor: reorderPage === Math.ceil(reorderData.total_recommendations / REORDER_PAGE_SIZE) ? '#f9fafb' : '#fff', cursor: reorderPage === Math.ceil(reorderData.total_recommendations / REORDER_PAGE_SIZE) ? 'default' : 'pointer', fontSize: 12, fontWeight: 600, color: reorderPage === Math.ceil(reorderData.total_recommendations / REORDER_PAGE_SIZE) ? '#d0d5dd' : '#344054' }}
                      >
                        Next →
                      </button>
                    </div>
                  )}
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
