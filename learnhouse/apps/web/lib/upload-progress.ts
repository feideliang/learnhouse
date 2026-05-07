export interface BatchProgressInfo {
  bytesUploaded: number
  totalBytes: number
  percentage: number
  speedBytesPerSecond: number
  currentFile: string
}

export type BatchProgressCallback = (info: BatchProgressInfo) => void

export function formatBytesPerSecond(bytesPerSecond: number): string {
  if (bytesPerSecond < 1024) {
    return `${bytesPerSecond.toFixed(0)} B/s`
  }
  if (bytesPerSecond < 1048576) {
    return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`
  }
  if (bytesPerSecond < 1073741824) {
    return `${(bytesPerSecond / 1048576).toFixed(1)} MB/s`
  }
  return `${(bytesPerSecond / 1073741824).toFixed(2)} GB/s`
}

export function uploadFileWithXHR(
  url: string,
  accessToken: string,
  file: File,
  fieldName: string,
  extraFields: Record<string, string>,
  onProgress?: BatchProgressCallback,
): Promise<any> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const startTime = Date.now()

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        const elapsed = (Date.now() - startTime) / 1000
        const avgSpeed = elapsed > 0 ? e.loaded / elapsed : 0
        const pct = Math.round((e.loaded / e.total) * 100)
        onProgress({
          bytesUploaded: e.loaded,
          totalBytes: e.total,
          percentage: pct,
          speedBytesPerSecond: avgSpeed,
          currentFile: file.name,
        })
      }
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          resolve({})
        }
      } else {
        let msg = `Upload failed: ${xhr.status} ${xhr.statusText}`
        try {
          const detail = JSON.parse(xhr.responseText)?.detail
          if (detail) msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
        } catch {}
        reject(new Error(msg))
      }
    })

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'))
    })

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload aborted'))
    })

    xhr.open('POST', url)
    xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`)

    const formData = new FormData()
    for (const [key, value] of Object.entries(extraFields)) {
      formData.append(key, value)
    }
    formData.append(fieldName, file)

    xhr.send(formData)
  })
}

export function uploadBatchWithProgress(
  url: string,
  accessToken: string,
  files: File[],
  batchByteOffset: number,
  totalAllBytes: number,
  onProgress: BatchProgressCallback,
): Promise<any> {
  if (files.length !== 1) {
    throw new Error('uploadBatchWithProgress supports a single file per call')
  }
  const file = files[0]

  return uploadFileWithXHR(
    url,
    accessToken,
    file,
    'files',
    {},
    (info) => {
      const totalUploaded = batchByteOffset + info.bytesUploaded
      const pct = totalAllBytes > 0 ? Math.round((totalUploaded / totalAllBytes) * 100) : 0
      onProgress({
        bytesUploaded: totalUploaded,
        totalBytes: totalAllBytes,
        percentage: pct,
        speedBytesPerSecond: info.speedBytesPerSecond,
        currentFile: file.name,
      })
    },
  )
}
