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

const DEFAULT_MAX_BANDWIDTH = 0.8 // MB/s

export function uploadBatchWithProgress(
  url: string,
  accessToken: string,
  files: File[],
  batchByteOffset: number,
  totalAllBytes: number,
  onProgress: BatchProgressCallback,
  maxBandwidthMBs: number = DEFAULT_MAX_BANDWIDTH,
): Promise<any> {
  const maxBytesPerSecond = maxBandwidthMBs * 1024 * 1024

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    const startTime = Date.now()

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const elapsed = (Date.now() - startTime) / 1000
        const avgSpeed = elapsed > 0 ? e.loaded / elapsed : 0

        const totalUploaded = batchByteOffset + e.loaded
        const pct = totalAllBytes > 0 ? Math.round((totalUploaded / totalAllBytes) * 100) : 0
        onProgress({
          bytesUploaded: totalUploaded,
          totalBytes: totalAllBytes,
          percentage: pct,
          speedBytesPerSecond: avgSpeed,
          currentFile: files.length === 1 ? files[0].name : `${files.length} files`,
        })
      }
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        reject(new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`))
      }
    })

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'))
    })

    xhr.open('POST', url)
    xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`)

    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }

    xhr.send(formData)
  })
}
