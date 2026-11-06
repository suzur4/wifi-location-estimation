#!/usr/bin/env bash
# Deploy the latest commit of the configured branch from GitHub.
#
# Installed by setup-server.sh as /usr/local/sbin/wifi-location-update and run as root
# (by hand or by wifi-location-update.timer). Each commit is built in its own release
# directory as the app user; root only switches the "current" symlink and restarts the
# service. The running release is replaced only after the build and the tests pass,
# and the previous release comes back if the new one does not answer its health check.
#
#   sudo wifi-location-update             deploy if GitHub has a new commit
#   sudo wifi-location-update --force     rebuild and redeploy the newest commit
#   sudo wifi-location-update --rollback  switch back to the previous release
#   sudo wifi-location-update --status    show what is running and what GitHub has
set -Eeuo pipefail
# Without this, a failing "git fetch" inside $(...) would go unnoticed and stale refs would be deployed.
shopt -s inherit_errexit

CONFIG=${WIFI_LOCATION_DEPLOY_CONF:-/etc/wifi-location/deploy.conf}
if [[ -r $CONFIG ]]; then
  # shellcheck source=/dev/null
  . "$CONFIG"
fi

: "${APP_USER:=wifiloc}"
: "${FETCH_USER:=wifiloc-fetch}"
: "${APP_DIR:=/opt/wifi-location}"
: "${BRANCH:=main}"
: "${KEEP_RELEASES:=3}"
: "${RUN_TESTS:=yes}"
: "${SERVICE:=wifi-location.service}"
: "${HEALTH_URL:=http://127.0.0.1:8000/api/health}"
: "${PYTHON:=python3.12}"
: "${LOCK_FILE:=/run/wifi-location-update.lock}"

REPO=$APP_DIR/fetch/repo.git
RELEASES=$APP_DIR/releases
CURRENT=$APP_DIR/current
PREVIOUS=$APP_DIR/previous
release=""

log() { printf '[wifi-location-update] %s\n' "$*"; }
fail() { log "$*" >&2; exit 1; }

# Only git needs the private repository and its SSH key. Child processes must not
# retain the update lock if a build tool starts a background process.
as_fetch() { runuser -u "$FETCH_USER" -- "$@" 9>&-; }
as_app() { runuser -u "$APP_USER" -- "$@" 9>&-; }

point_link_at() {
  local link=$1 dir=$2
  # These links live in a root-owned directory. Rename within it atomically.
  ln -sfn "$dir" "$link.next"
  mv -T "$link.next" "$link"
}

