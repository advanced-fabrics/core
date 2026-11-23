#!/bin/sh
set -eu

WINDOW_SECONDS=${SERVICE_TRAFFIC_WINDOW_SECONDS:-15}
# /var/run is an absolute host symlink to /run. Inside the host-root mount,
# address the real path so the symlink cannot escape back into the container.
SOCKET=/host/run/cilium/hubble.sock
TARGET=${SERVICE_TRAFFIC_TARGET:-/status/service-traffic.json}
SOURCE_EPOCH=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# A crashed older collector may have left its whole-window scratch file.
rm -f "${TARGET}.ndjson.tmp"

while :; do
  started_epoch=$(date +%s)
  counts="${TARGET}.counts.tmp"
  exit_status="${TARGET}.exit.tmp"
  rm -f "${counts}" "${exit_status}"
  parser_rc=0
  # Consume one JSON event at a time. Never materialize or retain a complete
  # flow window: node traffic rate must not determine collector heap size.
  {
    producer_rc=0
    timeout "${WINDOW_SECONDS}" hubble observe --server "unix://${SOCKET}" --follow \
      --output jsonpb --all-namespaces --traffic-direction ingress --verdict FORWARDED 2>/dev/null || producer_rc=$?
    printf '%s\n' "${producer_rc}" >"${exit_status}"
  } | jq -n 'reduce inputs as $event ({flowEvents:0,requests:0};
      if ($event | type) != "object" then error("unsupported Hubble event")
      elif $event.lost_events != null or $event.lostEvents != null then
        error("incomplete Hubble stream")
      elif $event.flow != null then
        if ($event.flow | type) != "object" then error("invalid Hubble flow")
        else .flowEvents += 1 |
          if $event.flow.l7.http == null then .
          elif $event.flow.l7.type == "REQUEST" or $event.flow.l7.type == 1 then .requests += 1
          elif (["RESPONSE","SAMPLE",2,3] | index($event.flow.l7.type)) != null then .
          else error("unknown HTTP flow type") end
        end
      elif $event.node_status != null or $event.nodeStatus != null then .
      else error("unsupported Hubble event") end)' >"${counts}" || parser_rc=$?
  rc=$(cat "${exit_status}" 2>/dev/null || printf '255')
  ended=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  ended_epoch=$(date +%s)
  duration=$((ended_epoch - started_epoch))
  # 124 is a deliberately completed follow window. A malformed/incomplete
  # stream must leave the previous observation to expire, never publish zero.
  if [ "${rc}" -eq 124 ] && [ "${parser_rc}" -eq 0 ] && [ "${duration}" -gt 0 ]; then
    jq -cn --arg node "${NODE_NAME}" --arg observedAt "${ended}" --arg sourceEpoch "${SOURCE_EPOCH}" \
      --argjson windowSeconds "${duration}" --slurpfile totals "${counts}" \
      '{schemaVersion:"networking.re8ch.com/service-traffic-window-v1alpha1",observedAt:$observedAt,
        windowSeconds:$windowSeconds,sourceEpoch:$sourceEpoch,collector:"node-local Hubble Unix socket",
        samples:[{node:$node,receivedFlowEvents:$totals[0].flowEvents,requests:$totals[0].requests,observationPlane:"hubble",
          availableDimensions:["flowEvents","requests"]}]}' >"${TARGET}.tmp"
    mv "${TARGET}.tmp" "${TARGET}"
  fi
  rm -f "${counts}" "${exit_status}"
  [ "${rc}" -eq 124 ] || sleep "${WINDOW_SECONDS}"
done
