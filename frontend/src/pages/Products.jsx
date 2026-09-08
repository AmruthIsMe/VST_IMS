import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getProducts, createProduct, updateProduct, deleteProduct, getCategories, getStockoutRisk } from '../services/api';
import Header from '../components/Header';
import { Box, Layers, CheckCircle2, AlertTriangle, XCircle, Search, Plus, Eye, Pencil, Trash2, ArrowLeft, Package, Wrench, Droplets, Cog, Cpu, Settings2 } from 'lucide-react';

const EMPTY = { sku_id: '', category: 'Spare Parts', sub_category: '', machine_compatibility: '', shelf_life_days: '', unit_volume_m3: '' };

const CATEGORY_DATA = [
  {
    id: 'spare-parts',
    name: 'Spare Parts',
    icon: Wrench,
    gradient: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 100%)',
    iconBg: '#0284c7',
    description: 'Tractor & machinery spare components',
    subCategories: ['Bearings', 'Seals', 'Filters', 'Piston Kits', 'Gaskets'],
  },
  {
    id: 'electric-pumps',
    name: 'Electric Pumps',
    icon: Droplets,
    gradient: 'linear-gradient(135deg, #ecfdf3 0%, #a6f4c5 100%)',
    iconBg: '#12b76a',
    description: 'Irrigation & industrial pump systems',
    subCategories: ['Monoblock Pump', 'Domestic Pump', 'Centrifugal Pump', 'Submersible Pump'],
  },
  {
    id: 'lubricants',
    name: 'Lubricants',
    icon: Droplets,
    gradient: 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
    iconBg: '#d97706',
    description: 'Engine oils, greases & fluids',
    subCategories: ['Hydraulic Fluid', 'Grease', 'Engine Oil', 'Coolant'],
  },
  {
    id: 'engines',
    name: 'Engines',
    icon: Cog,
    gradient: 'linear-gradient(135deg, #f3e8ff 0%, #d8b4fe 100%)',
    iconBg: '#7e22ce',
    description: 'Complete engines & engine parts',
    subCategories: ['Pump Engine', 'Diesel Engine', 'Power Tiller Engine'],
  },
  {
    id: 'precision-components',
    name: 'Precision Components',
    icon: Cpu,
    gradient: 'linear-gradient(135deg, #ede9fe 0%, #c4b5fd 100%)',
    iconBg: '#6b21a8',
    description: 'High-precision CNC machined components',
    subCategories: ['Rotary Assembly', 'Valve Assembly', 'Locomotive Coupling', 'Precision Gear'],
  },
];

