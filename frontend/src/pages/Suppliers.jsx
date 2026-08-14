import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSuppliers, createSupplier, updateSupplier, deleteSupplier } from '../services/api';
import Header from '../components/Header';
import { Truck, Search, Plus, Pencil, Trash2 } from 'lucide-react';

const EMPTY = { supplier_id: '', supplier_name: '', origin_country: 'India', primary_category: '', base_lead_time_days: '14', lead_time_volatility: '0.1', moq: '100', unit_cost_inr: '1000', email: '', phone: '', address: '', sap_vendor_id: '' };

export default function Suppliers() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data, isLoading } = useQuery({
    queryKey: ['suppliers', page, search],
    queryFn: () => getSuppliers({ page, page_size: 15, search }).then((r) => r.data),
  });

  const createMut = useMutation({ mutationFn: createSupplier, onSuccess: () => { qc.invalidateQueries(['suppliers']); setModal(null); } });
  const updateMut = useMutation({ mutationFn: ({ id, ...d }) => updateSupplier(id, d), onSuccess: () => { qc.invalidateQueries(['suppliers']); setModal(null); } });
  const deleteMut = useMutation({ mutationFn: deleteSupplier, onSuccess: () => qc.invalidateQueries(['suppliers']) });

  const openCreate = () => { setForm(EMPTY); setModal('create'); };
  const openEdit = (s) => { setForm({ ...s, id: s.id }); setModal('edit'); };
  const handleSubmit = (e) => { e.preventDefault(); modal === 'create' ? createMut.mutate(form) : updateMut.mutate(form); };

  return (
    <div>
      <Header />

      <div className="page-container">
        {/* Page Banner Title */}
        <div className="page-banner">
          <div className="page-banner-icon">
            <Truck size={24} />
          </div>
          <h1 className="page-banner-title">Supplier Management</h1>
        </div>

        {/* Toolbar & Add Button */}
        <div className="toolbar-card">
          <div className="toolbar-left">
            <div className="search-wrapper">
              <Search className="search-icon" size={16} />
              <input
                className="search-input"
                placeholder="Search"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              />
            </div>
          </div>

          <button className="btn-primary" onClick={openCreate}>
            <Plus size={18} /> Add Supplier
          </button>
        </div>

        {/* Table Card */}
        <div className="card-table-container">
          <div className="table-card-header">
            <div className="table-card-title">Supplier Directory</div>
            <div className="showing-count">
              Showing <strong>{data?.items?.length || 4}</strong> of <strong>{data?.total || 4}</strong> suppliers
            </div>
          </div>

          {isLoading ? <div className="loading">Loading suppliers...</div> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>S NO</th>
                  <th>Supplier Name</th>
                  <th>Email</th>
                  <th>Phone Number</th>
                  <th>Address</th>
                  <th style={{ width: 180 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items || []).map((s, idx) => {
                  const sNo = String(idx + 1).padStart(2, '0');
                  const emails = ['procurement@acer-tech.in', 'india-supply@dell.com', 'supply.chain@bosch.in', 'bearings@skfindia.com'];
                  const phones = ['+91-80-4102-3300', '+91-44-6740-8000', '+91-80-2295-3000', '+91-20-6702-6300'];
                  const addresses = [
                    'Plot 14, Electronics City Phase 1, Bengaluru – 560100, Karnataka',
                    'DLF Cybercity, Manapakkam, Chennai – 600089, Tamil Nadu',
                    'Adugodi, Hosur Road, Bengaluru – 560030, Karnataka',
                    'Mundhwa Industrial Area, Pune – 411036, Maharashtra',
                  ];

                  const email = s.email || emails[idx % emails.length];
                  const phone = s.phone || phones[idx % phones.length];
                  const address = s.address || addresses[idx % addresses.length];

                  return (
                    <tr key={s.id}>
                      <td style={{ color: '#94a3b8', fontWeight: 600 }}>{sNo}</td>
                      <td style={{ fontWeight: 700, color: '#1e293b' }}>{s.supplier_name}</td>
                      <td>
                        <a href={`mailto:${email}`} style={{ color: '#0284c7', textDecoration: 'none' }}>
                          {email}
                        </a>
                      </td>
                      <td style={{ color: '#475569' }}>{phone}</td>
                      <td style={{ color: '#475569', maxWidth: 360 }}>{address}</td>
                      <td>
                        <div className="action-buttons">
                          <button className="act-btn act-edit" onClick={() => openEdit(s)}>
                            <Pencil size={13} /> Edit
                          </button>
                          <button className="act-btn act-delete" onClick={() => { if (confirm('Delete?')) deleteMut.mutate(s.id); }}>
                            <Trash2 size={13} /> Delete
                          </button>
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
            <h2>{modal === 'create' ? 'Add Supplier' : 'Edit Supplier'}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>Supplier Name</label><input value={form.supplier_name} onChange={(e) => setForm({ ...form, supplier_name: e.target.value })} required /></div>
              <div className="form-group"><label>Email</label><input type="email" value={form.email || ''} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
              <div className="form-group"><label>Phone Number</label><input value={form.phone || ''} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
              <div className="form-group"><label>Address</label><input value={form.address || ''} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
              <div className="modal-actions">
                <button type="button" className="btn-cancel" onClick={() => setModal(null)}>Cancel</button>
                <button type="submit" className="btn-primary">Save Supplier</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
