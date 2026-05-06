#!/usr/bin/env bash
# Regression test for video playback + bandwidth-protection fix
# Verifies that:
#  1. Login succeeds with admin credentials
#  2. Backend returns 206 Partial Content for explicit Range requests (start)
#  3. Backend returns 206 for mid-file Range (seek)
#  4. Backend FORCES 206 with a ~10MB slice for no-Range GET on large files
#     (bandwidth protection — MUST NOT return 200 with full Content-Length)
#  5. Next.js frontend proxy forwards Range requests and returns 206
#  6. Next.js frontend proxy also enforces the forced-206 behavior (no full 610MB)

# Expected forced-slice cap for no-Range responses on large files
FORCED_SLICE_BYTES=10485760   # 10 MiB
FULL_FILE_BYTES=639418378     # 610 MB — this value MUST NOT appear as Content-Length

set -u

BACKEND="http://localhost:9001"
FRONTEND="http://localhost:3000"
EMAIL="admin@school.dev"
PASSWORD="learnhouse123"

# UUIDs (without prefix — the endpoint adds them)
COURSE_ID="1a118b09-032c-4b8f-ba42-3247a758fea0"
VIDEO_FILE="e2a7e02a-673a-40e4-9ddd-6e17d60d9f01.mp4"
ORG_UUID="org_a796940d-42f0-44d9-95d8-2ce6b3829bda"
ACTIVITY_UUID="a253029a-d604-4eb8-97fc-9d4717be49d4"

COOKIE_JAR="$(mktemp -t lh-cookies.XXXXXX)"
trap 'rm -f "$COOKIE_JAR"' EXIT

PASS=0
FAIL=0

log()   { printf '\033[0;36m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[0;32m[PASS]\033[0m  %s\n' "$*"; PASS=$((PASS+1)); }
fail()  { printf '\033[0;31m[FAIL]\033[0m  %s\n' "$*"; FAIL=$((FAIL+1)); }

# ------------------------------------------------------------------
# Step 1: Login and get access token + cookies
# ------------------------------------------------------------------
log "Logging in as ${EMAIL}"
LOGIN_BODY=$(mktemp); LOGIN_CODE=$(mktemp)
HTTP_CODE=$(curl -sS -o "$LOGIN_BODY" -w '%{http_code}' \
  -c "$COOKIE_JAR" \
  -X POST "${BACKEND}/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${EMAIL}" \
  --data-urlencode "password=${PASSWORD}")

if [[ "$HTTP_CODE" != "200" ]]; then
  fail "Login failed (HTTP ${HTTP_CODE})"
  cat "$LOGIN_BODY"
  echo
  echo "Login must succeed before other tests can run. Aborting."
  exit 1
fi
ok "Login returned HTTP 200"

