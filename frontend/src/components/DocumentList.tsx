import { useState, useEffect, useCallback } from 'react'
import { formatDateForDisplay } from '../utils/dateUtils'
import { FileText, Plus, Trash2, Download, Edit3, Save, X } from 'lucide-react'
import { toast } from 'sonner'
import api from '../services/api'
import type { Document } from '../types/document'

interface DocumentListProps {
  vin: string
  onAddClick: () => void
}

export default function DocumentList({ vin, onAddClick }: DocumentListProps) {
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editData, setEditData] = useState<{
    title: string
    document_type: string
    description: string
  }>({ title: '', document_type: '', description: '' })

  const fetchDocuments = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/documents`)
      setDocuments(response.data.documents)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchDocuments().finally(() => setLoading(false))
  }, [fetchDocuments])

  const handleDelete = async (documentId: number) => {
    if (!confirm('Are you sure you want to delete this document?')) {
      return
    }

    setDeletingId(documentId)
    try {
      await api.delete(`/vehicles/${vin}/documents/${documentId}`)
      await fetchDocuments()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete document')
    } finally {
      setDeletingId(null)
    }
  }

  const handleDownload = async (documentId: number, fileName: string) => {
    try {
      const response = await api.get(`/vehicles/${vin}/documents/${documentId}/download`, {
        responseType: 'blob',
      })

      const url = window.URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = fileName
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to download document')
    }
  }

  const startEdit = (doc: Document) => {
    setEditingId(doc.id)
    setEditData({
      title: doc.title,
      document_type: doc.document_type || '',
      description: doc.description || '',
    })
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditData({ title: '', document_type: '', description: '' })
  }

  const saveEdit = async (documentId: number) => {
    try {
      await api.put(`/vehicles/${vin}/documents/${documentId}`, editData)
      await fetchDocuments()
      setEditingId(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update document')
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const formatDate = (dateString: string): string => {
    return formatDateForDisplay(dateString)
  }

  const getFileIcon = (mimeType: string) => {
    if (mimeType.startsWith('image/')) {
      return '🖼️'
    } else if (mimeType === 'application/pdf') {
      return '📄'
    } else if (mimeType.includes('word')) {
      return '📝'
    } else if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) {
      return '📊'
    }
    return '📎'
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading documents...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">
            Documents
          </h3>
          <span className="text-sm text-garage-text-muted">({documents.length} files)</span>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Upload Document</span>
        </button>
      </div>

      {documents.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <FileText className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No documents yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Upload important vehicle documents like insurance, registration, manuals, and receipts
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gabtn-primary transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Upload First Document</span>
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="bg-garage-surface border border-garage-border rounded-lg p-4 hover:border-primary/50 transition-colors"
            >
              {editingId === doc.id ? (
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      Title
                    </label>
                    <input
                      type="text"
                      value={editData.title}
                      onChange={(e) => setEditData({ ...editData, title: e.target.value })}
                      className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      Type
                    </label>
                    <select
                      value={editData.document_type}
                      onChange={(e) => setEditData({ ...editData, document_type: e.target.value })}
                      className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                    >
                      <option value="" className="bg-garage-bg text-garage-text">Select type</option>
                      <option value="Insurance" className="bg-garage-bg text-garage-text">Insurance</option>
                      <option value="Registration" className="bg-garage-bg text-garage-text">Registration</option>
                      <option value="Manual" className="bg-garage-bg text-garage-text">Manual</option>
                      <option value="Receipt" className="bg-garage-bg text-garage-text">Receipt</option>
                      <option value="Inspection" className="bg-garage-bg text-garage-text">Inspection</option>
                      <option value="Other" className="bg-garage-bg text-garage-text">Other</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      Description
                    </label>
                    <textarea
                      value={editData.description}
                      onChange={(e) => setEditData({ ...editData, description: e.target.value })}
                      rows={2}
                      className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => saveEdit(doc.id)}
                      className="flex items-center gap-1 px-3 py-1 bg-primary text-white rounded-md hover:bg-primary-dark text-sm"
                    >
                      <Save className="w-3 h-3" />
                      Save
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="flex items-center gap-1 px-3 py-1 bg-gray-700 border border-gray-600 text-white rounded-md hover:bg-gray-800 text-sm"
                    >
                      <X className="w-3 h-3" />
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-4">
                  <div className="text-3xl flex-shrink-0">
                    {getFileIcon(doc.mime_type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <h4 className="text-garage-text font-medium truncate">{doc.title}</h4>
                        <p className="text-sm text-garage-text-muted truncate">{doc.file_name}</p>
                      </div>
                      {doc.document_type && (
                        <span className="px-2 py-1 bg-primary/20 text-primary text-xs rounded flex-shrink-0">
                          {doc.document_type}
                        </span>
                      )}
                    </div>
                    {doc.description && (
                      <p className="text-sm text-garage-text-muted mt-2">{doc.description}</p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-garage-text-muted">
                      <span>{formatFileSize(doc.file_size)}</span>
                      <span>Uploaded {formatDate(doc.uploaded_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button
                      onClick={() => handleDownload(doc.id, doc.file_name)}
                      className="p-2 text-primary hover:bg-primary/10 rounded-full"
                      title="Download"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => startEdit(doc)}
                      className="p-2 text-garage-text-muted hover:bg-garage-bg rounded-full"
                      title="Edit"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(doc.id)}
                      disabled={deletingId === doc.id}
                      className="p-2 text-danger hover:bg-danger/10 rounded-full disabled:opacity-50"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
