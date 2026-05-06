import '../styles/globals.css'
import { getLEARNHOUSE_TOP_DOMAIN_VAL, getLEARNHOUSE_TELEMETRY_DISABLED_VAL } from '@services/config/config'
import Script from 'next/script'
import Providers from '@components/Providers'
import { Wix_Madefor_Text } from 'next/font/google'

const isDevEnv = getLEARNHOUSE_TOP_DOMAIN_VAL() === 'localhost'
const isTelemetryDisabled = getLEARNHOUSE_TELEMETRY_DISABLED_VAL() === 'true'

const wixMadeforText = Wix_Madefor_Text({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-default',
})

// Inline runtime config to avoid hydration mismatch from browser extensions
// that inject scripts into <head> before React hydrates
function getRuntimeConfigScript(): string {
  if (typeof window !== 'undefined') return ''
  try {
    const fs = require('fs')
    const path = require('path')
    const possiblePaths = [
      path.join(process.cwd(), 'runtime-config.json'),
      path.join(__dirname || process.cwd(), '..', 'runtime-config.json'),
    ]
    for (const configPath of possiblePaths) {
      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
        return `window.__RUNTIME_CONFIG__ = ${JSON.stringify(config)};`
      }
    }
  } catch { /* ignore */ }

  // Fallback: build from NEXT_PUBLIC_ env vars
  const config: Record<string, string> = {}
  Object.keys(process.env).forEach((key) => {
    if (key.startsWith('NEXT_PUBLIC_')) {
      config[key] = process.env[key] || ''
    }
  })
  return `window.__RUNTIME_CONFIG__ = ${JSON.stringify(config)};`
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const inlineRuntimeConfig = getRuntimeConfigScript()

  return (
    <html className={wixMadeforText.variable} lang="en" suppressHydrationWarning>
      <head suppressHydrationWarning>
        {/* Inline runtime config to avoid hydration mismatch from browser extensions */}
        <script dangerouslySetInnerHTML={{ __html: inlineRuntimeConfig }} />
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/embed-bg.js" />
      </head>
      <body suppressHydrationWarning>
        {
            isDevEnv ? '' : isTelemetryDisabled ? '' :
                            <Script
                                data-website-id="a1af6d7a-9286-4a1f-8385-ddad2a29fcbb"
                                src="/umami/script.js"
                            />
        }
        <Providers>
          <main className="animate-fade-in">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  )
}
