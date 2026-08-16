import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getProducts, createProduct, updateProduct, deleteProduct, getCategories } from '../services/api';
import Header from '../components/Header';
import { Box, Layers, CheckCircle2, AlertTriangle, XCircle, Search, Plus, Eye, Pencil, Trash2, ArrowLeft, Package, Wrench, Droplets, Cog, Cpu, Settings2 } from 'lucide-react';

const EMPTY = { sku_id: '', category: 'Spare Parts', sub_category: '', machine_compatibility: '', shelf_life_days: '', unit_volume_m3: '', criticality_score: '0.5' };

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

export default function Products() {
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
    queryFn: () => getProducts({ page, page_size: 15, search, category: catFilter }).then(r => r.data),
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

  // Status classification based on criticality_score (1-5 scale):
  //   1-2 = Healthy, 3-4 = Low Stock, 5 = Critical
  const statusMap = {
    Healthy: (p) => p.criticality_score == null || p.criticality_score < 3,
    Low: (p) => p.criticality_score != null && p.criticality_score >= 3 && p.criticality_score < 5,
    Critical: (p) => p.criticality_score != null && p.criticality_score >= 5,
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

  // Also apply status filter to the table items (client-side since backend doesn't support status filter)
  const displayedItems = useMemo(() => {
    const items = data?.items || [];
    if (!statusFilter) return items;
    return items.filter((p) => statusMap[statusFilter]?.(p));
  }, [data?.items, statusFilter]);

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

  const getStatusBadge = (score) => {
    if (score == null) return <span className="badge-pill badge-healthy">Healthy</span>;
    if (score >= 5) return <span className="badge-pill badge-critical">Critical</span>;
    if (score >= 3) return <span className="badge-pill badge-low">Low Stock</span>;
    return <span className="badge-pill badge-healthy">Healthy</span>;
  };

  const getCriticalityLabel = (score) => {
    if (score == null) return '—';
    if (score <= 2) return `${score} — Low`;
    if (score <= 4) return `${score} — Medium`;
    return `${score} — High`;
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
      <Header />

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
                </div>
              </div>

              <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
                <div className="kpi-icon-box kpi-icon-orange">
                  <AlertTriangle size={22} />
                </div>
                <div>
                  <div className="kpi-label">Low Stock</div>
                  <div className="kpi-value kpi-value-orange">{lowCriticalCount}</div>
                </div>
              </div>

              <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
                <div className="kpi-icon-box kpi-icon-red">
                  <XCircle size={22} />
                </div>
                <div>
                  <div className="kpi-label">Critical</div>
                  <div className="kpi-value kpi-value-red">{criticalCount}</div>
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
                  <option value="">All Statuses</option>
                  <option value="Healthy">Healthy (Score 1–2)</option>
                  <option value="Low">Low Stock (Score 3–4)</option>
                  <option value="Critical">Critical (Score 5)</option>
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
                  Showing <strong>{displayedItems.length}</strong> of <strong>{data?.total || 0}</strong> SKUs
                  {statusFilter && <span style={{ color: '#6366f1', marginLeft: 8 }}>(filtered by {statusFilter})</span>}
                </div>
              </div>

              {isLoading ? <div className="loading">Loading products...</div> : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>SKU ID</th>
                      <th>Category</th>
                      <th>Sub-Category</th>
                      <th>Machine Compatibility</th>
                      <th>Shelf Life</th>
                      <th>Volume (m³)</th>
                      <th>Criticality</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayedItems.map((p) => (
                      <tr key={p.id}>
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
                        <td style={{ fontWeight: 600, color: p.criticality_score >= 5 ? '#dc2626' : p.criticality_score >= 3 ? '#d97706' : '#16a34a' }}>
                          {getCriticalityLabel(p.criticality_score)}
                        </td>
                        <td>{getStatusBadge(p.criticality_score)}</td>
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

              {data && data.total_pages > 1 && (
                <div className="pagination-container">
                  <button className="page-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
                  {Array.from({ length: Math.min(data.total_pages, 5) }, (_, i) => i + 1).map((p) => (
                    <button key={p} className={`page-btn ${p === page ? 'active' : ''}`} onClick={() => setPage(p)}>{p}</button>
                  ))}
                  <button className="page-btn" disabled={page >= data.total_pages} onClick={() => setPage(page + 1)}>Next</button>
                </div>
              )}
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
