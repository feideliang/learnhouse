import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'
import { uploadFileWithXHR, BatchProgressInfo } from '@/lib/upload-progress'

export async function uploadNewImageFile(
  file: File,
  activity_uuid: string,
  access_token: string,
  onProgress?: (info: BatchProgressInfo) => void,
) {
  return uploadFileWithXHR(
    `${getAPIUrl()}blocks/image`,
    access_token,
    file,
    'file_object',
    { activity_uuid },
    onProgress,
  )
}

export async function getImageFile(file_id: string, access_token: string) {
  // todo : add course id to url
  return fetch(
    `${getAPIUrl()}blocks/image?file_id=${file_id}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
    .then((result) => result.json())
    .catch((error) => console.log('error', error))
}
