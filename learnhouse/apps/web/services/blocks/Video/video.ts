import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'
import { uploadFileWithXHR, BatchProgressInfo } from '@/lib/upload-progress'

export async function uploadNewVideoFile(
  file: File,
  activity_uuid: string,
  access_token: string,
  onProgress?: (info: BatchProgressInfo) => void,
  _maxBandwidthMBs?: number,
) {
  return uploadFileWithXHR(
    `${getAPIUrl()}blocks/video`,
    access_token,
    file,
    'file_object',
    { activity_uuid },
    onProgress,
  )
}

export async function getVideoFile(file_id: string, access_token: string) {
  return fetch(
    `${getAPIUrl()}blocks/video?file_id=${file_id}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
    .then((result) => result.json())
    .catch((error) => console.error('error', error))
}
