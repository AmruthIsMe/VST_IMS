import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getProducts, createProduct, updateProduct, deleteProduct, getCategories } from '../services/api';
import Header from '../components/Header';
import { Box, Layers, CheckCircle2, AlertTriangle, XCircle, Search, Plus, Eye, Pencil, Trash2 } from 'lucide-react';

const EMPTY = { sku_id: '', category: 'Spare Parts', sub_category: '', machine_compatibility: '', shelf_life_days: '', unit_volume_m3: '', criticality_score: '0.5' };

export default function Products() {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState('products');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('');
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

  const createMut = useMutation({
    mutationFn: (d) => createProduct(d),
    onSuccess: () => { qc.invalidateQueries(['products']); setModal(null); },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...d }) => updateProduct(id, d),
    onSuccess: () => { qc.invalidateQueries(['products']); setModal(null); },
  });

  const deleteMut = useMutation({
    mutationFn: (id) => deleteProduct(id),
    onSuccess: () => qc.invalidateQueries(['products']),
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

  const getStatusBadge = (score, idx) => {
    // Determine realistic demo statuses based on index or criticality
    if (idx % 4 === 0) return <span className="badge-pill badge-healthy">Healthy</span>;
    if (idx % 4 === 1) return <span className="badge-pill badge-critical">Critical</span>;
    if (idx % 4 === 2) return <span className="badge-pill badge-out">Out of Stock</span>;
    return <span className="badge-pill badge-low">Low Stock</span>;
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
            onClick={() => setActiveTab('products')}
          >
            <Box size={16} /> Products
          </button>
          <button
            className={`tab-btn ${activeTab === 'categories' ? 'active' : ''}`}
            onClick={() => setActiveTab('categories')}
          >
            <Layers size={16} /> Categories
          </button>
        </div>

        {/* KPI Cards */}
        <div className="kpi-grid">
          <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
            <div className="kpi-icon-box kpi-icon-green">
              <Box size={22} />
            </div>
            <div>
              <div className="kpi-label">Total SKUs</div>
              <div className="kpi-value">{data?.total ?? 200}</div>
            </div>
          </div>

          <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
            <div className="kpi-icon-box kpi-icon-green">
              <CheckCircle2 size={22} />
            </div>
            <div>
              <div className="kpi-label">Healthy Stock</div>
              <div className="kpi-value kpi-value-green">142</div>
            </div>
          </div>

          <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
            <div className="kpi-icon-box kpi-icon-orange">
              <AlertTriangle size={22} />
            </div>
            <div>
              <div className="kpi-label">Low / Critical</div>
              <div className="kpi-value kpi-value-orange">52</div>
            </div>
          </div>

          <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
            <div className="kpi-icon-box kpi-icon-red">
              <XCircle size={22} />
            </div>
            <div>
              <div className="kpi-label">Out of Stock</div>
              <div className="kpi-value kpi-value-red">6</div>
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

            <select className="filter-select">
              <option value="">All Suppliers</option>
              <option value="Bosch">Bosch Limited</option>
              <option value="Acer">Acer Technologies</option>
              <option value="Dell">Dell International</option>
              <option value="SKF">SKF India</option>
            </select>

            <select className="filter-select">
              <option value="">All Statuses</option>
              <option value="Healthy">Healthy</option>
              <option value="Critical">Critical</option>
              <option value="Out of Stock">Out of Stock</option>
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
              Showing <strong>{data?.items?.length || 0}</strong> of <strong>{data?.total || 0}</strong> SKUs
            </div>
          </div>

          {isLoading ? <div className="loading">Loading products...</div> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>SKU / Barcode</th>
                  <th>Product Name</th>
                  <th>Category</th>
                  <th>Supplier</th>
                  <th>Cost ₹</th>
                  <th>Sell ₹</th>
                  <th>Qty</th>
                  <th>Reorder</th>
                  <th>Expiry</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items || []).map((p, idx) => {
                  const qty = idx === 2 ? 0 : idx === 1 ? 8 : idx === 4 ? 18 : 145;
                  const reorder = 20;
                  const cost = idx === 3 ? '28,000' : idx === 1 ? '4,200' : '480';
                  const sell = idx === 3 ? '36,500' : idx === 1 ? '5,800' : '650';
                  const suppliers = ['Bosch Limited', 'Acer Technologies', 'Dell International', 'SKF India'];
                  const supplierName = suppliers[idx % suppliers.length];

                  return (
                    <tr key={p.id}>
                      <td style={{ fontWeight: 600, color: '#334155' }}>{p.sku_id}</td>
                      <td style={{ fontWeight: 700 }}>{p.sub_category || p.category}</td>
                      <td>
                        <span className={`badge-pill ${getCategoryClass(p.category)}`}>
                          {p.category}
                        </span>
                      </td>
                      <td style={{ color: '#475569' }}>{supplierName}</td>
                      <td>₹{cost}</td>
                      <td style={{ fontWeight: 700 }}>₹{sell}</td>
                      <td style={{ fontWeight: 700, color: qty === 0 ? '#dc2626' : qty < reorder ? '#d97706' : '#1e293b' }}>
                        {qty}
                      </td>
                      <td style={{ color: '#64748b' }}>{reorder}</td>
                      <td style={{ color: '#64748b', fontSize: 12 }}>
                        {idx % 2 === 0 ? '2027-06-30' : 'N/A'}
                      </td>
                      <td>{getStatusBadge(p.criticality_score, idx)}</td>
                      <td>
                        <div className="action-buttons">
                          <button className="act-btn act-view"><Eye size={13} /> View</button>
                          <button className="act-btn act-edit" onClick={() => openEdit(p)}><Pencil size={13} /> Edit</button>
                          <button className="act-btn act-delete" onClick={() => { if (confirm('Delete?')) deleteMut.mutate(p.id); }}><Trash2 size={13} /> Delete</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
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
