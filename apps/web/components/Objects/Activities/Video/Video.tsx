import React from 'react'
import YouTube from 'react-youtube'
import { getActivityVideoStreamUrl } from '@services/media/media'
import { useOrg } from '@components/Contexts/OrgContext'
import LearnHousePlayer from './LearnHousePlayer'
import { AlertCircle } from 'lucide-react'

interface VideoDetails {
  startTime?: number
  endTime?: number | null
  autoplay?: boolean
  muted?: boolean
}

interface VideoActivityProps {
  activity: {
    activity_sub_type: string
    activity_uuid: string
    content: {
      filename?: string
      uri?: string
    }
    details?: VideoDetails
  }
  course: {
    course_uuid: string
  }
  orgUuid?: string
}

function VideoActivity({ activity, course, orgUuid }: VideoActivityProps) {
  const org = useOrg() as any
  const resolvedOrgUuid = orgUuid || org?.org_uuid
  const [videoId, setVideoId] = React.useState('')

  React.useEffect(() => {
    if (activity?.content?.uri) {
      var getYouTubeID = require('get-youtube-id')
      setVideoId(getYouTubeID(activity.content.uri))
    }
  }, [activity, org])

  const getVideoSrc = () => {
    if (!resolvedOrgUuid || !course?.course_uuid || !activity?.activity_uuid || !activity.content?.filename) {
      return ''
    }
    return getActivityVideoStreamUrl(
      resolvedOrgUuid,
      course.course_uuid,
      activity.activity_uuid,
      activity.content.filename
    )
  }

  return (
    <div className="w-full max-w-full px-0 sm:px-4">
      {activity && (
        <>
          {activity.activity_sub_type === 'SUBTYPE_VIDEO_HOSTED' && (
            <div className="my-0 sm:my-3 md:my-5 w-full">
              <div className="relative w-full aspect-video sm:rounded-lg overflow-hidden ring-0 sm:ring-1 sm:ring-gray-200/10 sm:dark:ring-gray-700/20 shadow-none">
                {(() => {
                  const src = getVideoSrc()
                  return src ? (
                    <LearnHousePlayer
                      key={activity.activity_uuid}
                      src={src}
                      details={activity.details}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-gray-900 text-white">
                      <div className="text-center">
                        <AlertCircle className="w-8 h-8 mx-auto mb-2 text-yellow-400" />
                        <p className="text-sm">Video unavailable — missing context information</p>
                      </div>
                    </div>
                  )
                })()}
              </div>
            </div>
          )}
          {activity.activity_sub_type === 'SUBTYPE_VIDEO_YOUTUBE' && (
            <div className="my-0 sm:my-3 md:my-5 w-full">
              <div className="relative w-full aspect-video sm:rounded-lg overflow-hidden ring-0 sm:ring-1 sm:ring-gray-200/10 sm:dark:ring-gray-700/20 shadow-none">
                <YouTube
                  className="w-full h-full"
                  opts={{
                    width: '100%',
                    height: '100%',
                    playerVars: {
                      autoplay: activity.details?.autoplay ? 1 : 0,
                      mute: activity.details?.muted ? 1 : 0,
                      start: activity.details?.startTime || 0,
                      end: activity.details?.endTime || undefined,
                      controls: 1,
                      modestbranding: 1,
                      rel: 0
                    },
                  }}
                  videoId={videoId}
                  onReady={(event) => {
                    if (activity.details?.startTime) {
                      event.target.seekTo(activity.details.startTime, true)
                    }
                  }}
                />
              </div>
            </div>
          )}
          {activity.activity_sub_type === 'SUBTYPE_VIDEO_MINIO' && (
            <div className="my-0 sm:my-3 md:my-5 w-full">
              <div className="relative w-full aspect-video sm:rounded-lg overflow-hidden ring-0 sm:ring-1 sm:ring-gray-200/10 sm:dark:ring-gray-700/20 shadow-none">
                {(() => {
                  // Use backend stream endpoint — browsers cannot reach internal MinIO URLs directly
                  if (resolvedOrgUuid && course?.course_uuid && activity?.activity_uuid && activity.content?.filename) {
                    const src = getActivityVideoStreamUrl(
                      resolvedOrgUuid,
                      course.course_uuid,
                      activity.activity_uuid,
                      activity.content.filename
                    )
                    return (
                      <LearnHousePlayer
                        key={activity.activity_uuid}
                        src={src}
                        details={activity.details}
                      />
                    )
                  }
                  return (
                    <div className="w-full h-full flex items-center justify-center bg-gray-900 text-white">
                      <div className="text-center">
                        <AlertCircle className="w-8 h-8 mx-auto mb-2 text-yellow-400" />
                        <p className="text-sm">Video unavailable — missing stream information</p>
                      </div>
                    </div>
                  )
                })()}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default VideoActivity
