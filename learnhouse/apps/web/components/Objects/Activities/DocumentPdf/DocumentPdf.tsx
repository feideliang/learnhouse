import { useOrg } from '@components/Contexts/OrgContext'
import { getActivityMediaDirectory } from '@services/media/media'
import React, { useState } from 'react'
import { AlertCircle, ExternalLink } from 'lucide-react'

function DocumentPdfActivity({
  activity,
  course,
  orgUuid,
  className,
}: {
  activity: any
  course: any
  orgUuid?: string
  className?: string
}) {
  const org = useOrg() as any
  const resolvedOrgUuid = orgUuid || org?.org_uuid
  const [hasError, setHasError] = useState(false)

  const hasAllParams = resolvedOrgUuid && course?.course_uuid && activity?.activity_uuid && activity.content?.filename

  if (!hasAllParams) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center text-gray-400">
          <AlertCircle className="w-8 h-8 mx-auto mb-2" />
          <p className="text-sm">PDF unavailable — missing context information</p>
        </div>
      </div>
    )
  }

  const pdfUrl = getActivityMediaDirectory(
    resolvedOrgUuid,
    course.course_uuid,
    activity.activity_uuid,
    activity.content.filename,
    'documentpdf'
  )

  return (
    <div className={className ?? "m-0 sm:m-8 bg-zinc-900 sm:rounded-md mt-0 sm:mt-14"}>
      {hasError && (
        <div className="w-full h-[85vh] sm:h-[900px] flex flex-col items-center justify-center gap-4 bg-gray-100 sm:rounded-lg text-gray-600">
          <AlertCircle className="w-10 h-10 text-red-400" />
          <p className="text-sm font-medium">Failed to load PDF</p>
          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-blue-500 text-white text-sm rounded-lg hover:bg-blue-600 transition-colors"
          >
            <ExternalLink size={16} />
            Open PDF in new tab
          </a>
        </div>
      )}
      <iframe
        className={className ? "w-full h-full" : "sm:rounded-lg w-full h-[85vh] sm:h-[900px]"}
        src={pdfUrl}
        title="PDF Document"
        onLoad={() => setHasError(false)}
        onError={() => setHasError(true)}
        style={{ display: hasError ? 'none' : undefined }}
      />
    </div>
  )
}

export default DocumentPdfActivity
