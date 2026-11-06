#!/usr/bin/env bash
# One-time setup of the laptop server (Ubuntu Server 26.04 or 24.04 LTS).
# See docs/SERVER.md. Copy the deploy/ folder to the laptop, then run:
#
#   sudo ./deploy/setup-server.sh [options]
#
#   --lan CIDR          serve student pages on a private IPv4 subnet (nginx, port 8080)
#   --no-lan            remove this app's LAN proxy
#   --auto-update       check GitHub every 15 minutes (--no-auto-update to disable)
#   --auto-reboot       allow security updates to reboot at 04:30 local time
#   --no-auto-reboot    disable automatic reboots
#   --ssh-keys-only     disable SSH passwords after testing your own key login
#   --branch NAME       branch to deploy (default: main)
#   --python PATH       absolute path to the administrator-installed application Python
#   --github-port PORT  443 (default) or 22
#   --charge-limit N    charging limit, 50-100 percent (default: 80)
#   --wifi-workaround   disable rtw89 power saving on supported Realtek cards
#   --no-laptop         skip applying lid, sleep, battery and wireless settings
#
set -Eeuo pipefail
shopt -s inherit_errexit

REPO_SLUG=suzur4/wifi-location-estimation
APP_USER=wifiloc
FETCH_USER=wifiloc-fetch
BUILD_HOME=/var/cache/wifi-location-build
APP_DIR=/opt/wifi-location
CONF_DIR=/etc/wifi-location
STATE_DIR=/var/lib/wifi-location
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