export default function Products({ onMenuToggle }) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState('products');
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data, isLoading } = useQuery({
    queryKey: ['products', page, search, catFilter],
    queryFn: () => getProducts({ page, page_size: 25, search, category: catFilter }).then(r => r.data),
  });

  const { data: cats } = useQuery({
    queryKey: ['categories'],
    queryFn: () => getCategories().then(r => r.data),
  });

  // Build a lookup map from API categories: { "Spare Parts": 80, ... }
  const categoryCountMap = useMemo(() => {
    const map = {};
    (cats || []).forEach((c) => { map[c.category] = c.count; });
    return map;
  }, [cats]);

  const { data: allProductsData } = useQuery({
    queryKey: ['products-all-for-kpi'],
    queryFn: async () => {
      const r1 = await getProducts({ page: 1, page_size: 100 });
      const total = r1.data.total;
      const pages = Math.ceil(total / 100);
      let items = [...r1.data.items];
      for (let p = 2; p <= pages; p++) {
        const r = await getProducts({ page: p, page_size: 100 });
        items = [...items, ...r.data.items];
      }
      return { items, total };
    },
  });

  const allProducts = allProductsData?.items || [];

  // Fetch forecast-based stockout risk (same data source as Dashboard)
  const { data: riskData } = useQuery({
    queryKey: ['stockout-risk'],
    queryFn: () => getStockoutRisk({ weeks_ahead: 12 }).then(r => r.data),
  });

  // Build risk lookup: { sku_id -> { risk_level, coverage_weeks, forecast_weekly, ... } }
  const riskMap = useMemo(() => {
    const map = {};
    (riskData?.risks || []).forEach(r => { map[r.sku_id] = r; });
    return map;
  }, [riskData]);

  // Fallback static thresholds for SKUs without forecast data
  const STOCK_THRESHOLDS = {
    'Spare Parts':          { low: 200, medium: 500 },
    'Lubricants':           { low: 150, medium: 400 },
    'Electric Pumps':       { low: 20,  medium: 50 },
    'Engines':              { low: 5,   medium: 15 },
    'Precision Components': { low: 10,  medium: 25 },
  };
  const getThresholds = (category) => STOCK_THRESHOLDS[category] || { low: 50, medium: 200 };

  // Forecast-based risk classification (matches Dashboard logic)
  const getRiskLevel = (p) => {
    const risk = riskMap[p.sku_id];
    if (risk) return risk.risk_level;
    // Fallback: static thresholds for SKUs without forecast data
    const stock = p.current_stock || 0;
    const t = getThresholds(p.category);
    if (stock < t.low) return 'CRITICAL';
    if (stock < t.medium) return 'HIGH';
    return 'LOW';
  };

  const statusMap = {
    Healthy: (p) => {
      const level = getRiskLevel(p);
      return level === 'LOW';
    },
    Low: (p) => {
      const level = getRiskLevel(p);
      return level === 'MEDIUM' || level === 'HIGH';
    },
    Critical: (p) => {
      const level = getRiskLevel(p);
      return level === 'CRITICAL';
    },
  };

  const filteredProducts = allProducts.filter((p) => {
    const matchesCategory = !catFilter || p.category === catFilter;
    const matchesStatus = !statusFilter || statusMap[statusFilter]?.(p);
    return matchesCategory && matchesStatus;
  });

  const totalSKUs = filteredProducts.length;
  const healthyCount = filteredProducts.filter(statusMap.Healthy).length;
  const lowCriticalCount = filteredProducts.filter(statusMap.Low).length;
  const criticalCount = filteredProducts.filter(statusMap.Critical).length;

  const PAGE_SIZE = 25;

  // When status filter is active, use allProducts (all items) with client-side pagination
  // When no filter, use server-side paginated data
  const { displayedItems, totalShowing } = useMemo(() => {
    if (statusFilter || catFilter) {
      const filtered = filteredProducts;
      const start = (page - 1) * PAGE_SIZE;
      return {
        displayedItems: filtered.slice(start, start + PAGE_SIZE),
        totalShowing: filtered.length,
      };
    }
    return {
      displayedItems: data?.items || [],
      totalShowing: data?.total || 0,
    };
  }, [data, filteredProducts, statusFilter, catFilter, page]);

  // Sub-category count lookup from allProducts
  const subCategoryCountMap = useMemo(() => {
    const map = {};
    allProducts.forEach((p) => {
      const key = `${p.category}::${p.sub_category}`;
      map[key] = (map[key] || 0) + 1;
    });
    return map;
  }, [allProducts]);

  const createMut = useMutation({
    mutationFn: (d) => createProduct(d),
    onSuccess: () => { qc.invalidateQueries(['products']); qc.invalidateQueries(['products-all-for-kpi']); qc.invalidateQueries(['categories']); setModal(null); },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...d }) => updateProduct(id, d),
    onSuccess: () => { qc.invalidateQueries(['products']); qc.invalidateQueries(['products-all-for-kpi']); qc.invalidateQueries(['categories']); setModal(null); },
  });

  const deleteMut = useMutation({
    mutationFn: (id) => deleteProduct(id),
    onSuccess: () => { qc.invalidateQueries(['products']); qc.invalidateQueries(['products-all-for-kpi']); qc.invalidateQueries(['categories']); },
  });

  const openCreate = () => { setForm(EMPTY); setModal('create'); };
  const openEdit = (p) => { setForm({ ...p, id: p.id }); setModal('edit'); };
  const handleSubmit = (e) => {
    e.preventDefault();
    if (modal === 'create') createMut.mutate(form);
    else updateMut.mutate(form);
  };

  const getCategoryClass = (cat) => {
    if (cat.includes('Spare')) return 'badge-spare';
    if (cat.includes('Pump')) return 'badge-pumps';
    if (cat.includes('Lubricant')) return 'badge-lubricants';
    if (cat.includes('Engine')) return 'badge-engines';
    return 'badge-precision';
  };

  const getStockColor = (p) => {
    const level = getRiskLevel(p);
    if (level === 'CRITICAL') return '#dc2626';
    if (level === 'HIGH') return '#d97706';
    if (level === 'MEDIUM') return '#2563eb';
    return '#16a34a';
  };

  const getStockBadge = (p) => {
    const level = getRiskLevel(p);
    if (level === 'CRITICAL') return <span className="badge-pill badge-critical">Critical</span>;
    if (level === 'HIGH') return <span className="badge-pill badge-low">High Risk</span>;
    if (level === 'MEDIUM') return <span className="badge-pill badge-low" style={{ backgroundColor: '#eff8ff', color: '#175cd3' }}>Medium</span>;
    return <span className="badge-pill badge-healthy">Healthy</span>;
  };

  const handleCategoryClick = (cat) => {
    setSelectedCategory(cat);
    setCatFilter(cat.name);
    setPage(1);
  };

  const handleBackToCategories = () => {
    setSelectedCategory(null);
    setCatFilter('');
  };

  const handleTabSwitch = (tab) => {
    setActiveTab(tab);
    if (tab === 'categories') {
      setSelectedCategory(null);
    }
  };

  return (
    <div>
      <Header onMenuToggle={onMenuToggle} />

      <div className="page-container">
        {/* Page Banner Title */}
        <div className="page-banner">
          <div className="page-banner-icon">
            <Box size={24} />
          </div>
          <h1 className="page-banner-title">Product Master Details</h1>
        </div>

        {/* Tabs */}
        <div className="page-tabs">
          <button
            className={`tab-btn ${activeTab === 'products' ? 'active' : ''}`}
            onClick={() => handleTabSwitch('products')}
          >
            <Box size={16} /> Products
          </button>
          <button
            className={`tab-btn ${activeTab === 'categories' ? 'active' : ''}`}
            onClick={() => handleTabSwitch('categories')}
          >
            <Layers size={16} /> Categories
          </button>
        </div>

        {/* ═══════ PRODUCTS TAB ═══════ */}
        {activeTab === 'products' && (
          <>
            {/* KPI Cards */}
            <div className="kpi-grid">
              <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
                <div className="kpi-icon-box kpi-icon-green">
                  <Box size={22} />
                </div>
                <div>
                  <div className="kpi-label">Total SKUs</div>
                  <div className="kpi-value">{totalSKUs}</div>
                </div>
              </div>

              <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
                <div className="kpi-icon-box kpi-icon-green">
                  <CheckCircle2 size={22} />
                </div>
                <div>
                  <div className="kpi-label">Healthy Stock</div>
                  <div className="kpi-value kpi-value-green">{healthyCount}</div>
                  <div className="kpi-sub" style={{ fontSize: 11, color: '#667085' }}>8+ weeks coverage</div>
                </div>
              </div>

              <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
                <div className="kpi-icon-box kpi-icon-orange">
                  <AlertTriangle size={22} />
                </div>
                <div>
                  <div className="kpi-label">At Risk</div>
                  <div className="kpi-value kpi-value-orange">{lowCriticalCount}</div>
                  <div className="kpi-sub" style={{ fontSize: 11, color: '#667085' }}>4-8 weeks coverage</div>
                </div>
              </div>

              <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
                <div className="kpi-icon-box kpi-icon-red">
                  <XCircle size={22} />
                </div>
                <div>
                  <div className="kpi-label">Critical</div>
                  <div className="kpi-value kpi-value-red">{criticalCount}</div>
                  <div className="kpi-sub" style={{ fontSize: 11, color: '#667085' }}>&lt;4 weeks coverage</div>
                </div>
              </div>
            </div>

            {/* Toolbar & Add Button */}
            <div className="toolbar-card">
              <div className="toolbar-left">
                <div className="search-wrapper">
                  <Search className="search-icon" size={16} />
                  <input
                    className="search-input"
                    placeholder="Search SKU or name..."
                    value={search}
                    onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                  />
                </div>

                <select className="filter-select" value={catFilter} onChange={(e) => { setCatFilter(e.target.value); setPage(1); }}>
                  <option value="">All Categories</option>
                  {(cats || []).map((c) => (
                    <option key={c.category} value={c.category}>{c.category}</option>
                  ))}
                </select>

                <select className="filter-select" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
                  <option value="">All Risk Levels</option>
                  <option value="Healthy">Healthy (8+ wk)</option>
                  <option value="Low">At Risk (4-8 wk)</option>
                  <option value="Critical">Critical (&lt;4 wk)</option>
                </select>
              </div>

              <button className="btn-primary" onClick={openCreate}>
                <Plus size={18} /> Add Product
              </button>
            </div>

            {/* Table Card */}
            <div className="card-table-container">
              <div className="table-card-header">
                <div className="table-card-title">Product Master List</div>
                <div className="showing-count">
                  Showing <strong>{displayedItems.length}</strong> of <strong>{totalShowing}</strong> SKUs
                  {statusFilter && <span style={{ color: '#6366f1', marginLeft: 8 }}>(filtered by {statusFilter})</span>}
                </div>
              </div>

              {isLoading ? <div className="loading">Loading products...</div> : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: 60 }}>SL NO</th>
                      <th>SKU ID</th>
                      <th>Category</th>
                      <th>Sub-Category</th>
                      <th>Machine Compatibility</th>
                      <th>Shelf Life</th>
                      <th>Volume (m³)</th>
                      <th>Current Stock</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayedItems.map((p, idx) => (
                      <tr key={p.id}>
                        <td style={{ color: '#94a3b8', fontWeight: 600 }}>{(page - 1) * PAGE_SIZE + idx + 1}</td>
                        <td style={{ fontWeight: 600, color: '#334155' }}>{p.sku_id}</td>
                        <td>
                          <span className={`badge-pill ${getCategoryClass(p.category)}`}>
                            {p.category}
                          </span>
                        </td>
                        <td style={{ fontWeight: 600 }}>{p.sub_category || '—'}</td>
                        <td style={{ color: '#475569', fontSize: 13, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.machine_compatibility || '—'}
                        </td>
                        <td style={{ color: '#64748b' }}>
                          {p.shelf_life_days ? `${p.shelf_life_days} days` : '—'}
                        </td>
                        <td style={{ color: '#64748b', fontFamily: 'monospace' }}>
                          {p.unit_volume_m3 != null ? p.unit_volume_m3.toFixed(4) : '—'}
                        </td>
                        <td style={{ fontWeight: 600, fontFamily: 'monospace', color: getStockColor(p) }}>
                          {p.current_stock != null ? p.current_stock.toLocaleString('en-IN') : '—'}
                        </td>
                        <td>{getStockBadge(p)}</td>
                        <td>
                          <div className="action-buttons">
                            <button className="act-btn act-view"><Eye size={13} /> View</button>
                            <button className="act-btn act-edit" onClick={() => openEdit(p)}><Pencil size={13} /> Edit</button>
                            <button className="act-btn act-delete" onClick={() => { if (confirm('Delete?')) deleteMut.mutate(p.id); }}><Trash2 size={13} /> Delete</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {(() => {
                const totalPages = Math.ceil(totalShowing / PAGE_SIZE);
                if (totalPages <= 1) return null;
                return (
                  <div className="pagination-container">
                    <button className="page-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
                    {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => i + 1).map((p) => (
                      <button key={p} className={`page-btn ${p === page ? 'active' : ''}`} onClick={() => setPage(p)}>{p}</button>
                    ))}
                    <button className="page-btn" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button>
                  </div>
                );
              })()}
            </div>
          </>
        )}

        {/* ═══════ CATEGORIES TAB ═══════ */}
        {activeTab === 'categories' && !selectedCategory && (
          <>
            {/* Section Title */}
            <div className="categories-section-header">
              <Package size={24} color="var(--primary)" />
              <div>
                <h2 className="categories-section-title">Our Product Range</h2>
                <p className="categories-section-subtitle">Click a category to explore sub-categories and products</p>
              </div>
            </div>

            {/* Category Cards Grid */}
            <div className="category-cards-grid">
              {CATEGORY_DATA.map((cat) => {
                const Icon = cat.icon;
                const count = categoryCountMap[cat.name] || 0;
                return (
                  <div
                    key={cat.id}
                    className="category-card"
                    onClick={() => handleCategoryClick(cat)}
                    style={{ background: cat.gradient }}
                  >
                    <div className="category-card-inner">
                      <div className="category-card-icon" style={{ backgroundColor: cat.iconBg }}>
                        <Icon size={32} color="#fff" />
                      </div>
                      <div className="category-card-content">
                        <h3 className="category-card-name">{cat.name}</h3>
                        <p className="category-card-desc">{cat.description}</p>
                        <div className="category-card-count">
                          <Package size={14} />
                          <span>{count} products</span>
                        </div>
                      </div>
                      <div className="category-card-arrow">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* ═══════ SUB-CATEGORY VIEW ═══════ */}
        {activeTab === 'categories' && selectedCategory && (
          <>
            {/* Back Navigation */}
            <button className="category-back-btn" onClick={handleBackToCategories}>
              <ArrowLeft size={18} />
              Back to Categories
            </button>

            {/* Category Header */}
            <div className="category-detail-header" style={{ background: selectedCategory.gradient }}>
              <div className="category-detail-icon" style={{ backgroundColor: selectedCategory.iconBg }}>
                {(() => { const Icon = selectedCategory.icon; return <Icon size={36} color="#fff" />; })()}
              </div>
              <div>
                <h2 className="category-detail-name">{selectedCategory.name}</h2>
                <p className="category-detail-desc">{selectedCategory.description}</p>
                <span className="category-detail-count">{categoryCountMap[selectedCategory.name] || 0} products</span>
              </div>
            </div>

            {/* Sub-Categories Grid */}
            <div className="subcategories-section-header">
              <Layers size={20} color="var(--primary)" />
              <h3>Sub-Categories</h3>
            </div>
            <div className="subcategory-grid">
              {selectedCategory.subCategories.map((sub, idx) => {
                const subCount = subCategoryCountMap[`${selectedCategory.name}::${sub}`] || 0;
                return (
                  <div key={idx} className="subcategory-card" onClick={() => { setActiveTab('products'); setCatFilter(selectedCategory.name); }}>
                    <div className="subcategory-icon-box" style={{ backgroundColor: selectedCategory.iconBg + '20', color: selectedCategory.iconBg }}>
                      <Settings2 size={20} />
                    </div>
                    <div className="subcategory-info">
                      <h4 className="subcategory-name">{sub}</h4>
                      <p className="subcategory-meta">{subCount} SKUs</p>
                    </div>
                    <div className="subcategory-arrow">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="9 18 15 12 9 6"></polyline>
                      </svg>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{modal === 'create' ? 'Add Product' : 'Edit Product'}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>SKU ID</label><input value={form.sku_id} onChange={(e) => setForm({ ...form, sku_id: e.target.value })} required disabled={modal === 'edit'} /></div>
              <div className="form-group"><label>Category</label><input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} required /></div>
              <div className="form-group"><label>Sub-Category</label><input value={form.sub_category || ''} onChange={(e) => setForm({ ...form, sub_category: e.target.value })} /></div>
              <div className="form-group"><label>Machine Compatibility</label><input value={form.machine_compatibility || ''} onChange={(e) => setForm({ ...form, machine_compatibility: e.target.value })} /></div>
              <div className="modal-actions">
                <button type="button" className="btn-cancel" onClick={() => setModal(null)}>Cancel</button>
                <button type="submit" className="btn-primary">Save Product</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
