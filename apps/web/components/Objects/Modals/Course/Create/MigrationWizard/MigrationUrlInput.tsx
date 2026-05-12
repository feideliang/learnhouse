'use client'
import React, { useState, useEffect } from 'react'
import { Link2, X, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getAPIUrl } from '@services/config/config'

interface ParsedUrl {
  id: string
  uri: string
  name: string
}

interface MigrationUrlInputProps {
  urls: ParsedUrl[]
  onUrlsChange: (urls: ParsedUrl[]) => void
  creating: boolean
}

export default function MigrationUrlInput({
  urls,
  onUrlsChange,
  creating,
}: MigrationUrlInputProps) {
  const { t } = useTranslation()
  const [rawInput, setRawInput] = useState('')
  const [minioEndpoint, setMinioEndpoint] = useState('')

  // Fetch MinIO endpoint from backend on mount
  useEffect(() => {
    fetch(`${getAPIUrl()}instance/info`)
      .then(r => r.json())
      .then(data => {
        if (data?.minio_endpoint) {
          setMinioEndpoint(data.minio_endpoint)
        }
      })
      .catch(() => {})
  }, [])

  const parseUrls = (text: string) => {
    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0)
    const newUrls: ParsedUrl[] = []
    for (const line of lines) {
      try {
        let uri = line
        // If it's a relative path (doesn't start with http), prepend MinIO endpoint
        if (!line.startsWith('http://') && !line.startsWith('https://')) {
          if (!minioEndpoint) continue // Skip if no endpoint configured
          const basePath = minioEndpoint.replace(/\/+$/, '')
          const pathPart = line.startsWith('/') ? line : '/' + line
          uri = basePath + pathPart
        }
        const url = new URL(uri)
        const pathParts = url.pathname.split('/').filter(p => p.length > 0)
        const filename = pathParts[pathParts.length - 1] || ''
        const name = filename
          .replace(/\.[^/.]+$/, '')
          .replace(/[_-]/g, ' ')
          .replace(/\b\w/g, c => c.toUpperCase())
        const validExt = /\.(mp4|webm|mov|mkv|avi)$/i.test(filename)
        if (!validExt) continue
        newUrls.push({
          id: crypto.randomUUID(),
          uri,
          name: name || 'Untitled Video',
        })
      } catch {
        continue
      }
    }
    return newUrls
  }

  const handleAdd = () => {
    if (!rawInput.trim()) return
    const parsed = parseUrls(rawInput)
    if (parsed.length > 0) {
      onUrlsChange([...urls, ...parsed])
      setRawInput('')
    }
  }

  const handlePaste = async (e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData('text')
    if (text.includes('\n') || text.includes('http') || text.includes('/')) {
      e.preventDefault()
      const parsed = parseUrls(text)
      if (parsed.length > 0) {
        onUrlsChange([...urls, ...parsed])
        setRawInput('')
      }
    }
  }

  const removeUrl = (id: string) => {
    onUrlsChange(urls.filter(u => u.id !== id))
  }

  const updateUrlName = (id: string, name: string) => {
    onUrlsChange(urls.map(u => u.id === id ? { ...u, name } : u))
  }

  return (
    <div className="space-y-4">
      {/* MinIO Endpoint Display */}
      {minioEndpoint && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-50 border border-blue-100">
          <Globe size={14} className="text-blue-500 flex-shrink-0" />
          <span className="text-xs text-blue-600 font-mono truncate">{minioEndpoint}</span>
          <span className="text-xs text-blue-400 whitespace-nowrap ml-auto">
            {t('migration.auto_detect') || 'Auto-detected'}
          </span>
        </div>
      )}

      {/* Path Input */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-700">
          {t('migration.minio_paths_label') || 'MinIO Video Paths'}
        </label>
        <div className="flex gap-2">
          <textarea
            value={rawInput}
            onChange={(e) => setRawInput(e.target.value)}
            onPaste={handlePaste}
            placeholder={t('migration.minio_paths_placeholder') || 'bucket-name/path/video.mp4\n/orgs/.../video.mp4'}
            rows={3}
            disabled={creating}
            className="flex-1 h-[80px] px-3 py-2 text-sm rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200 resize-none font-mono"
          />
          <button
            onClick={handleAdd}
            disabled={!rawInput.trim() || creating}
            className={`self-end rounded-lg px-4 py-2 text-sm font-medium transition-all ${
              !rawInput.trim() || creating
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : 'bg-black text-white hover:bg-gray-800'
            }`}
          >
            <Link2 size={16} />
          </button>
        </div>
      </div>

      {/* URL List */}
      {urls.length > 0 && (
        <div className="space-y-1.5 max-h-48 overflow-y-auto">
          {urls.map((url) => (
            <div
              key={url.id}
              className="flex items-center justify-between rounded-lg px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors"
            >
              <div className="flex items-center space-x-2.5 min-w-0">
                <Link2 size={14} className="text-blue-500 flex-shrink-0" />
                <input
                  type="text"
                  value={url.name}
                  onChange={(e) => updateUrlName(url.id, e.target.value)}
                  className="text-sm text-gray-700 bg-transparent border-0 focus:outline-none truncate max-w-[300px]"
                />
              </div>
              <div className="flex items-center space-x-2 flex-shrink-0 ml-2">
                <span className="text-[10px] text-gray-400 max-w-[150px] truncate" title={url.uri}>
                  {url.uri}
                </span>
                {!creating && (
                  <button
                    onClick={() => removeUrl(url.id)}
                    className="text-gray-300 hover:text-red-500 transition-colors"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
