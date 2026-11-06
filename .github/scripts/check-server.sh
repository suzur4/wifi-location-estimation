#!/usr/bin/env bash
# Integration test on a disposable GitHub-hosted Ubuntu VM. This installs real units and users.
set -Eeuo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && $EUID == 0 ]]
[[ ! -e /opt/wifi-location && ! -e /etc/wifi-location ]]
checkout=$(pwd -P)
# shellcheck source=deploy/setup-server.sh
source deploy/setup-server.sh
check_system
create_user_and_dirs
cd /

# Exercise the same key generation, clone and fetch paths as the laptop, using a
# local Git remote in place of a machine-specific key enrolled on github.com.
origin=$APP_DIR/fetch/test-origin.git
git init -q --bare -b main "$origin"
git -c safe.directory="$checkout" -C "$checkout" push -q "$origin" HEAD:refs/heads/main
chown -R "$FETCH_USER:$FETCH_USER" "$origin"
as_fetch git config --global "url.file://$origin.insteadOf" "git@github-deploy:$REPO_SLUG.git"
setup_github
if runuser -u "$APP_USER" -- test -r "$APP_DIR/fetch/.ssh/github_deploy_ed25519"; then
  echo 'The web service account can read the deployment key' >&2
  exit 1
fi

# Python and UI regression tests run in their own jobs. Exercise the actual build here.
RUN_TESTS=no
write_config
install_services
trap 'journalctl -u wifi-location.service -n 30 --no-pager >&2' ERR
/usr/local/sbin/wifi-location-update
test "$(cat "$APP_DIR/current/.commit")" = "$(git -c safe.directory="$checkout" -C "$checkout" rev-parse HEAD)"
systemctl is-enabled --quiet wifi-location.service
systemctl is-active --quiet wifi-location.service
base=http://127.0.0.1:8000
get() { curl --noproxy '*' -fsS --max-time 10 "$1"; }
code() { curl --noproxy '*' -sS --max-time 10 -o /dev/null -w '%{http_code}' "$@"; }
get "$base/" | grep 'id="root"' >/dev/null
get "$base/api/research?dataset=uji" | jq -e '.dataset == "uji" and (.metrics | length > 0)' >/dev/null
test "$(code "$base/api/admin/teachers")" = 401
test "$(code -H 'Host: unexpected.example' "$base/api/teachers")" = 400

# Verify an online backup, a persistent admin change and a restore across service restarts.
snapshot=$STATE_DIR/ci-snapshot.sqlite3
runuser -u "$APP_USER" -- sqlite3 -readonly "$STATE_DIR/demo.sqlite3" ".backup $snapshot"
test "$(runuser -u "$APP_USER" -- sqlite3 -readonly "$snapshot" 'PRAGMA quick_check')" = ok
token=$(sed -n 's/^WIFI_ADMIN_TOKEN=//p' "$CONF_DIR/wifi-location.env")
test "$(code -X DELETE -H "Authorization: Bearer $token" "$base/api/admin/teachers/demo-1")" = 204
unset token
systemctl restart wifi-location.service
/usr/local/sbin/wifi-location-update
get "$base/api/teachers" | jq -e 'all(.teachers[]; .id != "demo-1")' >/dev/null
systemctl stop wifi-location.service
runuser -u "$APP_USER" -- sqlite3 "$STATE_DIR/demo.sqlite3" ".restore $snapshot"
/usr/local/sbin/wifi-location-update
get "$base/api/teachers" | jq -e 'any(.teachers[]; .id == "demo-1")' >/dev/null

# Bind the optional proxy to a test-only address on this VM.
ip link add wifitest type dummy
ip address add 192.168.237.1/30 dev wifitest
ip link set wifitest up
LAN_CIDR=192.168.237.0/30
setup_lan_proxy
lan=http://192.168.237.1:8080
page=$(get "$lan/")
asset=$(sed -n 's/.*src="\(\/assets\/[^"]*\.js\)".*/\1/p' <<< "$page")
test -n "$asset"
get "$lan$asset" >/dev/null
get "$lan/api/teachers" | jq -e '.demo == true' >/dev/null
test "$(code "$lan/api/research")" = 403
test "$(code "$lan/api/admin/teachers")" = 403
test "$(code -X POST "$lan/api/teachers")" = 403
test "$(code --interface 127.0.0.1 "$lan/api/teachers")" = 403
LAN_CIDR=
setup_lan_proxy
test ! -e /etc/nginx/conf.d/wifi-location.conf
echo 'Release, restart, backup/restore and LAN access checks passed.'
