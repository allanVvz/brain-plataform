#!/usr/bin/env bash
set -Eeuo pipefail

SWAP_FILE="${SWAP_FILE:-/swapfile-brain-ai}"
SWAP_SIZE_MB="${SWAP_SIZE_MB:-2048}"
[[ "$SWAP_FILE" == /swapfile-brain-ai ]] || { echo "Unexpected swap path" >&2; exit 2; }
[[ "$SWAP_SIZE_MB" == 2048 ]] || { echo "Only the reviewed 2 GB size is allowed" >&2; exit 2; }
if swapon --show=NAME --noheadings | grep -qx "$SWAP_FILE"; then
  echo "Swap already active: $SWAP_FILE"; exit 0
fi
[[ ! -e "$SWAP_FILE" ]] || { echo "Existing inactive swap file requires review" >&2; exit 2; }
fallocate -l "${SWAP_SIZE_MB}M" "$SWAP_FILE"
chmod 0600 "$SWAP_FILE"
mkswap "$SWAP_FILE"
swapon "$SWAP_FILE"
grep -qF "$SWAP_FILE none swap sw 0 0" /etc/fstab \
  || printf '%s\n' "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
echo "2 GB OOM-protection swap enabled; this is not capacity."
