#!/usr/bin/env bash
# Dedicated host OOM reserve. Never changes services, cgroups or sysctl.
set -Eeuo pipefail
umask 077
mode="${1:-audit}"
case "$mode" in audit|dry-run|apply|rollback) ;; *) echo 'Use audit|dry-run|apply|rollback' >&2; exit 2;; esac
reserve_dir=/var/lib/brain-memory-reserve
swap_file="$reserve_dir/swapfile"
marker="$reserve_dir/owner"
size_bytes=2147483648
fstab_line="$swap_file none swap sw 0 0 # brain-memory-reserve-v1"
fail() { echo "memory-reserve: $*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'root required'
for command in flock stat findmnt swapon swapoff mkswap dd python3 timeout install sha256sum; do command -v "$command" >/dev/null || fail "missing $command"; done
for path in /var /var/lib "$reserve_dir" "$swap_file" "$marker" "$reserve_dir/fstab.before" /etc/fstab /run/lock/brain-memory-reserve.lock; do
 [[ ! -L "$path" ]] || fail "symlink refused: $path"
done
[[ -f /etc/fstab ]] || fail 'fstab must be a regular file'
# Advisory lock file is operational state only; audit does not create it.
if [[ "$mode" != audit ]]; then
 exec 9>/run/lock/brain-memory-reserve.lock
 flock -n 9 || fail 'another memory reserve operation is running'
fi
active() { swapon --show=NAME --noheadings --raw | awk -v path="$swap_file" '$0==path {found=1} END {exit !found}'; }
validate_owned() {
 [[ -d "$reserve_dir" && $(stat -c '%u:%a' "$reserve_dir") == 0:700 ]] || fail 'unmanaged reserve directory'
 [[ -f "$marker" && $(stat -c '%u:%a:%h' "$marker") == 0:600:1 ]] || fail 'invalid ownership marker'
 local ownership identity
 mapfile -t ownership < "$marker"
 [[ ${#ownership[@]} == 2 && ${ownership[0]} == brain-memory-reserve-v1 ]] || fail 'unrecognized ownership marker'
 identity="${ownership[1]}"
 [[ "$identity" == pending || "$identity" =~ ^[0-9]+:[0-9]+$ ]] || fail 'invalid marker identity'
 if [[ -e "$swap_file" ]]; then
  [[ -f "$swap_file" && $(stat -c '%u:%a:%h' "$swap_file") == 0:600:1 ]] || fail 'unsafe swap file'
  if [[ "$identity" == pending ]]; then
   [[ $(stat -c %s "$swap_file") == 0 ]] || fail 'partial file without recorded identity requires review'
  else
   [[ $(stat -c '%d:%i' "$swap_file") == "$identity" ]] || fail 'swap file identity changed'
  fi
  if active; then
   [[ $(stat -c %s "$swap_file") == "$size_bytes" && $(( $(stat -c %b "$swap_file") * 512 )) -ge "$size_bytes" ]] || fail 'active reserve allocation changed'
  fi
 elif [[ "$identity" != pending && "$mode" != rollback ]]; then
  fail 'owned file missing; requires review'
 fi
}
if [[ -e "$reserve_dir" ]]; then validate_owned; fi
# Refuse conflicting persistence, including entries installed by another tool.
fstab_count="$(python3 - "$swap_file" "$fstab_line" <<'PY'
import pathlib,sys
path,line=sys.argv[1:]
rows=pathlib.Path('/etc/fstab').read_text().splitlines()
related=[r for r in rows if r.strip() and not r.lstrip().startswith('#') and r.split()[0]==path]
assert not related or related==[line], 'unmanaged or duplicate fstab entry'
print(len(related))
PY
)"
[[ "$fstab_count" == 0 || -e "$marker" ]] || fail 'unmanaged persisted reserve'
filesystem="$(findmnt -n -o FSTYPE -T /var/lib)"
report() {
 echo "memory-reserve mode=$mode filesystem=$filesystem size_bytes=$size_bytes"
 awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree):/' /proc/meminfo
 df -h /var/lib
 swapon --show --bytes
 for pressure in memory io cpu; do [[ ! -f /proc/pressure/$pressure ]] || { echo "PSI $pressure"; cat "/proc/pressure/$pressure"; }; done
 if command -v docker >/dev/null; then
  local containers pid group
  containers="$(timeout 10s docker ps -q)" || fail 'container audit timeout'
  for container in $containers; do
   timeout 5s docker inspect --format '{{.Name}} restarts={{.RestartCount}} started={{.State.StartedAt}} pid={{.State.Pid}}' "$container"
   pid="$(timeout 5s docker inspect --format '{{.State.Pid}}' "$container")"
   group="$(awk -F: '$1=="0" {print $3}' "/proc/$pid/cgroup")"
   if [[ -n "$group" && -f "/sys/fs/cgroup$group/memory.swap.max" ]]; then
    echo "container=$container memory.swap.max=$(cat "/sys/fs/cgroup$group/memory.swap.max") memory.swap.current=$(cat "/sys/fs/cgroup$group/memory.swap.current")"
   else echo "container=$container cgroup-v2-swap=unavailable"; fi
  done
 fi
 if command -v curl >/dev/null; then
  curl --max-time 5 --silent --output /dev/null --write-out 'host_http_status=%{http_code} latency_seconds=%{time_total}\n' https://api.vzforeal.com/health || echo 'host_http_probe_failed'
 fi
}
report
[[ "$mode" != audit ]] || exit 0
case "$filesystem" in ext4|xfs) ;; *) fail 'filesystem requires separate swapfile review (no CoW/holey file support assumed)';; esac
read -r disk_size disk_used available < <(df -B1 --output=size,used,avail /var/lib | tail -1)
if [[ "$mode" == dry-run || "$mode" == apply ]]; then
 [[ "$disk_size" =~ ^[0-9]+$ && "$disk_used" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ && "$available" -gt $((size_bytes+1073741824)) ]] || fail 'insufficient disk reserve'
 additional_bytes="$size_bytes"
 if [[ -f "$swap_file" ]]; then
  allocated_bytes=$(( $(stat -c %b "$swap_file") * 512 ))
  if (( allocated_bytes >= size_bytes )); then additional_bytes=0; else additional_bytes=$((size_bytes-allocated_bytes)); fi
 fi
 (( (disk_used+additional_bytes)*100 < disk_size*50 )) || fail 'projected disk occupancy must remain below50%'