linked_release() {
  local link=$1 dir
  [[ -L $link ]] || return 1
  dir=$(readlink -f "$link") || return 1
  [[ ${dir%/*} == "$RELEASES" && -d $dir ]] || return 1
  printf '%s\n' "$dir"
}

running_commit() { as_app cat "$CURRENT/.commit" 2>/dev/null || true; }

responds() {
  systemctl is-active --quiet "$SERVICE" &&
    curl --noproxy '*' -fsS --max-time 3 --max-filesize 8192 "$HEALTH_URL" 2>/dev/null |
      python3 -I -c 'import json, sys
d = json.load(sys.stdin)
sys.exit(0 if d.get("status") == "ok" and d.get("network_collectors_enabled") is False else 1)' 2>/dev/null
}

healthy() {
  local attempt
  for attempt in $(seq 1 30); do
    if responds; then
      return 0
    fi
    sleep 1
  done
  log "ヘルスチェックに ${attempt} 回とも応答がありませんでした（$HEALTH_URL）"
  return 1
}

fetch() {
  as_fetch git -C "$REPO" fetch --prune --quiet origin
  as_fetch git -C "$REPO" rev-parse --verify "refs/remotes/origin/$BRANCH^{commit}"
}

build() {
  local dir=$1
  log "Python の仮想環境を作ります"
  as_app "$PYTHON" -m venv "$dir/.venv"
  as_app "$dir/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$dir/requirements.lock"
  log "画面の依存パッケージを入れます"
  as_app npm --prefix "$dir/frontend" ci --no-audit --no-fund --loglevel=error
  if [[ $RUN_TESTS == yes ]]; then
    log "テストを実行します"
    # shellcheck disable=SC2016  # $1 belongs to the inner shell
    as_app bash -c 'cd "$1" && .venv/bin/python -m pytest -q -p no:cacheprovider' _ "$dir"
    as_app npm --prefix "$dir/frontend" test
  fi
  log "画面をビルドします"
  as_app npm --prefix "$dir/frontend" run build
  as_app test -s "$dir/frontend/dist/index.html"
  # node_modules is only needed for building; it is the largest part of a release.
  as_app rm -rf "$dir/frontend/node_modules"
}

switch_to() {
  local new=$1 previous
  previous=$(linked_release "$CURRENT" || true)
  point_link_at "$CURRENT" "$new"
  if systemctl restart "$SERVICE" && healthy; then
    [[ -z $previous ]] || point_link_at "$PREVIOUS" "$previous"
    log "切り替えました：$(basename "$new")"
    return 0
  fi
  if [[ -n $previous && -d $previous && $previous != "$new" ]]; then
    log "新しいリリースが応答しないため、$(basename "$previous") に戻します"
    point_link_at "$CURRENT" "$previous"
    if ! systemctl restart "$SERVICE" || ! healthy; then
      log "前の版も応答しません。journalctl -u $SERVICE で確認してください"
    fi
  else
    # A failed first installation must be retryable even when upstream is unchanged.
    rm -f "$CURRENT"
    systemctl stop "$SERVICE"
  fi
  return 1
}

prune() {
  local active previous dir kept=1
  active=$(linked_release "$CURRENT")
  previous=$(linked_release "$PREVIOUS" || true)
  [[ -z $previous || $previous == "$active" ]] || kept=2
  # Directory names start with a timestamp, so reverse order is newest first.
  while IFS= read -r dir; do
    [[ $dir == "$active" || $dir == "$previous" ]] && continue
    if (( kept < KEEP_RELEASES )); then
      kept=$((kept + 1))
      continue
    fi
    log "古いリリースを削除します：$(basename "$dir")"
    rm -rf -- "$dir"
  done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d | sort -r)
}

on_exit() {
  local status=$?
  if (( status != 0 )); then
    log "更新に失敗しました（終了コード $status）。詳しくは journalctl -u wifi-location-update を見てください"
    # A half-built release is removed unless it is what "current" points at.
    if [[ -n $release && -d $release && $(readlink -f "$CURRENT" 2>/dev/null) != "$release" ]]; then
      rm -rf -- "$release"
    fi
  fi
}

deploy() {
  local force=$1 target
  log "GitHub から $BRANCH を取得します"
  target=$(fetch)
  if [[ $target == "$(running_commit)" && $force != yes ]]; then
    if ! responds; then
      log "実行中の版を起動し直します"
      systemctl restart "$SERVICE"
      healthy || fail "実行中の版が応答しません"
    fi
    log "更新はありません（${target:0:7} を実行中）"
    return 0
  fi
  # Reserve a fresh directory even for a forced rebuild of the same SHA in the same second.
  release=$(mktemp -d "$RELEASES/$(date -u +%Y%m%d%H%M%S)-${target:0:7}.XXXXXX")
  chown "$APP_USER" "$release"
  log "${target:0:7} を $(basename "$release") として用意します"
  as_fetch git -C "$REPO" archive "$target" | as_app tar -xf - -C "$release"
  printf '%s\n' "$target" | as_app tee "$release/.commit" >/dev/null
  build "$release"
  switch_to "$release"
  release=""
  prune
}

main() {
  local mode=${1:-deploy}
  [[ $(id -u) -eq 0 ]] || fail "root で実行してください：sudo wifi-location-update"
  cd /
  [[ -d $REPO ]] || fail "$REPO がありません。先に setup-server.sh を実行してください"
  [[ $KEEP_RELEASES =~ ^[1-9][0-9]*$ && $KEEP_RELEASES != 1 ]] || fail "KEEP_RELEASES は2以上の整数を指定してください"
  case $mode in
    deploy | --force) ;;
    --rollback | --status) ;;
    *) fail "使い方：wifi-location-update [--force | --rollback | --status]" ;;
  esac
  # sudo may have started us in an operator's private directory.
  cd /

  if [[ $mode == --status ]]; then
    local remote
    remote=$(as_fetch git -C "$REPO" rev-parse --short "refs/remotes/origin/$BRANCH" 2>/dev/null || echo "未取得")
    log "実行中：$(basename "$(linked_release "$CURRENT" || echo なし)")（$(running_commit | cut -c1-7)）"
    log "前回取得した GitHub の $BRANCH：$remote"
    log "サービス：$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
    return 0
  fi

  exec 9>"$LOCK_FILE"
  flock -n 9 || fail "別の更新が実行中です"
  trap on_exit EXIT

  if [[ $mode == --rollback ]]; then
    local previous
    previous=$(linked_release "$PREVIOUS") || fail "戻せる以前のリリースがありません"
    switch_to "$previous"
    return 0
  fi
  deploy "$([[ $mode == --force ]] && echo yes || echo no)"
}

main "$@"
