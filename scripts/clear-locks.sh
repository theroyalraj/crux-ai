#!/usr/bin/env bash
redis-cli DEL crux:speaker:lock crux:speaker:generation crux:speaker:thinking 2>/dev/null || true
rm -f "${TMPDIR:-/tmp}/crux-speaker-active" 2>/dev/null || true
echo "Crux locks cleared."