ACCESS_TOKEN=$(sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$LOGIN_BODY")
if [[ -z "${ACCESS_TOKEN}" ]]; then
  fail "No access_token in login response"
  cat "$LOGIN_BODY"
else
  ok "Obtained access_token (${#ACCESS_TOKEN} chars)"
fi
rm -f "$LOGIN_BODY" "$LOGIN_CODE"

AUTH_HEADER="Authorization: Bearer ${ACCESS_TOKEN}"

# Stream endpoint URL format: /api/v1/stream/video/{org}/{course}/{activity}/{filename}
STREAM_PATH="/api/v1/stream/video/${ORG_UUID}/course_${COURSE_ID}/activity_${ACTIVITY_UUID}/${VIDEO_FILE}"
BACKEND_VIDEO_URL="${BACKEND}${STREAM_PATH}"
FRONTEND_VIDEO_URL="${FRONTEND}${STREAM_PATH}"

# ------------------------------------------------------------------
# Step 2: Backend Range request -> expect 206 Partial Content
# ------------------------------------------------------------------
log "Requesting first 1024 bytes from backend with Range: bytes=0-1023"
BE_HEADERS=$(mktemp); BE_BODY=$(mktemp)
BE_STATUS=$(curl -sS -o "$BE_BODY" -D "$BE_HEADERS" -w '%{http_code}' \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  -H "Range: bytes=0-1023" \
  "$BACKEND_VIDEO_URL")

if [[ "$BE_STATUS" == "206" ]]; then
  ok "Backend returned 206 Partial Content"
else
  fail "Backend did not return 206 (got ${BE_STATUS})"
  echo "--- response headers ---"; cat "$BE_HEADERS"
fi

if grep -iq '^content-range:' "$BE_HEADERS"; then
  CR=$(grep -i '^content-range:' "$BE_HEADERS" | tr -d '\r')
  ok "Backend includes ${CR}"
else
  fail "Backend missing Content-Range header"
fi

if grep -iq '^accept-ranges:[[:space:]]*bytes' "$BE_HEADERS"; then
  ok "Backend advertises Accept-Ranges: bytes"
else
  fail "Backend missing Accept-Ranges: bytes header"
fi

BE_BYTES=$(wc -c < "$BE_BODY")
if [[ "$BE_BYTES" -eq 1024 ]]; then
  ok "Backend returned exactly 1024 bytes for range 0-1023"
else
  fail "Backend returned ${BE_BYTES} bytes (expected 1024)"
fi
rm -f "$BE_HEADERS" "$BE_BODY"

# ------------------------------------------------------------------
# Step 4: Verify video file exists in MinIO (via backend content endpoint)
# MinIO requires AWS4-HMAC-SHA256 auth, so we test through the backend
# which already proxies MinIO. A successful 206 from backend confirms
# the file exists in MinIO and is retrievable.
# ------------------------------------------------------------------
log "Verifying video file exists in MinIO via backend /api/v1/content/ endpoint"
CONTENT_URL="${BACKEND}/api/v1/content/orgs/${ORG_UUID}/courses/course_${COURSE_ID}/activities/activity_${ACTIVITY_UUID}/video/${VIDEO_FILE}"
MINIO_STATUS=$(curl -sS -o /dev/null -w '%{http_code}' \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  -I "$CONTENT_URL")

if [[ "$MINIO_STATUS" == "200" ]]; then
  ok "MinIO file verified via backend /content/ endpoint (HTTP 200)"
else
  fail "MinIO file check via /content/ returned ${MINIO_STATUS}"
fi

# ------------------------------------------------------------------
# Step 5: Second Range request (middle of file) -> expect 206
# ------------------------------------------------------------------
log "Requesting bytes 2048-4095 from backend"
BE2_HEADERS=$(mktemp); BE2_BODY=$(mktemp)
BE2_STATUS=$(curl -sS -o "$BE2_BODY" -D "$BE2_HEADERS" -w '%{http_code}' \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  -H "Range: bytes=2048-4095" \
  "$BACKEND_VIDEO_URL")

if [[ "$BE2_STATUS" == "206" ]]; then
  ok "Backend returned 206 for second range"
else
  fail "Backend did not return 206 for second range (got ${BE2_STATUS})"
fi

BE2_BYTES=$(wc -c < "$BE2_BODY")
if [[ "$BE2_BYTES" -eq 2048 ]]; then
  ok "Backend returned 2048 bytes for range 2048-4095"
else
  fail "Backend returned ${BE2_BYTES} bytes for second range (expected 2048)"
fi
rm -f "$BE2_HEADERS" "$BE2_BODY"

# ------------------------------------------------------------------
# Step 6: Frontend Next.js proxy Range request -> expect 206
# ------------------------------------------------------------------
log "Requesting through frontend proxy: ${FRONTEND_VIDEO_URL}"

FE_HEADERS=$(mktemp); FE_BODY=$(mktemp)
FE_STATUS=$(curl -sS -o "$FE_BODY" -D "$FE_HEADERS" -w '%{http_code}' \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  -H "Range: bytes=0-1023" \
  -H "Origin: ${FRONTEND}" \
  -H "Referer: ${FRONTEND}/org/${ORG_UUID}/course/${COURSE_ID}/activity/${ACTIVITY_UUID}" \
  "$FRONTEND_VIDEO_URL")

if [[ "$FE_STATUS" == "206" ]]; then
  ok "Frontend proxy returned 206 Partial Content"
else
  fail "Frontend proxy did not return 206 (got ${FE_STATUS})"
  echo "--- response headers ---"; cat "$FE_HEADERS"
fi

if grep -iq '^content-range:' "$FE_HEADERS"; then
  CR=$(grep -i '^content-range:' "$FE_HEADERS" | tr -d '\r')
  ok "Frontend proxy preserves ${CR}"
else
  fail "Frontend proxy missing Content-Range header"
fi

FE_BYTES=$(wc -c < "$FE_BODY")
if [[ "$FE_BYTES" -eq 1024 ]]; then
  ok "Frontend proxy returned 1024 bytes for range 0-1023"
else
  fail "Frontend proxy returned ${FE_BYTES} bytes (expected 1024)"
fi
rm -f "$FE_HEADERS" "$FE_BODY"

# ------------------------------------------------------------------
# Step 7: ?token= query param auth (new backend feature)
# ------------------------------------------------------------------
log "Requesting via ?token= query parameter (new auth fallback)"
QT_HEADERS=$(mktemp); QT_BODY=$(mktemp)
QT_STATUS=$(curl -sS -o "$QT_BODY" -D "$QT_HEADERS" -w '%{http_code}' \
  -H "Range: bytes=0-1023" \
  "${BACKEND_VIDEO_URL}?token=${ACCESS_TOKEN}")

if [[ "$QT_STATUS" == "206" ]]; then
  ok "Backend accepted ?token= query param and returned 206"
else
  fail "Backend rejected ?token= query param (got ${QT_STATUS})"
  echo "--- response headers ---"; cat "$QT_HEADERS"
fi
rm -f "$QT_HEADERS" "$QT_BODY"

# ------------------------------------------------------------------
# Step 8: Bandwidth protection — no-Range GET on a large file
#         MUST return 206 with a capped slice (~10MB), NOT 200 with 610MB.
#         Covers both backend direct and frontend proxy.
# ------------------------------------------------------------------
check_forced_206() {
  # $1 = label, $2 = URL, $3 = headers file
  local label="$1" hdr="$3"
  local status cr clen te range_end range_total slice_bytes

  status=$(sed -n '1s/^HTTP\/[0-9.]* \([0-9]*\).*/\1/p' "$hdr" | tail -n1)
  cr=$(grep -i '^content-range:' "$hdr" | tr -d '\r' | awk '{print $2" "$3}')
  clen=$(grep -i '^content-length:' "$hdr" | tr -d '\r' | awk '{print $2}')
  te=$(grep -i '^transfer-encoding:' "$hdr" | tr -d '\r' | awk '{print tolower($2)}')

  if [[ "$status" == "206" ]]; then
    ok "${label}: forced 206 Partial Content on no-Range GET"
  else
    fail "${label}: expected 206 on no-Range GET, got ${status}"
    echo "--- response headers ---"; cat "$hdr"
    return
  fi

  if [[ -z "$cr" ]]; then
    fail "${label}: missing Content-Range on forced 206"
    return
  fi
  ok "${label}: Content-Range present (${cr})"

  # Derive slice size from Content-Range "bytes START-END/TOTAL"
  range_end=$(echo "$cr" | sed -n 's#bytes \([0-9]*\)-\([0-9]*\)/\([0-9]*\)#\2#p')
  range_total=$(echo "$cr" | sed -n 's#bytes \([0-9]*\)-\([0-9]*\)/\([0-9]*\)#\3#p')
  if [[ -n "$range_end" ]]; then
    slice_bytes=$((range_end + 1))
  fi

  if [[ "$range_total" != "$FULL_FILE_BYTES" ]]; then
    fail "${label}: Content-Range total ${range_total} != expected ${FULL_FILE_BYTES}"
  fi

  if [[ -n "$slice_bytes" && "$slice_bytes" -le "$FORCED_SLICE_BYTES" && "$slice_bytes" -gt 0 ]]; then
    ok "${label}: slice size ${slice_bytes} bytes (<= ${FORCED_SLICE_BYTES})"
  else
    fail "${label}: slice size '${slice_bytes}' outside (0, ${FORCED_SLICE_BYTES}]"
  fi

  # Content-Length: either absent (chunked transfer) OR must be capped; NEVER the full file size
  if [[ "$clen" == "$FULL_FILE_BYTES" ]]; then
    fail "${label}: Content-Length is the FULL file (${clen}) — bandwidth NOT protected"
  elif [[ -z "$clen" && "$te" == "chunked" ]]; then
    ok "${label}: Content-Length omitted (Transfer-Encoding: chunked) — capped via Content-Range"
  elif [[ -n "$clen" && "$clen" -le "$FORCED_SLICE_BYTES" && "$clen" -gt 0 ]]; then
    ok "${label}: Content-Length capped at ${clen} bytes (<= ${FORCED_SLICE_BYTES})"
  else
    fail "${label}: unexpected Content-Length '${clen}' / Transfer-Encoding '${te}'"
  fi
}

log "Backend: no-Range GET on 610MB video — expect forced 206 with ~10MB slice"
NB_HEADERS=$(mktemp)
curl -sS -o /dev/null -D "$NB_HEADERS" \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  --max-time 30 \
  "$BACKEND_VIDEO_URL" > /dev/null || true
check_forced_206 "Backend no-Range" "$BACKEND_VIDEO_URL" "$NB_HEADERS"
rm -f "$NB_HEADERS"

log "Frontend proxy: no-Range GET on 610MB video — expect forced 206 with ~10MB slice"
NF_HEADERS=$(mktemp)
curl -sS -o /dev/null -D "$NF_HEADERS" \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  -H "Origin: ${FRONTEND}" \
  -H "Referer: ${FRONTEND}/org/${ORG_UUID}/course/${COURSE_ID}/activity/${ACTIVITY_UUID}" \
  --max-time 30 \
  "$FRONTEND_VIDEO_URL" > /dev/null || true
check_forced_206 "Frontend no-Range" "$FRONTEND_VIDEO_URL" "$NF_HEADERS"
rm -f "$NF_HEADERS"

# ------------------------------------------------------------------
# Step 9: Frontend proxy sanity — explicit Range still returns 206
# ------------------------------------------------------------------
log "Frontend proxy: explicit 1MB Range must stay 206"
FULL_HEADERS=$(mktemp)
FULL_STATUS=$(curl -sS -o /dev/null -D "$FULL_HEADERS" -w '%{http_code}' \
  -b "$COOKIE_JAR" \
  -H "$AUTH_HEADER" \
  -H "Range: bytes=0-1048575" \
  --max-time 30 \
  "$FRONTEND_VIDEO_URL" || echo "timeout")

if [[ "$FULL_STATUS" == "206" ]]; then
  ok "Frontend returns 206 for explicit 1MB Range"
else
  fail "Frontend 1MB Range returned ${FULL_STATUS} (expected 206)"
fi
rm -f "$FULL_HEADERS"

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo
echo "=============================================="
echo " Video playback regression test summary"
echo "   PASS: ${PASS}"
echo "   FAIL: ${FAIL}"
echo "=============================================="

if [[ "$FAIL" -ne 0 ]]; then
  exit 1
fi
exit 0
