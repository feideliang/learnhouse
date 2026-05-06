import { getAPIUrl } from '@services/config/config'
import {
  uploadBatchWithProgress,
  BatchProgressInfo,
} from '@/lib/upload-progress'

export interface UploadedFileInfo {
  file_id: string
  filename: string
  file_type: string
  size: number
  extension: string
}

export interface MigrationActivityNode {
  name: string
  activity_type: string
  activity_sub_type: string
  file_ids: string[]
}

export interface MigrationChapterNode {
  name: string
  activities: MigrationActivityNode[]
}

export interface MigrationTreeStructure {
  course_name: string
  course_description?: string
  chapters: MigrationChapterNode[]
}

export interface MigrationCreateResult {
  course_uuid: string
  course_name: string
  chapters_created: number
  activities_created: number
  success: boolean
  error?: string
}

export interface UploadProgressInfo {
  uploaded: number
  total: number
  percentage: number
  speedBytesPerSecond: number
  currentFile: string
}

export type UploadProgressCallback = (info: UploadProgressInfo) => void

export interface MigrationUploadResponse {
  temp_id: string
  files: UploadedFileInfo[]
  skipped: string[]
}

export async function uploadMigrationFiles(
  files: File[],
  access_token: string,
  onProgress?: UploadProgressCallback
): Promise<MigrationUploadResponse> {
  let tempId: string | null = null
  let allUploadedFiles: UploadedFileInfo[] = []
  let allSkipped: string[] = []
  const totalAllBytes = files.reduce((sum, f) => sum + f.size, 0)

  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    const batchByteOffset = files.slice(0, i).reduce((s, f) => s + f.size, 0)

    const tempIdParam = tempId ? `&temp_id=${tempId}` : ''
    const url = `${getAPIUrl()}courses/migrate/upload${tempIdParam}`

    const result: MigrationUploadResponse = await uploadBatchWithProgress(
      url,
      access_token,
      [file],
      batchByteOffset,
      totalAllBytes,
      (info: BatchProgressInfo) => {
        if (onProgress) {
          onProgress({
            uploaded: i,
            total: files.length,
            percentage: info.percentage,
            speedBytesPerSecond: info.speedBytesPerSecond,
            currentFile: file.name,
          })
        }
      }
    )

    tempId = result.temp_id
    allUploadedFiles = [...allUploadedFiles, ...result.files]
    allSkipped = [...allSkipped, ...result.skipped]
  }

  if (onProgress) {
    onProgress({
      uploaded: files.length,
      total: files.length,
      percentage: 100,
      speedBytesPerSecond: 0,
      currentFile: '',
    })
  }

  return {
    temp_id: tempId!,
    files: allUploadedFiles,
    skipped: allSkipped,
  }
}

export async function suggestStructure(
  temp_id: string,
  course_name: string,
  description: string | undefined,
  access_token: string
): Promise<MigrationTreeStructure> {
  const response = await fetch(
    `${getAPIUrl()}courses/migrate/suggest`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${access_token}`,
      },
      body: JSON.stringify({ temp_id, course_name, description }),
    }
  )

  if (!response.ok) {
    throw new Error(`Suggestion failed: ${response.statusText}`)
  }

  return response.json()
}

export async function createFromMigration(
  temp_id: string,
  structure: MigrationTreeStructure,
  org_id: number,
  access_token: string
): Promise<MigrationCreateResult> {
  const response = await fetch(
    `${getAPIUrl()}courses/migrate/create?org_id=${org_id}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${access_token}`,
      },
      body: JSON.stringify({ temp_id, structure }),
    }
  )

  if (!response.ok) {
    throw new Error(`Creation failed: ${response.statusText}`)
  }

  return response.json()
}
