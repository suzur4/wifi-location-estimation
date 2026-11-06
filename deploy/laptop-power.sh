#!/usr/bin/env bash
# Battery helpers for the always-on laptop server, installed by setup-server.sh as
# /usr/local/sbin/wifi-location-laptop-power. Settings: /etc/wifi-location/laptop.conf.
#
#   charge-limit  stop charging at CHARGE_LIMIT percent (asus-wmi resets it to 100 at every boot)
#   guard         during a power cut, power off cleanly below SHUTDOWN_BELOW percent
#                 (the laptop does not turn itself back on: press the power button afterwards)
set -euo pipefail

CONFIG=${WIFI_LOCATION_LAPTOP_CONF:-/etc/wifi-location/laptop.conf}
if [[ -r $CONFIG ]]; then
  # shellcheck source=/dev/null
  . "$CONFIG"
fi
: "${CHARGE_LIMIT:=80}"
: "${SHUTDOWN_BELOW:=15}"
: "${POWER_SUPPLY:=/sys/class/power_supply}"

log() { printf '[laptop-power] %s\n' "$*"; }

percent_between() {
  local value=$1 low=$2 high=$3
  [[ $value =~ ^[0-9]{1,3}$ ]] && ((10#$value >= low && 10#$value <= high))
}

charge_limit() {
  percent_between "$CHARGE_LIMIT" 50 100 || { log "CHARGE_LIMIT は 50〜100 にしてください（今: $CHARGE_LIMIT）"; return 1; }
  # asus-wmi can add the attribute a few seconds after the battery itself appears.
  local file
  for _ in $(seq 1 30); do
    compgen -G "$POWER_SUPPLY/BAT*/charge_control_end_threshold" >/dev/null && break
    sleep 1
  done
  if ! compgen -G "$POWER_SUPPLY/BAT*/charge_control_end_threshold" >/dev/null; then
    log "このPCでは充電上限を設定できません（charge_control_end_threshold がありません）"
    return 0
  fi
  for file in "$POWER_SUPPLY"/BAT*/charge_control_end_threshold; do
    echo "$CHARGE_LIMIT" > "$file"
    log "$(basename "$(dirname "$file")") の充電上限を ${CHARGE_LIMIT}% にしました"
  done
}

guard() {
  percent_between "$SHUTDOWN_BELOW" 5 50 || { log "SHUTDOWN_BELOW は 5〜50 にしてください（今: $SHUTDOWN_BELOW）"; return 1; }
  local supply battery status capacity
  # Some laptops briefly discharge even with an adapter connected.
  for supply in "$POWER_SUPPLY"/*; do
    if [[ -r $supply/online && $(cat "$supply/online") == 1 ]]; then return 0; fi
  done
  for battery in "$POWER_SUPPLY"/BAT*; do
    [[ -r $battery/status && -r $battery/capacity ]] || continue
    status=$(cat "$battery/status")
    capacity=$(cat "$battery/capacity")
    if [[ $status == Discharging ]] && percent_between "$capacity" 0 "$((10#$SHUTDOWN_BELOW))"; then
      log "停電中でバッテリー残量が ${capacity}% です。データを守るため電源を切ります"
      systemctl poweroff
      return 0
    fi
  done
}

case ${1:-} in
  charge-limit) charge_limit ;;
  guard) guard ;;
  *) echo "使い方: wifi-location-laptop-power charge-limit | guard" >&2; exit 2 ;;
esac
