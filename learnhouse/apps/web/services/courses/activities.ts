import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyWithAuthHeader,
  getResponseMetadata,
} from '@services/utils/ts/requests'
import { uploadFileWithXHR, BatchProgressInfo } from '@/lib/upload-progress'

export async function createActivity(
  data: any,
  chapter_id: any,
  org_id: any,
  access_token: string
) {
  data.content = data.content || {}
  // remove chapter_id from data
  delete data.chapterId

  const result = await fetch(
    `${getAPIUrl()}activities/?coursechapter_id=${chapter_id}&org_id=${org_id}`,
    RequestBodyWithAuthHeader('POST', data, null, access_token)
  )
  const res = await result.json()
  return res
}

export async function createFileActivity(
  file: File,
  type: string,
  data: any,
  chapter_id: any,
  access_token: string,
  onProgress?: (info: BatchProgressInfo) => void,
) {
  let endpoint = ''
  let fieldName = ''
  const extraFields: Record<string, string> = { chapter_id: String(chapter_id) }

  if (type === 'video') {
    extraFields['name'] = data.name
    fieldName = 'video_file'
    if (data.details) {
      extraFields['details'] = JSON.stringify({
        startTime: data.details.startTime || 0,
        endTime: data.details.endTime || null,
        autoplay: data.details.autoplay || false,
        muted: data.details.muted || false,
      })
    }
    endpoint = `${getAPIUrl()}activities/video`
  } else if (type === 'documentpdf') {
    extraFields['name'] = data.name
    fieldName = 'pdf_file'
    endpoint = `${getAPIUrl()}activities/documentpdf`
  } else {
    throw new Error(`Unsupported file activity type: ${type}`)
  }

  return uploadFileWithXHR(
    endpoint,
    access_token,
    file,
    fieldName,
    extraFields,
    onProgress,
  )
}

export async function createExternalVideoActivity(
  data: any,
  activity: any,
  chapter_id: any,
  access_token: string
) {
  // add coursechapter_id to data
  data.chapter_id = String(chapter_id)
  data.activity_id = activity.id
  
  // Add video details with null checking
  const defaultDetails = {
    startTime: 0,
    endTime: null,
    autoplay: false,
    muted: false
  }

  const videoDetails = data.details ? {
    startTime: data.details.startTime ?? defaultDetails.startTime,
    endTime: data.details.endTime ?? defaultDetails.endTime,
    autoplay: data.details.autoplay ?? defaultDetails.autoplay,
    muted: data.details.muted ?? defaultDetails.muted
  } : defaultDetails

  data.details = JSON.stringify(videoDetails)

  const result = await fetch(
    `${getAPIUrl()}activities/external_video`,
    RequestBodyWithAuthHeader('POST', data, null, access_token)
  )
  const res = await result.json()
  return res
}

export async function getActivity(
  activity_uuid: any,
  next: any,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}`,
    RequestBodyWithAuthHeader('GET', null, next, access_token)
  )
  const res = await result.json()
  return res
}

export async function getActivityByID(
  activity_id: any,
  next: any,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/id/${activity_id}`,
    RequestBodyWithAuthHeader('GET', null, next, access_token)
  )
  const res = await result.json()
  return res
}

export async function deleteActivity(activity_uuid: any, access_token: string) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}`,
    RequestBodyWithAuthHeader('DELETE', null, null, access_token)
  )
  const res = await result.json()
  return res
}

export async function getActivityWithAuthHeader(
  activity_uuid: any,
  next: any,
  access_token: string | null | undefined
) {
  const result = await fetch(
    `${getAPIUrl()}activities/activity_${activity_uuid}`,
    RequestBodyWithAuthHeader('GET', null, next, access_token || undefined)
  )
  const res = await result.json()
  return res
}

export async function updateActivity(
  data: any,
  activity_uuid: string,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}`,
    RequestBodyWithAuthHeader('PUT', data, null, access_token)
  )
  const res = await getResponseMetadata(result)
  return res
}

export async function getActivityUserGroups(
  activity_uuid: string,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/usergroups`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return result.json()
}

export async function addUserGroupToActivity(
  activity_uuid: string,
  usergroup_uuid: string,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/usergroups/${usergroup_uuid}`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  )
  return result.json()
}

export async function removeUserGroupFromActivity(
  activity_uuid: string,
  usergroup_uuid: string,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/usergroups/${usergroup_uuid}`,
    RequestBodyWithAuthHeader('DELETE', null, null, access_token)
  )
  return result.json()
}

export async function getUrlPreview(url: string) {
  const result = await fetch(
    `${getAPIUrl()}utils/link-preview?url=${encodeURIComponent(url)}`,
    RequestBodyWithAuthHeader('GET', null, null, undefined)
  )
  const res = await result.json()
  return res
}

// Versioning API functions

export async function getActivityVersions(
  activity_uuid: string,
  access_token: string,
  limit: number = 20,
  offset: number = 0
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/versions?limit=${limit}&offset=${offset}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  const res = await result.json()
  return res
}

export async function getActivityVersion(
  activity_uuid: string,
  version_number: number,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/versions/${version_number}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  const res = await result.json()
  return res
}

export async function getActivityState(
  activity_uuid: string,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/state`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  const res = await result.json()
  return res
}

export async function restoreActivityVersion(
  activity_uuid: string,
  version_number: number,
  access_token: string
) {
  const result = await fetch(
    `${getAPIUrl()}activities/${activity_uuid}/versions/${version_number}/restore`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  )
  const res = await getResponseMetadata(result)
  return res
}
