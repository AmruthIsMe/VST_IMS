import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getUsers, createUser, updateUser, deleteUser } from '../services/api';
import Header from '../components/Header';
import { Users as UsersIcon, Search, Plus, Pencil, Trash2 } from 'lucide-react';

const EMPTY = { user_id: '', name: '', email: '', password: '', role: 'Viewer' };

export default function Users({ onMenuToggle }) {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data, isLoading } = useQuery({
    queryKey: ['users', page, search, roleFilter],
    queryFn: () => getUsers({ page, page_size: 15, search, role: roleFilter }).then((r) => r.data),
  });

  const createMut = useMutation({ mutationFn: createUser, onSuccess: () => { qc.invalidateQueries(['users']); setModal(null); } });
  const updateMut = useMutation({ mutationFn: ({ id, ...d }) => updateUser(id, d), onSuccess: () => { qc.invalidateQueries(['users']); setModal(null); } });
  const deleteMut = useMutation({ mutationFn: deleteUser, onSuccess: () => qc.invalidateQueries(['users']) });

  const openCreate = () => { setForm(EMPTY); setModal('create'); };
  const openEdit = (u) => { setForm({ ...u, password: '', id: u.id }); setModal('edit'); };
  const handleSubmit = (e) => { e.preventDefault(); modal === 'create' ? createMut.mutate(form) : updateMut.mutate(form); };

  return (
    <div>
      <Header onMenuToggle={onMenuToggle} />

      <div className="page-container">
        <div className="page-banner">
          <div className="page-banner-icon">
            <UsersIcon size={24} />
          </div>
          <h1 className="page-banner-title">User Administration</h1>
        </div>

        <div className="toolbar-card">
          <div className="toolbar-left">
            <div className="search-wrapper">
              <Search className="search-icon" size={16} />
              <input
                className="search-input"
                placeholder="Search users..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              />
            </div>

            <select className="filter-select" value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}>
              <option value="">All Roles</option>
              <option value="Admin">Admin</option>
              <option value="Store Manager">Store Manager</option>
              <option value="Cashier">Cashier</option>
              <option value="Viewer">Viewer</option>
            </select>
          </div>

          <button className="btn-primary" onClick={openCreate}>
            <Plus size={18} /> Add User
          </button>
        </div>

        <div className="card-table-container">
          <div className="table-card-header">
            <div className="table-card-title">User Directory</div>
            <div className="showing-count">
              Showing <strong>{data?.items?.length || 0}</strong> users
            </div>
          </div>

          {isLoading ? <div className="loading">Loading users...</div> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>User ID</th>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last Login</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items || []).map((u) => (
                  <tr key={u.id}>
                    <td style={{ fontWeight: 700 }}>{u.user_id}</td>
                    <td style={{ fontWeight: 600 }}>{u.name}</td>
                    <td>{u.email}</td>
                    <td>
                      <span className="badge-pill badge-spare">{u.role}</span>
                    </td>
                    <td>
                      <span className={`badge-pill ${u.status === 'Active' ? 'badge-healthy' : 'badge-critical'}`}>
                        {u.status}
                      </span>
                    </td>
                    <td style={{ color: '#64748b' }}>
                      {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button className="act-btn act-edit" onClick={() => openEdit(u)}><Pencil size={13} /> Edit</button>
                        <button className="act-btn act-delete" onClick={() => { if (confirm('Delete?')) deleteMut.mutate(u.id); }}><Trash2 size={13} /> Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{modal === 'create' ? 'Add User' : 'Edit User'}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>User ID</label><input value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })} required disabled={modal === 'edit'} /></div>
              <div className="form-group"><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></div>
              <div className="form-group"><label>Email</label><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></div>
              {modal === 'create' && <div className="form-group"><label>Password</label><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></div>}
              <div className="form-group"><label>Role</label>
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option>Admin</option>
                  <option>Store Manager</option>
                  <option>Cashier</option>
                  <option>Viewer</option>
                </select>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn-cancel" onClick={() => setModal(null)}>Cancel</button>
                <button type="submit" className="btn-primary">Save User</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
