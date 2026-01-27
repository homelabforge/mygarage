import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Download,
  Upload,
  AlertCircle,
  CheckCircle,
  Database,
  HardDrive,
  Trash2,
  RefreshCw,
  FileJson,
  Archive,
} from 'lucide-react'
import api from '@/services/api'

interface BackupFile {
  filename: string
  type: 'settings' | 'full'
  size_mb: number
  created: string
  is_safety: boolean
}

interface BackupStats {
  database: {
    size_mb: number
    last_modified: string
    exists: boolean
  }
  settings_backups: {
    count: number
    total_size_mb: number
  }
  full_backups: {
    count: number
    total_size_mb: number
  }
}

export default function SettingsBackupTab() {
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<BackupStats | null>(null)
  const [settingsBackups, setSettingsBackups] = useState<BackupFile[]>([])
  const [fullBackups, setFullBackups] = useState<BackupFile[]>([])
  const [creatingSettings, setCreatingSettings] = useState(false)
  const [creatingFull, setCreatingFull] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null)
  const settingsFileInputRef = useRef<HTMLInputElement>(null)
  const fullFileInputRef = useRef<HTMLInputElement>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      // Load stats
      const statsResponse = await api.get('/backup/stats')
      setStats(statsResponse.data)

      // Load backups
      const backupsResponse = await api.get('/backup/list?backup_type=all')
      const allBackups: BackupFile[] = backupsResponse.data.backups || []

      setSettingsBackups(allBackups.filter(b => b.type === 'settings'))
      setFullBackups(allBackups.filter(b => b.type === 'full'))
    } catch {
      setMessage({ type: 'error', text: 'Failed to load backup data' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleCreateSettingsBackup = async () => {
    setCreatingSettings(true)
    setMessage(null)

    try {
      const response = await api.post('/backup/create')
      setMessage({ type: 'success', text: response.data.message || 'Settings backup created successfully!' })
      await loadData()
    } catch {
      setMessage({ type: 'error', text: 'Failed to create settings backup' })
    } finally {
      setCreatingSettings(false)
    }
  }

  const handleCreateFullBackup = async () => {
    setCreatingFull(true)
    setMessage(null)

    try {
      const response = await api.post('/backup/create-full')
      setMessage({ type: 'success', text: response.data.message || 'Full backup created successfully!' })
      await loadData()
    } catch {
      setMessage({ type: 'error', text: 'Failed to create full backup' })
    } finally {
      setCreatingFull(false)
    }
  }

  const handleDownload = async (filename: string) => {
    try {
      const response = await api.get(`/backup/download/${filename}`, {
        responseType: 'blob'
      })

      const blob = response.data
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch {
      // Removed console.error
      setMessage({ type: 'error', text: `Failed to download ${filename}` })
    }
  }

  const handleRestore = async (filename: string, isFullBackup: boolean) => {
    const confirmMessage = isFullBackup
      ? 'WARNING: This will overwrite your entire database and all uploaded files! A safety backup will be created first. Are you absolutely sure?'
      : 'This will restore all settings from the backup. A safety backup will be created first. Continue?'

    if (!confirm(confirmMessage)) {
      return
    }

    setMessage(null)

    try {
      const response = await api.post(`/backup/restore/${filename}`)
      setMessage({
        type: 'success',
        text: response.data.message + (response.data.warning ? ` ${response.data.warning}` : '')
      })

      await loadData()

      if (isFullBackup) {
        setMessage({
          type: 'warning',
          text: 'Full backup restored! Please refresh the page or restart the application for changes to take effect.'
        })
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      setMessage({ type: 'error', text: error.response?.data?.detail || error.message || 'Restore failed' })
    }
  }

  const handleDelete = async (filename: string) => {
    if (!confirm(`Are you sure you want to delete ${filename}?`)) {
      return
    }

    try {
      await api.delete(`/backup/${filename}`)
      setMessage({ type: 'success', text: `Backup ${filename} deleted successfully` })
      await loadData()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      setMessage({ type: 'error', text: error.response?.data?.detail || error.message || 'Failed to delete backup' })
    }
  }

  const handleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)

    try {
      const response = await api.post('/backup/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })
      setMessage({ type: 'success', text: response.data.message || 'Backup uploaded successfully!' })
      await loadData()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      setMessage({ type: 'error', text: error.response?.data?.detail || error.message || 'Upload failed' })
    } finally {
      if (settingsFileInputRef.current) settingsFileInputRef.current.value = ''
      if (fullFileInputRef.current) fullFileInputRef.current.value = ''
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString()
  }

  const formatSize = (sizeMb: number) => {
    if (sizeMb < 1) {
      return `${(sizeMb * 1024).toFixed(1)} KB`
    }
    return `${sizeMb.toFixed(2)} MB`
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading backup data...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Success/Error Messages */}
      {message && (
        <div
          className={`p-4 rounded-lg border flex items-start gap-2 ${
            message.type === 'success'
              ? 'bg-success-500/10 border-success-500 text-success-500'
              : message.type === 'warning'
              ? 'bg-warning-500/10 border-warning-500 text-warning-500'
              : 'bg-danger-500/10 border-danger-500 text-danger-500'
          }`}
        >
          {message.type === 'success' ? (
            <CheckCircle className="w-5 h-5 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 mt-0.5" />
          )}
          <div className="flex-1">{message.text}</div>
          <button
            onClick={() => setMessage(null)}
            className="text-current opacity-60 hover:opacity-100"
          >
            ×
          </button>
        </div>
      )}

      {/* Backup Sections Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ========== SECTION 1: SETTINGS BACKUP ========== */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <FileJson className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">Settings Backup</h2>
            <p className="text-sm text-garage-text-muted">
              Backup and restore application settings only. Does not include database or uploaded files.
            </p>
          </div>
        </div>

        {/* Database Statistics */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <div className="flex items-center gap-2 text-garage-text-muted mb-2">
                <Database className="w-4 h-4" />
                <span className="text-sm font-medium">Database Size</span>
              </div>
              <p className="text-2xl font-bold text-primary">{stats.database.size_mb} MB</p>
            </div>
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <div className="flex items-center gap-2 text-garage-text-muted mb-2">
                <FileJson className="w-4 h-4" />
                <span className="text-sm font-medium">Settings Backups</span>
              </div>
              <p className="text-2xl font-bold text-primary">{stats.settings_backups.count}</p>
              <p className="text-xs text-garage-text-muted mt-1">
                {formatSize(stats.settings_backups.total_size_mb)} total
              </p>
            </div>
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <div className="flex items-center gap-2 text-garage-text-muted mb-2">
                <Database className="w-4 h-4" />
                <span className="text-sm font-medium">Last Modified</span>
              </div>
              <p className="text-sm font-bold text-primary">
                {stats.database.last_modified ? formatDate(stats.database.last_modified) : 'Never'}
              </p>
            </div>
          </div>
        )}

        {/* Create Settings Backup */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={handleCreateSettingsBackup}
            disabled={creatingSettings}
            className="flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
          >
            <Download size={16} />
            {creatingSettings ? 'Creating Backup...' : 'Create Settings Backup'}
          </button>
          <button
            onClick={() => settingsFileInputRef.current?.click()}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Upload size={16} />
            Upload Settings Backup
          </button>
          <input
            ref={settingsFileInputRef}
            type="file"
            accept=".json"
            onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
            className="hidden"
          />
        </div>

        {/* Settings Backup Files Table */}
        {settingsBackups.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-garage-bg border-b border-garage-border">
                <tr>
                  <th className="text-left p-3 text-garage-text font-medium">Filename</th>
                  <th className="text-left p-3 text-garage-text font-medium">Size</th>
                  <th className="text-left p-3 text-garage-text font-medium">Created</th>
                  <th className="text-right p-3 text-garage-text font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {settingsBackups.map((backup) => (
                  <tr key={backup.filename} className="border-b border-garage-border hover:bg-garage-bg">
                    <td className="p-3 text-garage-text font-mono text-xs">
                      {backup.filename}
                      {backup.is_safety && (
                        <span className="ml-2 px-2 py-0.5 text-xs bg-warning-500/20 text-warning-500 rounded">
                          Safety
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-garage-text-muted">{formatSize(backup.size_mb)}</td>
                    <td className="p-3 text-garage-text-muted">{formatDate(backup.created)}</td>
                    <td className="p-3 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => handleDownload(backup.filename)}
                          className="p-1 text-primary hover:bg-primary/10 rounded"
                          title="Download"
                        >
                          <Download size={16} />
                        </button>
                        <button
                          onClick={() => handleRestore(backup.filename, false)}
                          className="p-1 text-success-500 hover:bg-success-500/10 rounded"
                          title="Restore"
                        >
                          <RefreshCw size={16} />
                        </button>
                        {!backup.is_safety && (
                          <button
                            onClick={() => handleDelete(backup.filename)}
                            className="p-1 text-danger-500 hover:bg-danger-500/10 rounded"
                            title="Delete"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8 text-garage-text-muted">
            No settings backups available. Create your first backup above.
          </div>
        )}
        </div>

        {/* ========== SECTION 2: FULL DATA BACKUP ========== */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <Archive className="w-6 h-6 text-warning-500 mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">Full Data Backup</h2>
            <p className="text-sm text-garage-text-muted">
              Complete backup including database and all uploaded files (photos, documents, attachments).
              May take several minutes depending on data size.
            </p>
          </div>
        </div>

        {/* Full Backup Statistics */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <div className="flex items-center gap-2 text-garage-text-muted mb-2">
                <Archive className="w-4 h-4" />
                <span className="text-sm font-medium">Full Backups</span>
              </div>
              <p className="text-2xl font-bold text-warning-500">{stats.full_backups.count}</p>
              <p className="text-xs text-garage-text-muted mt-1">
                {formatSize(stats.full_backups.total_size_mb)} total
              </p>
            </div>
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <div className="flex items-center gap-2 text-garage-text-muted mb-2">
                <HardDrive className="w-4 h-4" />
                <span className="text-sm font-medium">Data Included</span>
              </div>
              <p className="text-sm text-garage-text">
                Database, Photos, Documents, Attachments
              </p>
            </div>
          </div>
        )}

        {/* Warning */}
        <div className="bg-warning-500/10 border border-warning-500 rounded-lg p-4 mb-6">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-warning-500 mt-0.5" />
            <div>
              <h3 className="text-sm font-medium text-warning-500 mb-1">Important Information:</h3>
              <ul className="text-sm text-warning-500/90 space-y-1">
                <li>• Full backups include your entire database and all uploaded files</li>
                <li>• Backup size depends on the amount of photos and documents you have uploaded</li>
                <li>• Restoring a full backup will OVERWRITE all current data and files</li>
                <li>• A safety backup is automatically created before any restore operation</li>
                <li>• Application restart may be required after restoring a full backup</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Create Full Backup */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={handleCreateFullBackup}
            disabled={creatingFull}
            className="flex items-center gap-2 px-4 py-2 btn bg-warning-600 hover:bg-warning-700 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Archive size={16} />
            {creatingFull ? 'Creating Full Backup...' : 'Create Full Backup'}
          </button>
          <button
            onClick={() => fullFileInputRef.current?.click()}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Upload size={16} />
            Upload Full Backup
          </button>
          <input
            ref={fullFileInputRef}
            type="file"
            accept=".tar.gz"
            onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
            className="hidden"
          />
        </div>

        {/* Full Backup Files Table */}
        {fullBackups.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-garage-bg border-b border-garage-border">
                <tr>
                  <th className="text-left p-3 text-garage-text font-medium">Filename</th>
                  <th className="text-left p-3 text-garage-text font-medium">Size</th>
                  <th className="text-left p-3 text-garage-text font-medium">Created</th>
                  <th className="text-right p-3 text-garage-text font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {fullBackups.map((backup) => (
                  <tr key={backup.filename} className="border-b border-garage-border hover:bg-garage-bg">
                    <td className="p-3 text-garage-text font-mono text-xs">
                      {backup.filename}
                      {backup.is_safety && (
                        <span className="ml-2 px-2 py-0.5 text-xs bg-warning-500/20 text-warning-500 rounded">
                          Safety
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-garage-text-muted">{formatSize(backup.size_mb)}</td>
                    <td className="p-3 text-garage-text-muted">{formatDate(backup.created)}</td>
                    <td className="p-3 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => handleDownload(backup.filename)}
                          className="p-1 text-primary hover:bg-primary/10 rounded"
                          title="Download"
                        >
                          <Download size={16} />
                        </button>
                        <button
                          onClick={() => handleRestore(backup.filename, true)}
                          className="p-1 text-danger-500 hover:bg-danger-500/10 rounded"
                          title="Restore (Overwrites all data!)"
                        >
                          <RefreshCw size={16} />
                        </button>
                        {!backup.is_safety && (
                          <button
                            onClick={() => handleDelete(backup.filename)}
                            className="p-1 text-danger-500 hover:bg-danger-500/10 rounded"
                            title="Delete"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8 text-garage-text-muted">
            No full backups available. Create your first full backup above.
          </div>
        )}
        </div>
      </div>
    </div>
  )
}
