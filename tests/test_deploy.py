"""Run deploy/update.sh against a local git repository with stubbed system commands.

systemctl, curl, runuser, pip/npm and the clock are replaced by small scripts, so the
release switching, rollback and cleanup logic can be checked without root or network.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "update.sh"


def modern_bash():
    # update.sh needs bash 4.4+ (inherit_errexit); macOS ships 3.2 as /bin/bash.
    for candidate in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash", shutil.which("bash")):
        if candidate and Path(candidate).exists():
            version = subprocess.run([candidate, "-c", "echo ${BASH_VERSINFO[0]}${BASH_VERSINFO[1]}"],
                                     capture_output=True, text=True).stdout.strip()
            if version.isdigit() and int(version) >= 44:
                return candidate
    return None


BASH = modern_bash()
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="needs bash 4.4+ and git")

STUBS = {
    # Pretend to be root, and run "runuser -u USER -- cmd" as the current user.
    "id": '[ "$1" = "-u" ] && echo 0 || exec /usr/bin/id "$@"',
    "runuser": 'echo "user $2 $4" >> "$STUB_STATE/calls"; shift 3; exec "$@"',
    "chown": "exit 0",
    "systemctl": '''echo "systemctl $*" >> "$STUB_STATE/calls"
if [ "$1" = restart ] && [ -f "$STUB_STATE/restart-failure" ]; then
  rm "$STUB_STATE/restart-failure"
  exit 1
fi
if [ "$1" = is-active ] && [ "$2" != --quiet ]; then echo active; fi
exit 0''',
    "curl": '''echo curl >> "$STUB_STATE/calls"
[ -e "$STUB_STATE/unhealthy" ] && exit 7
if [ -e "$STUB_STATE/other-server" ]; then echo unrelated; else
  echo '{"status":"ok","network_collectors_enabled":false}'
fi''',
    "sleep": "exit 0",
    # A clock that moves one second per call keeps release names in deploy order.
    "date": 'n=$(cat "$STUB_STATE/clock" 2>/dev/null || echo 100000); [ -f "$STUB_STATE/same-second" ] || n=$((n + 1)); echo $n > "$STUB_STATE/clock"; echo "20261106$n"',
    "fake-python": '''version=$(cat "$STUB_STATE/python-version" 2>/dev/null || echo "CPython 3.12.14")
if [ "$1 $2" = "-I -c" ]; then
  echo "$version"
elif [ "$1 $2" = "-m venv" ]; then
  mkdir -p "$3/bin"
  echo "$version" > "$3/bin/version"
  cat > "$3/bin/python" <<'SH'
#!/bin/sh
if [ "$1 $2" = "-I -c" ]; then cat "$(dirname "$0")/version"; exit; fi
if [ "$2" = pytest ] && [ -e "$STUB_STATE/tests-fail" ]; then exit 1; fi
exit 0
SH
  chmod +x "$3/bin/python"
fi''',
    "npm": '''dir=$2; shift 2
case "$1" in
  ci) mkdir -p "$dir/node_modules" ;;
  test) [ -e "$STUB_STATE/tests-fail" ] && exit 1 ;;
  run) mkdir -p "$dir/dist" && echo built > "$dir/dist/index.html" ;;
esac
exit 0''',
}
if sys.platform == "darwin":
    # GNU mv -T and flock exist on the Ubuntu server but not on macOS.
    STUBS["mv"] = '[ "$1" = "-T" ] && exec python3 -c "import os,sys; os.replace(sys.argv[1], sys.argv[2])" "$2" "$3"; exec /bin/mv "$@"'
    STUBS["flock"] = "exit 0"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def server(tmp_path):
    bin_dir, state, app = tmp_path / "bin", tmp_path / "state", tmp_path / "app"
    for directory in (bin_dir, state, app / "releases", app / "fetch"):
        directory.mkdir(parents=True)
    for name, body in STUBS.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)

    origin = tmp_path / "origin"
    (origin / "frontend").mkdir(parents=True)
    (origin / "requirements.lock").write_text("fastapi==0\n")
    (origin / "frontend/package.json").write_text("{}\n")
    git(origin, "init", "-q", "-b", "main")
    commit(origin, "first")
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(app / "fetch/repo.git")], check=True)
    git(app / "fetch/repo.git", "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")

    config = tmp_path / "deploy.conf"
    config.write_text(f"APP_USER=nobody\nAPP_DIR={app}\nKEEP_RELEASES=2\nPYTHON=fake-python\n"
                      f"LOCK_FILE={state}/lock\nHEALTH_URL=http://127.0.0.1:1/\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_STATE": str(state),
           "WIFI_LOCATION_DEPLOY_CONF": str(config), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}

    def run(*args):
        return subprocess.run([BASH, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)

    return {"run": run, "origin": origin, "app": app, "state": state, "config": config}


def commit(origin, message):
    (origin / "VERSION").write_text(message)
    git(origin, "add", "-A")
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=origin, check=True, env={
        **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})
    return git(origin, "rev-parse", "HEAD")


def current(server):
    link = server["app"] / "current"
    return link.resolve() if link.is_symlink() else None


def releases(server):
    return sorted(path.name for path in (server["app"] / "releases").iterdir())


def restarts(server):
    calls = server["state"] / "calls"
    return calls.read_text().count("systemctl restart") if calls.exists() else 0


def test_first_deploy_then_nothing_to_do(server):
    head = git(server["origin"], "rev-parse", "HEAD")
    result = server["run"]()
    assert result.returncode == 0, result.stderr + result.stdout
    assert (current(server) / ".commit").read_text().strip() == head
    assert (current(server) / "VERSION").read_text() == "first"
    assert (current(server) / "frontend/dist/index.html").exists()
    assert not (current(server) / "frontend/node_modules").exists()
    assert restarts(server) == 1
    again = server["run"]()
    assert again.returncode == 0 and "更新はありません" in again.stdout
    assert len(releases(server)) == 1 and restarts(server) == 1
    calls = (server["state"] / "calls").read_text()
    assert "user wifiloc-fetch git" in calls and "user nobody tar" in calls
    assert "user nobody git" not in calls


def test_new_commits_are_deployed_and_old_releases_pruned(server):
    for message in ("first", "second", "third"):
        if message != "first":
            commit(server["origin"], message)
        assert server["run"]().returncode == 0
    assert (current(server) / "VERSION").read_text() == "third"
    assert len(releases(server)) == 2  # KEEP_RELEASES=2: the running one and one to roll back to


def test_failing_tests_keep_the_running_release(server):
    assert server["run"]().returncode == 0
    running = current(server)
    commit(server["origin"], "broken")
    (server["state"] / "tests-fail").touch()
    result = server["run"]()
    assert result.returncode != 0 and "更新に失敗しました" in result.stdout
    assert current(server) == running
    assert len(releases(server)) == 1  # the half-built release was removed
    assert restarts(server) == 1


def test_python_patch_pin_applies_at_unchanged_commit(server):
    assert server["run"]().returncode == 0
    first = current(server)
    with server["config"].open("a") as config:
        config.write("PYTHON_REQUIRED=3.13.18\n")
    version = server["state"] / "python-version"
    for unavailable in ("CPython 3.13.17", "PyPy 3.13.18", "CPython 3.13.18rc1"):
        version.write_text(unavailable)
        failed = server["run"]()
        assert failed.returncode != 0 and "CPython 3.13.18" in failed.stderr
        assert current(server) == first and restarts(server) == 1
    version.write_text("CPython 3.13.18")
    assert server["run"]().returncode == 0
    second = current(server)
    assert second != first
    assert (second / ".commit").read_text() == (first / ".commit").read_text()
    assert server["run"]().returncode == 0 and current(server) == second
    assert server["run"]("--rollback").returncode != 0 and current(server) == second


def test_unhealthy_release_is_rolled_back(server):
    assert server["run"]().returncode == 0
    running = current(server)
    commit(server["origin"], "starts but does not answer")
    (server["state"] / "unhealthy").touch()
    result = server["run"]()
    assert result.returncode != 0 and "に戻します" in result.stdout
    assert current(server) == running
    assert len(releases(server)) == 1
    assert restarts(server) == 3  # first deploy, the bad release, and the rollback


def test_manual_rollback_and_status(server):
    assert server["run"]().returncode == 0
    first = current(server)
    commit(server["origin"], "second")
    assert server["run"]().returncode == 0
    assert current(server) != first
    assert server["run"]("--rollback").returncode == 0
    assert current(server) == first
    status = server["run"]("--status")
    assert status.returncode == 0 and first.name in status.stdout


def test_fetch_failure_is_not_hidden(server):
    assert server["run"]().returncode == 0
    commit(server["origin"], "unreachable")
    git(server["app"] / "fetch/repo.git", "remote", "set-url", "origin", str(server["origin"]) + "-missing")
    result = server["run"]()
    assert result.returncode != 0
    assert (current(server) / "VERSION").read_text() == "first"
    assert len(releases(server)) == 1


def test_unknown_option_is_refused(server):
    result = server["run"]("--deploy-everything")
    assert result.returncode != 0 and "使い方" in result.stderr


def test_restart_failure_restores_running_release(server):
    assert server["run"]().returncode == 0
    first = current(server)
    commit(server["origin"], "restart failure")
    (server["state"] / "restart-failure").touch()
    assert server["run"]().returncode != 0
    assert current(server) == first and releases(server) == [first.name]
    assert restarts(server) == 3


def test_unhealthy_first_deploy_is_retryable_at_same_commit(server):
    marker = server["state"] / "other-server"
    marker.touch()  # HTTP success from the wrong service must not pass the health check
    assert server["run"]().returncode != 0
    assert current(server) is None and not releases(server)
    marker.unlink()
    assert server["run"]().returncode == 0
    assert (current(server) / "VERSION").read_text() == "first"


def test_rebuild_in_same_second_does_not_modify_active_release(server):
    (server["state"] / "same-second").touch()
    assert server["run"]().returncode == 0
    first = current(server)
    assert server["run"]("--force").returncode == 0
    assert current(server) != first and len(releases(server)) == 2
    assert server["run"]("--rollback").returncode == 0 and current(server) == first


@pytest.mark.skipif(sys.platform != "linux", reason="tests the flock used on the Ubuntu target")
def test_overlapping_deployment_cannot_change_releases(server):
    import fcntl

    with (server["state"] / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = server["run"]()
        assert result.returncode != 0 and "別の更新" in result.stderr
        assert current(server) is None and not releases(server)


LAPTOP_POWER = ROOT / "deploy" / "laptop-power.sh"
SETUP = ROOT / "deploy" / "setup-server.sh"


@pytest.fixture
def laptop(tmp_path):
    bin_dir, power = tmp_path / "bin", tmp_path / "power_supply"
    bin_dir.mkdir()
    (power / "BAT0").mkdir(parents=True)
    for name, body in {"systemctl": 'echo "$*" >> "$STUB_STATE/calls"', "sleep": "exit 0"}.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    config = tmp_path / "laptop.conf"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_STATE": str(tmp_path),
           "WIFI_LOCATION_LAPTOP_CONF": str(config), "POWER_SUPPLY": str(power)}

    def run(command, **settings):
        config.write_text("".join(f"{key}={value}\n" for key, value in settings.items()))
        return subprocess.run([BASH, str(LAPTOP_POWER), command], env=env, capture_output=True, text=True, timeout=30)

    def battery(status=None, capacity=None, threshold=None):
        for name, value in (("status", status), ("capacity", capacity), ("charge_control_end_threshold", threshold)):
            if value is not None:
                (power / "BAT0" / name).write_text(f"{value}\n")

    calls = tmp_path / "calls"
    return {"run": run, "battery": battery, "power": power, "calls": calls}


def test_charge_limit_is_written_when_supported(laptop):
    laptop["battery"](threshold=100)
    result = laptop["run"]("charge-limit", CHARGE_LIMIT=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (laptop["power"] / "BAT0/charge_control_end_threshold").read_text().strip() == "60"


def test_charge_limit_is_skipped_without_support_and_validated(laptop):
    result = laptop["run"]("charge-limit")
    assert result.returncode == 0 and "設定できません" in result.stdout
    laptop["battery"](threshold=100)
    assert laptop["run"]("charge-limit", CHARGE_LIMIT=30).returncode != 0
    assert (laptop["power"] / "BAT0/charge_control_end_threshold").read_text().strip() == "100"


@pytest.mark.parametrize("status,capacity,powers_off", [
    ("Discharging", 10, True), ("Discharging", 15, True), ("Discharging", 40, False),
    ("Charging", 5, False), ("Not charging", 80, False),
])
def test_battery_guard_powers_off_only_during_a_power_cut(laptop, status, capacity, powers_off):
    laptop["battery"](status=status, capacity=capacity)
    assert laptop["run"]("guard", SHUTDOWN_BELOW=15).returncode == 0
    assert (laptop["calls"].exists() and "poweroff" in laptop["calls"].read_text()) is powers_off


def test_battery_guard_keeps_running_while_an_adapter_is_online(laptop):
    laptop["battery"](status="Discharging", capacity=5)
    adapter = laptop["power"] / "AC0"
    adapter.mkdir()
    (adapter / "online").write_text("1\n")
    assert laptop["run"]("guard").returncode == 0
    assert not laptop["calls"].exists()


@pytest.mark.parametrize("args,message", [
    (["--charge-limit", "30"], "50〜100"),
    (["--github-port", "8080"], "22 か 443"),
    (["--python", "python3.13"], "絶対パス"),
    (["--lan", "0.0.0.0/0"], "私設IPv4"),
    (["--lan", "192.168.1.5/24"], "私設IPv4"),
    (["--branch", "main;reboot"], "使えない文字"),
    (["--unknown"], "不明なオプション"),
])
def test_setup_rejects_bad_options_before_changing_anything(args, message):
    result = subprocess.run([BASH, str(SETUP), *args], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and message in result.stderr


def test_setup_help_lists_the_options():
    result = subprocess.run([BASH, str(SETUP), "--help"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert "--lan" in result.stdout and "--ssh-keys-only" in result.stdout and "set -E" not in result.stdout


def test_setup_selects_interpreter_for_os_and_preserves_operator_path(tmp_path):
    path = "/opt/Private installation/bin/python3.13"
    result = subprocess.run(
        [BASH, "-c", '''
source "$1"
select_server_python 24.04
[[ $PYTHON == /usr/bin/python3.12 && $PYTHON_REQUIRED == 3.12 ]]
select_server_python 26.04
[[ $PYTHON == /opt/wifi-location-python/3.13.18/bin/python3.13 && $PYTHON_REQUIRED == 3.13.18 ]]
parse_options --python "$2"
select_server_python 26.04
CONF_DIR=$3
write_config
unset PYTHON PYTHON_REQUIRED
source "$CONF_DIR/deploy.conf"
PYTHON_REQUEST=""
select_server_python 26.04
[[ $PYTHON == "$2" && $PYTHON_REQUIRED == 3.13.18 ]]
''', "_", str(SETUP), path, str(tmp_path)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('cidr', ['0.0.0.0/0', '10.0.0.1/24', '127.0.0.0/8', '172.15.0.0/16', 'fd00::/64'])
def test_lan_option_rejects_invalid_or_non_private_subnets(cidr):
    result = subprocess.run([BASH, str(SETUP), '--lan', cidr], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and '私設IPv4' in result.stderr


def test_lan_listener_requires_one_matching_local_address():
    # Simulate a laptop with Wi-Fi, a container bridge, and an IPv6 address.
    def select(addresses):
        return subprocess.run([BASH, '-c', 'source "$1"; hostname() { echo "$ADDRESSES"; }; '
                               'parse_options --lan 192.168.1.0/24; select_lan_ip', '_', str(SETUP)],
                              env={**os.environ, 'ADDRESSES': addresses}, capture_output=True, text=True, timeout=10)

    selected = select('172.17.0.1 192.168.1.23 fd00::1')
    assert selected.returncode == 0 and selected.stdout.strip() == '192.168.1.23'
    assert select('172.17.0.1').returncode != 0
    assert select('192.168.1.23 192.168.1.24').returncode != 0


def test_battery_guard_keeps_running_on_ac_or_invalid_reading(laptop):
    laptop['battery'](status='Discharging', capacity=4)
    adapter = laptop['power'] / 'AC0'
    adapter.mkdir()
    (adapter / 'online').write_text('1\n')
    assert laptop['run']('guard').returncode == 0
    assert not laptop['calls'].exists()
    (adapter / 'online').write_text('0\n')
    laptop['battery'](capacity='')
    assert laptop['run']('guard').returncode == 0
    assert not laptop['calls'].exists()