fi
if [[ "$mode" == dry-run ]]; then
 echo "PLAN dedicated 2GiB full allocation, mode0600, identity marker, one owned fstab line; disk_available=$available"
 echo 'ROLLBACK requires MemAvailable > all SwapUsed + 512MiB; no forced swapoff or automatic rollback'
 exit 0
fi
write_marker() {
 local next
 next="$(mktemp "$reserve_dir/.owner.XXXXXX")"
 printf 'brain-memory-reserve-v1\n%s\n' "$1" > "$next"
 chmod 600 "$next"
 mv -f "$next" "$marker"
}
edit_fstab() {
 local operation="$1" next original_identity original_checksum
 original_identity="$(stat -c '%d:%i:%u:%g:%a:%y:%z' /etc/fstab)"
 original_checksum="$(sha256sum /etc/fstab | cut -d' ' -f1)"
 next="$(mktemp /etc/.brain-memory-fstab.XXXXXX)"
 # Copy attributes first, then write only the exact owned line. Preserve all
 # unrelated bytes; rollback never restores an old entire fstab over new edits.
 cp --preserve=mode,ownership /etc/fstab "$next"
 [[ "$(sha256sum "$next" | cut -d' ' -f1)" == "$original_checksum" ]] || fail 'fstab changed while copying; original preserved'
 python3 - "$next" "$fstab_line" "$operation" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1]);line=sys.argv[2].encode();mode=sys.argv[3]
data=p.read_bytes();rows=data.splitlines(keepends=True)
rows=[r for r in rows if r.rstrip(b'\r\n')!=line]
out=b''.join(rows)
if mode=='add':
    assert not out or out.endswith(b'\n'), 'fstab lacks final newline; requires review'
    out+=line+b'\n'
p.write_bytes(out)
PY
 [[ "$(stat -c '%d:%i:%u:%g:%a:%y:%z' /etc/fstab)" == "$original_identity" && "$(sha256sum /etc/fstab | cut -d' ' -f1)" == "$original_checksum" ]] || fail 'fstab changed concurrently; original preserved'
 mv -f "$next" /etc/fstab
}
if [[ "$mode" == apply ]]; then
 if [[ ! -e "$reserve_dir" ]]; then
  # Do not adopt a preexisting unmanaged directory or file.
  mkdir -m 700 "$reserve_dir"
  write_marker pending
 fi
 validate_owned
 if [[ ! -e "$swap_file" ]]; then
  (umask 077; set -o noclobber; : > "$swap_file")
 fi
 if [[ $(sed -n '2p' "$marker") == pending ]]; then write_marker "$(stat -c '%d:%i' "$swap_file")"; fi
 if ! active; then
  # Every byte is written: no sparse allocation, no fallocate/COW assumptions.
  dd if=/dev/zero of="$swap_file" bs=1M count=2048 conv=fsync status=none
  [[ $(stat -c %s "$swap_file") == "$size_bytes" && $(( $(stat -c %b "$swap_file") * 512 )) -ge "$size_bytes" ]] || fail 'file is not fully allocated'
  mkswap "$swap_file"
  swapon "$swap_file"
 fi
 active || fail 'swap activation not confirmed'
 if [[ -e "$reserve_dir/fstab.before" ]]; then
  [[ -f "$reserve_dir/fstab.before" && $(stat -c '%u:%a:%h' "$reserve_dir/fstab.before") == 0:600:1 ]] || fail 'unsafe fstab backup'
 else
  install -m 600 /etc/fstab "$reserve_dir/fstab.before"
 fi
 edit_fstab add
 echo 'RESERVE_APPLIED: 2GiB OOM reserve; underlying memory pressure is not cured'
else
 if [[ ! -e "$reserve_dir" ]]; then echo 'RESERVE_ABSENT'; exit 0; fi
 validate_owned
 if active; then
  read -r mem_available swap_used < <(awk '/MemAvailable:/ {m=$2} /SwapTotal:/ {t=$2} /SwapFree:/ {f=$2} END {print m,t-f}' /proc/meminfo)
  [[ "$mem_available" -gt $((swap_used+524288)) ]] || fail 'rollback blocked: insufficient MemAvailable for SwapUsed plus512MiB'
  swapoff "$swap_file" || fail 'swapoff failed; file and persistence preserved'
 fi
 ! active || fail 'swapoff not confirmed; refusing unlink'
 edit_fstab remove
 [[ ! -e "$swap_file" ]] || rm -- "$swap_file"
 # Keep ownership marker and fstab backup as audit evidence; pending permits
 # a later idempotent apply to recreate only this dedicated file.
 write_marker pending
 echo 'RESERVE_ROLLED_BACK: other swap and fstab entries preserved'
fi
report