LAN_CIDR='' LAN_IP='' AUTO_UPDATE=no AUTO_REBOOT=system KEYS_ONLY=no LAPTOP=yes WIFI_WORKAROUND=no REBOOT_NEEDED=no
BRANCH=main GITHUB_PORT=443 CHARGE_LIMIT=80 SHUTDOWN_BELOW=15 KEEP_RELEASES=3 RUN_TESTS=yes
PYTHON='' PYTHON_REQUIRED='' PYTHON_REQUEST=''

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
die() { printf 'エラー: %s\n' "$*" >&2; exit 1; }
as_fetch() { runuser -u "$FETCH_USER" -- "$@"; }
usage() { sed -n '2,/^set -Eeuo/{ /^#/s/^# \{0,1\}//p; }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

load_previous_choices() {
  # All sourced configuration lives in a root-controlled directory.
  [[ ! -L $CONF_DIR ]] || die "設定フォルダがシンボリックリンクです: $CONF_DIR"
  if [[ -e $CONF_DIR ]]; then
    require_root_directory "$CONF_DIR"
  fi
  local file
  for file in "$CONF_DIR/setup.conf" "$CONF_DIR/deploy.conf" "$CONF_DIR/laptop.conf"; do
    if [[ -e $file || -L $file ]]; then
      [[ -f $file && ! -L $file && $(stat -c '%u' "$file") == 0 && -z $(find "$file" -maxdepth 0 -perm /022 -print) ]] || die "設定ファイルの所有者・権限を確認してください: $file"
      # shellcheck source=/dev/null
      . "$file"
    fi
  done
  return 0
}

parse_options() {
  while (($#)); do
    case $1 in
      --lan) LAN_CIDR=${2:?--lan に許可するIPv4 CIDRを指定してください}; shift ;;
      --no-lan) LAN_CIDR= ;;
      --no-auto-update) AUTO_UPDATE=no ;;
      --auto-reboot) AUTO_REBOOT=yes ;;
      --wifi-workaround) WIFI_WORKAROUND=yes ;;
      --auto-update) AUTO_UPDATE=yes ;;
      --no-auto-reboot) AUTO_REBOOT=no ;;
      --ssh-keys-only) KEYS_ONLY=yes ;;
      --no-laptop) LAPTOP=no ;;
      --branch) BRANCH=${2:?--branch にブランチ名を指定してください}; shift ;;
      --python) PYTHON_REQUEST=${2:?--python にPythonの絶対パスを指定してください}; shift ;;
      --github-port) GITHUB_PORT=${2:?--github-port に 22 か 443 を指定してください}; shift ;;
      --charge-limit) CHARGE_LIMIT=${2:?--charge-limit に 50〜100 を指定してください}; shift ;;
      -h | --help) usage 0 ;;
      *) printf '不明なオプション: %s\n\n' "$1" >&2; usage 1 ;;
    esac
    shift
  done
  [[ $GITHUB_PORT == 22 || $GITHUB_PORT == 443 ]] || die "--github-port は 22 か 443 です"
  if ! [[ $CHARGE_LIMIT =~ ^([5-9][0-9]|100)$ ]]; then
    die "--charge-limit は 50〜100 です"
  fi
  [[ $BRANCH =~ ^[A-Za-z0-9_][A-Za-z0-9._/-]*$ ]] || die "ブランチ名に使えない文字があります"
  [[ -z $PYTHON_REQUEST || $PYTHON_REQUEST == /* ]] || die "--python は絶対パスで指定してください"
  if [[ -n $LAN_CIDR ]]; then
    /usr/bin/python3 -I - "$LAN_CIDR" <<'PYNET' || die "--lan には私設IPv4のネットワークCIDRを指定してください（例: 192.168.1.0/24）"
from ipaddress import IPv4Network
import sys

try:
    network = IPv4Network(sys.argv[1])
except ValueError:
    sys.exit(1)
private_ranges = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
valid = str(network) == sys.argv[1] and any(network.subnet_of(IPv4Network(block)) for block in private_ranges)
sys.exit(0 if valid else 1)
PYNET
  fi
}

select_server_python() {
  local saved_requirement=$PYTHON_REQUIRED default
  case $1 in
    26.04) PYTHON_REQUIRED=3.13.18; default=/opt/wifi-location-python/3.13.18/bin/python3.13 ;;
    24.04) PYTHON_REQUIRED=3.12; default=/usr/bin/python3.12 ;;
    *) die "対応するOSはUbuntu Server 26.04 / 24.04 LTSです" ;;
  esac
  # An in-place OS upgrade gets the new interpreter; repeated setup on the same OS keeps the selected path.
  if [[ -n $PYTHON_REQUEST ]]; then
    PYTHON=$PYTHON_REQUEST
  elif [[ -z $PYTHON || $saved_requirement != "$PYTHON_REQUIRED" ]]; then
    PYTHON=$default
  fi
}

check_system() {
  step "環境を確認します"
  [[ $(id -u) -eq 0 ]] || die "sudo で実行してください: sudo ./deploy/setup-server.sh"
  # shellcheck source=/dev/null
  . /etc/os-release
  [[ ${ID:-} == ubuntu ]] || die "Ubuntu Server 用です（この環境: ${PRETTY_NAME:-不明}）"
  select_server_python "${VERSION_ID:-}"
  require_root_directory /opt
  if [[ $VERSION_ID == 26.04 && ! -x $PYTHON ]]; then
    die "CPython $PYTHON_REQUIRED が $PYTHON に見つかりません。docs/SERVER.md の導入手順か --python /絶対パス を使ってください"
  fi
  if [[ -n $LAN_CIDR ]]; then
    command -v nginx >/dev/null || die "LAN公開には先にnginxを導入し、既存サイトとファイアウォールの公開範囲を確認してください"
    LAN_IP=$(select_lan_ip)
  fi
  note "$PRETTY_NAME / カーネル $(uname -r) / $(hostname)"
}

install_packages() {
  step "パッケージを入れます"
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q git curl ca-certificates gnupg openssh-server \
    sqlite3 linux-firmware unattended-upgrades
  if [[ $VERSION_ID == 24.04 ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3.12 python3.12-venv
    if ! dpkg-query -W -f '${Status}' linux-generic-hwe-24.04 2>/dev/null | grep -q 'ok installed'; then
      DEBIAN_FRONTEND=noninteractive apt-get install -y -q linux-generic-hwe-24.04
      REBOOT_NEEDED=yes
      note "新しいカーネル（HWE）を入れました"
    fi
  fi
  install_node
}

node_is_new_enough() {
  local version major minor
  version=$(node --version 2>/dev/null) || return 1
  version=${version#v}
  major=${version%%.*}
  minor=${version#*.}
  minor=${minor%%.*}
  # The frontend needs Node 22.12+ or 24+ (frontend/package.json "engines").
  [[ $major =~ ^[0-9]+$ && $minor =~ ^[0-9]+$ ]] && ((major == 24 || major >= 26 || (major == 22 && minor >= 12))) && command -v npm >/dev/null
}

install_node() {
  if node_is_new_enough; then
    note "Node.js $(node --version) を使います"
    return 0
  fi
  # If no supported Node is installed, use NodeSource's signed Node 24
  # repository, set up the same way as its setup_24.x script (keyring, deb822 source, pin).
  local key source
  for source in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    [[ -f $source && $source != /etc/apt/sources.list.d/wifi-location-node24.sources ]] || continue
    if grep -Fq 'deb.nodesource.com' "$source"; then
      die "既存のNodeSource設定があります。管理者がNode.js 24とnpmを導入して再実行してください"
    fi
  done
  key=$(mktemp)
  curl -fsSL --proto '=https' https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor --yes -o "$key"
  install -m 0644 "$key" /usr/share/keyrings/wifi-location-node24.gpg
  rm "$key"
  cat > /etc/apt/sources.list.d/wifi-location-node24.sources <<EOF
Types: deb
URIs: https://deb.nodesource.com/node_24.x
Suites: nodistro
Components: main
Architectures: $(dpkg --print-architecture)
Signed-By: /usr/share/keyrings/wifi-location-node24.gpg
EOF
  cat > /etc/apt/preferences.d/wifi-location-node24 <<'EOF'
Package: nodejs
Pin: origin deb.nodesource.com
Pin-Priority: 600
EOF
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q nodejs
  node_is_new_enough || die "Node.js 22.12 以上を入れられませんでした"
  note "Node.js $(node --version) を入れました"
}

require_root_directory() {
  local path=$1
  [[ -d $path && ! -L $path && $(stat -c '%u' "$path") == 0 && -z $(find "$path" -maxdepth 0 -perm /022 -print) ]] || die "root管理の実ディレクトリが必要です: $path。既存のデータ・鍵を保全し、旧構成は別の場所へ退避してください"
}

ensure_account() {
  local account=$1 home=$2 entry
  if entry=$(getent passwd "$account"); then
    [[ $(cut -d: -f3 <<< "$entry") != 0 && $(cut -d: -f6,7 <<< "$entry") == "$home:/usr/sbin/nologin" && $(id -gn "$account") == "$account" ]] \
      || die "既存ユーザー $account の設定が想定と異なります。既存の環境を確認してください"
  else
    useradd --system --user-group --home-dir "$home" --no-create-home --shell /usr/sbin/nologin "$account"
  fi
}

create_user_and_dirs() {
  step "取得用・実行用のユーザーとフォルダを用意します"
  local path
  for path in "$APP_DIR" "$APP_DIR/releases" "$CONF_DIR"; do
    if [[ -e $path || -L $path ]]; then require_root_directory "$path"; fi
  done
  for path in "$APP_DIR/fetch" "$BUILD_HOME" "$STATE_DIR"; do
    [[ ! -L $path ]] || die "シンボリックリンクにはインストールできません: $path"
  done
  ensure_account "$APP_USER" "$BUILD_HOME"
  ensure_account "$FETCH_USER" "$APP_DIR/fetch"
  install -d -o root -g root -m 0755 "$APP_DIR" "$APP_DIR/releases"
  install -d -o root -g root -m 0700 "$CONF_DIR"
  install -d -o "$APP_USER" -g "$APP_USER" -m 0700 "$BUILD_HOME"
  install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$STATE_DIR"
  install -d -o "$FETCH_USER" -g "$FETCH_USER" -m 0700 "$APP_DIR/fetch"
  as_fetch install -d -m 0700 "$APP_DIR/fetch/.ssh"
}

validate_server_python() {
  local path actual
  [[ $PYTHON == /* && -f $PYTHON && -x $PYTHON ]] || die "使用可能なPythonの絶対パスを指定してください: $PYTHON"
  PYTHON=$(realpath -e -- "$PYTHON")
  case $PYTHON in /home/*|/root/*|/run/user/*) die "systemdから読める /opt または /usr 以下へPythonを導入してください" ;; esac
  # Persist the resolved path so a subsequently retargeted alias cannot select another interpreter.
  path=$PYTHON
  while [[ $path != / ]]; do
    [[ $(stat -c '%u' "$path") == 0 && -z $(find "$path" -maxdepth 0 -perm /022 -print) ]] ||
      die "Python本体と親ディレクトリにはroot所有・グループとその他の書込禁止が必要です: $path"
    path=$(dirname "$path")
  done
  actual=$(runuser -u "$APP_USER" -- "$PYTHON" -I -c 'import ensurepip, platform, sqlite3, ssl, venv; print(platform.python_implementation(), platform.python_version())') ||
    die "アプリユーザーでPythonのSSL・SQLite・venv・ensurepipを読み込めません: $PYTHON"
  case "$PYTHON_REQUIRED:$actual" in
    '3.12:CPython 3.12.'*|'3.13.18:CPython 3.13.18') note "アプリの実行環境: $actual ($PYTHON)" ;;
    *) die "必要なPythonはCPython $PYTHON_REQUIRED です（検出: $actual / $PYTHON）" ;;
  esac
}

write_github_ssh_config() {
  local ssh=$APP_DIR/fetch/.ssh host=github.com
  [[ $GITHUB_PORT == 443 ]] && host=ssh.github.com
  # The published GitHub Ed25519 host key applies on both supported SSH ports.
  # https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
  as_fetch tee "$ssh/known_hosts_github" >/dev/null <<'EOF'
github.com,[ssh.github.com]:443 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
EOF
  as_fetch tee "$ssh/config" >/dev/null <<EOF
Host github-deploy
    HostName $host
    Port $GITHUB_PORT
    User git
    IdentityFile ~/.ssh/github_deploy_ed25519
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 10
    StrictHostKeyChecking yes
    HostKeyAlgorithms ssh-ed25519
    UserKnownHostsFile ~/.ssh/known_hosts_github
EOF
  as_fetch chmod 0600 "$ssh/config" "$ssh/known_hosts_github"
}

setup_github() {
  step "GitHub の読み取り専用デプロイキーを準備します"
  local key=$APP_DIR/fetch/.ssh/github_deploy_ed25519 repo=$APP_DIR/fetch/repo.git url="git@github-deploy:$REPO_SLUG.git"
  if ! as_fetch test -f "$key"; then
    as_fetch ssh-keygen -q -t ed25519 -N "" -C "wifi-location deploy key ($(hostname))" -f "$key"
  fi
  write_github_ssh_config
  until as_fetch git ls-remote "$url" HEAD >/dev/null; do
    note "GitHubが読み取りを許可しているか、SSHホスト鍵・接続エラーと下記の登録を確認してください。"
    note "https://github.com/$REPO_SLUG/settings/keys/new で次の公開鍵を登録します。Allow write access はオフです。"
    as_fetch cat "$key.pub"
    [[ -t 0 ]] || die "登録後、同じコマンドをもう一度実行してください"
    read -r -p "登録したら Enter で再試行（中止は Ctrl+C）: " _
  done
  as_fetch git check-ref-format --branch "$BRANCH" >/dev/null || die "不正なブランチ名: $BRANCH"
  if ! as_fetch test -d "$repo"; then as_fetch git clone --quiet --bare "$url" "$repo"; fi
  as_fetch git -C "$repo" config remote.origin.url "$url"
  as_fetch git -C "$repo" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
  as_fetch git -C "$repo" fetch --quiet --prune origin
  as_fetch git -C "$repo" rev-parse --verify --quiet "refs/remotes/origin/$BRANCH^{commit}" >/dev/null \
    || die "GitHub にブランチ $BRANCH が見つかりません"
}

write_config() {
  step "設定ファイルを書きます（$CONF_DIR）"
  local env=$CONF_DIR/wifi-location.env hosts="127.0.0.1,localhost,[::1]"

  if [[ ! -f $env ]]; then
    local token
    token=$(/usr/bin/python3 -I -c 'import secrets; print(secrets.token_urlsafe(32))')
    install -m 0600 /dev/null "$env"
    cat > "$env" <<EOF
# Managed by deploy/setup-server.sh. Read by wifi-location.service.
# The token opens the admin screen: keep it secret (sudo grep TOKEN $env).
WIFI_ADMIN_TOKEN=$token
WIFI_DB_PATH=$STATE_DIR/demo.sqlite3
WIFI_RETENTION_SECONDS=3600
WIFI_ALLOWED_HOSTS=$hosts
EOF
    note "管理トークンを作りました（sudo grep TOKEN $env で確認できます）"
  else
    [[ ! -L $env && $(stat -c '%u:%a' "$env") == 0:600 ]] || die "管理トークンのファイルをroot:0600にしてください: $env"
    grep -Eq '^WIFI_ADMIN_TOKEN=[!-~]{16,}$' "$env" || die "管理環境ファイルに固定トークンを設定してください: $env"
    note "管理トークンとデータの場所は前回のまま使います"
  fi
  cat > "$CONF_DIR/setup.conf" <<EOF
LAN_CIDR=$LAN_CIDR
AUTO_UPDATE=$AUTO_UPDATE
AUTO_REBOOT=$AUTO_REBOOT
KEYS_ONLY=$KEYS_ONLY
LAPTOP=$LAPTOP
WIFI_WORKAROUND=$WIFI_WORKAROUND
GITHUB_PORT=$GITHUB_PORT
CHARGE_LIMIT=$CHARGE_LIMIT
EOF
  cat > "$CONF_DIR/deploy.conf" <<EOF
# Managed by deploy/setup-server.sh. Read by /usr/local/sbin/wifi-location-update.
BRANCH=$BRANCH
KEEP_RELEASES=$KEEP_RELEASES
RUN_TESTS=$RUN_TESTS
PYTHON=$(printf '%q' "$PYTHON")
PYTHON_REQUIRED=$PYTHON_REQUIRED
EOF
}

install_services() {
  step "サービスを登録します"
  install -m 0755 "$HERE/update.sh" /usr/local/sbin/wifi-location-update
  install -m 0644 "$HERE/systemd/wifi-location.service" "$HERE/systemd/wifi-location-update.service" \
    "$HERE/systemd/wifi-location-update.timer" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable wifi-location.service
}

configure_update_timer() {
  if [[ $AUTO_UPDATE == yes ]]; then
    systemctl enable --now wifi-location-update.timer
    note "15分ごとに GitHub の $BRANCH を確認して自動で更新します"
  else
    systemctl disable --now wifi-location-update.timer 2>/dev/null || true
    note "更新は手動です: sudo wifi-location-update"
  fi
}

realtek_wifi_present() {
  # PCI IDs of the RTL8852BE (b852, b85b) and RTL8852BE-VT (b520), both driven by rtw89.
  local device
  for device in /sys/bus/pci/devices/*; do
    [[ $(cat "$device/vendor" 2>/dev/null) == 0x10ec ]] || continue
    case $(cat "$device/device" 2>/dev/null) in
      0xb852 | 0xb85b | 0xb520) return 0 ;;
    esac
  done
  return 1
}

install_if_changed() {
  # Installs a config file; succeeds only if it was new or different (so a reboot is needed).
  local source=$1 target=$2
  if [[ -f $target ]] && cmp -s "$source" "$target"; then
    return 1
  fi
  install -D -m 0644 "$source" "$target"
}

laptop_settings() {
  step "ノートPCをサーバーとして動かす設定をします"
  if install_if_changed "$HERE/conf/logind-lid.conf" /etc/systemd/logind.conf.d/wifi-location-server.conf; then
    REBOOT_NEEDED=yes
  fi
  install -D -m 0644 "$HERE/conf/sleep-nosuspend.conf" /etc/systemd/sleep.conf.d/wifi-location-server.conf
  systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1
  note "ふたを閉じても止まらず、スリープもしません"

  cat > "$CONF_DIR/laptop.conf" <<EOF
# Managed by deploy/setup-server.sh. Read by wifi-location-laptop-power.
CHARGE_LIMIT=$CHARGE_LIMIT
SHUTDOWN_BELOW=$SHUTDOWN_BELOW
EOF
  install -m 0755 "$HERE/laptop-power.sh" /usr/local/sbin/wifi-location-laptop-power
  install -m 0644 "$HERE/systemd/battery-charge-limit.service" "$HERE/systemd/battery-guard.service" \
    "$HERE/systemd/battery-guard.timer" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable battery-charge-limit.service >/dev/null 2>&1
  systemctl enable --now battery-guard.timer >/dev/null 2>&1
  if systemctl restart battery-charge-limit.service; then
    note "$(journalctl -u battery-charge-limit.service -n 1 -o cat 2>/dev/null || true)"
  fi
  note "停電でバッテリーが ${SHUTDOWN_BELOW}% 以下になったら自動で電源を切ります"

  if [[ $WIFI_WORKAROUND == yes ]] && realtek_wifi_present; then
    if install_if_changed "$HERE/conf/rtw89-stable.conf" /etc/modprobe.d/70-wifi-location-rtw89.conf; then
      update-initramfs -u >/dev/null 2>&1 || note "update-initramfs に失敗しました（再起動後に設定を確認してください）"
      REBOOT_NEEDED=yes
    fi
    note "Realtek RTL8852BE の省電力機能を切りました（Wi-Fi の切断対策）"
  fi

}

security_settings() {
  step "セキュリティ更新を設定します"
  # Keep the administrator's existing reboot policy until explicitly configured.
  if [[ $AUTO_REBOOT != system ]]; then
    local reboot=false
    [[ $AUTO_REBOOT == yes ]] && reboot=true
    cat > /etc/apt/apt.conf.d/52wifi-location-auto-reboot <<EOF
// Managed by deploy/setup-server.sh
Unattended-Upgrade::Automatic-Reboot "$reboot";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
EOF
  fi
  if [[ $AUTO_REBOOT == yes ]]; then
    note "再起動が必要なセキュリティ更新は、04:30 に自動で再起動して適用します"
  fi

  if [[ $KEYS_ONLY == yes ]]; then
    local operator=${SUDO_USER:-} home target=/etc/ssh/sshd_config.d/10-wifi-location.conf
    [[ -n $operator && $operator != root ]] || die "鍵でログインできる一般ユーザーから sudo で実行してください"
    home=$(getent passwd "$operator" | cut -d: -f6)
    runuser -u "$operator" -- ssh-keygen -lf "$home/.ssh/authorized_keys" >/dev/null || die "$operator の authorized_keys に公開鍵がありません"
    if [[ ! -e $target ]]; then
      cat > "$target" <<'EOF'
# Managed by deploy/setup-server.sh. Set only after verifying administrator key login.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
      if ! sshd -t; then rm "$target"; die "SSH 設定の検証に失敗し、変更を取り消しました"; fi
      systemctl try-reload-or-restart ssh.service
    fi
  fi
}

# Only accept a single IPv4 address of this machine in the explicitly requested subnet.
select_lan_ip() {
  hostname -I | /usr/bin/python3 -I -c 'import sys, ipaddress
network = ipaddress.IPv4Network(sys.argv[1])
ips = [ip for ip in sys.stdin.read().split() if ipaddress.ip_address(ip) in network]
if len(ips) != 1:
    sys.exit("指定したCIDRでサーバーのIPv4アドレスを1つだけ特定できません。ip -4 addr と --lan を確認してください")
print(ips[0])' "$LAN_CIDR"
}

setup_lan_proxy() {
  local conf=/etc/nginx/conf.d/wifi-location.conf temp old
  if [[ -e $conf || -L $conf ]]; then
    [[ -f $conf && ! -L $conf && $(head -n1 "$conf") == '# Managed by deploy/setup-server.sh.' ]] || die "既存の $conf はこのアプリの管理外です"
  elif [[ -z $LAN_CIDR ]]; then
    return 0
  fi
  command -v nginx >/dev/null || die "LAN公開にはUbuntuのnginxを先に導入し、既存サイトとファイアウォールの公開範囲を確認してください"
  old=$(mktemp)
  if [[ -f $conf ]]; then cp "$conf" "$old"; fi
  if [[ -n $LAN_CIDR ]]; then
    LAN_IP=$(select_lan_ip)
    temp=$(mktemp)
    sed -e "s|__LAN_IP__|$LAN_IP|g" -e "s|__LAN_CIDR__|$LAN_CIDR|g" "$HERE/nginx/wifi-location.conf" > "$temp"
    install -m 0644 "$temp" "$conf"
    rm "$temp"
  else
    rm "$conf"
  fi
  if ! nginx -t -q || ! systemctl reload-or-restart nginx; then
    if [[ -s $old ]]; then install -m 0644 "$old" "$conf"; else rm -f "$conf"; fi
    rm "$old"
    die "nginx の反映に失敗したため、専用設定を元に戻しました"
  fi
  rm "$old"
  if [[ -n $LAN_CIDR ]]; then
    note "生徒用: http://$LAN_IP:8080/ （許可: $LAN_CIDR）。必要に応じて sudo ufw allow from $LAN_CIDR to $LAN_IP port 8080 proto tcp"
  fi
}

first_deploy() {
  step "GitHub の $BRANCH を取得して起動します（初回は数分かかります）"
  # Deploys only when nothing is running yet or GitHub has a newer commit.
  /usr/local/sbin/wifi-location-update
  # A re-run of this script may have changed the environment file, so restart to apply it.
  systemctl restart wifi-location.service
  curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 --max-time 3 \
    --noproxy '*' http://127.0.0.1:8000/api/health >/dev/null
}

summary() {
  step "完了しました"
  local address
  address=$(hostname -I 2>/dev/null | awk '{print $1}')
  cat <<EOF
   状態の確認   : sudo wifi-location-update --status
   ログ        : journalctl -u wifi-location -f
   手動で更新   : sudo wifi-location-update
   前の版に戻す : sudo wifi-location-update --rollback
   管理トークン : sudo grep TOKEN $CONF_DIR/wifi-location.env
   自分のPCから : ssh -L 8000:127.0.0.1:8000 <ユーザー名>@${address:-<このPCのIPアドレス>} を実行してから
                  http://127.0.0.1:8000/ を開く（管理画面もこの方法で使う）
EOF
  if [[ $REBOOT_NEEDED == yes ]]; then
    printf '\n   カーネル・Wi-Fi・ふたの設定を反映するため、再起動してください: sudo reboot\n'
  fi
}

main() {
  load_previous_choices
  parse_options "$@"
  check_system
  # The bootstrap may be in an operator's private home; service accounts need an accessible cwd.
  cd /
  install_packages
  create_user_and_dirs
  validate_server_python
  setup_github
  write_config
  install_services
  if [[ $LAPTOP == yes ]]; then
    laptop_settings
  fi
  security_settings
  setup_lan_proxy
  first_deploy
  configure_update_timer
  summary
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
