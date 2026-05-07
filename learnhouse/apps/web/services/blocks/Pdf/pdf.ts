import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'
import { uploadFileWithXHR, BatchProgressInfo } from '@/lib/upload-progress'

export async function uploadNewPDFFile(
  file: File,
  activity_uuid: string,
  access_token: string,
  onProgress?: (info: BatchProgressInfo) => void,
) {
  return uploadFileWithXHR(
    `${getAPIUrl()}blocks/pdf`,
    access_token,
    file,
    'file_object',
    { activity_uuid },
    onProgress,
  )
}

export async function getPDFFile(file_id: string, access_token: string) {
  // todo : add course id to url
  return fetch(
    `${getAPIUrl()}blocks/pdf?file_id=${file_id}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
    .then((result) => result.json())
    .catch((error) => console.log('error', error))
}
