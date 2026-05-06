import { getAPIUrl } from '@services/config/config'
import { BatchProgressInfo } from '@/lib/upload-progress'

const DEFAULT_MAX_BANDWIDTH = 0.8 // MB/s

export async function uploadNewAudioFile(
  file: File,
  activity_uuid: string,
  access_token: string,
  onProgress?: (info: BatchProgressInfo) => void,
  maxBandwidthMBs: number = DEFAULT_MAX_BANDWIDTH,
) {
  const response = await uploadFileWithThrottle(
    `${getAPIUrl()}blocks/audio`,
    access_token,
    file,
    'file_object',
    { activity_uuid },
    onProgress,
    maxBandwidthMBs,
  )
  return response
}

function uploadFileWithThrottle(
  url: string,
  accessToken: string,
  file: File,
  fieldName: string,
  extraFields: Record<string, string>,
  onProgress?: (info: BatchProgressInfo) => void,
  maxBandwidthMBs: number = DEFAULT_MAX_BANDWIDTH,
): Promise<Record<string, any>> {
  const maxBytesPerSecond = maxBandwidthMBs * 1024 * 1024

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    const startTime = Date.now()

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const elapsed = (Date.now() - startTime) / 1000
        const avgSpeed = elapsed > 0 ? e.loaded / elapsed : 0

        const pct = Math.round((e.loaded / e.total) * 100)
        onProgress?.({
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
        resolve(JSON.parse(xhr.responseText))
      } else {
        let msg = `Upload failed: ${xhr.status} ${xhr.statusText}`
        try {
          const detail = JSON.parse(xhr.responseText)?.detail
          if (detail) msg = detail
        } catch {}
        reject(new Error(msg))
      }
    })

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'))
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
