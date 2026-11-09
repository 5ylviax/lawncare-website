#!/usr/bin/env python3
"""Install the Ubuntu pull deployer for the Lawn Care GitHub Actions release."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path, PurePosixPath

APP = "lawncare.service"
JOB = "lawncare-pull.service"
TIMER = "lawncare-pull.timer"
BASE = Path("/srv/lawncare-pull")
CONFIG = Path("/etc/lawncare-pull.json")
PROGRAM = Path("/usr/local/sbin/lawncare-pull.py")
UNITS = Path("/etc/systemd/system")
DROP_IN = UNITS / (APP + ".d") / "90-release-pull.conf"
ARTIFACT = "lawncare.tar.gz"
HEALTH_URL = "http://127.0.0.1:4000/"


def systemctl(*args):
    return subprocess.run(["systemctl", *args], check=True, text=True)


def property_value(name):
    return subprocess.check_output(
        ["systemctl", "show", APP, "-p", name, "--value"], text=True
    ).strip()


def healthy():
    for _ in range(10):
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
                if response.status == 200 and property_value("SubState") == "running":
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def get_release(repo):
    endpoint = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(
        endpoint, headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    tag = release["tag_name"]
    if not re.fullmatch(r"deploy-[0-9]+-[0-9]+", tag):
        raise ValueError("Latest GitHub release is missing the expected deploy tag.")
    for asset in release["assets"]:
        if asset["name"] == ARTIFACT:
            url = f"https://github.com/{repo}/releases/download/{tag}/{ARTIFACT}"
            digest = asset.get("digest") or ""
            if re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                return tag, url, digest.removeprefix("sha256:")
            raise ValueError("The release asset has no SHA-256 digest yet.")
    raise ValueError(f"Latest GitHub release does not contain {ARTIFACT}.")


def unpack(package, stage):
    with tarfile.open(package, "r:gz") as archive:
        for item in archive.getmembers():
            path = PurePosixPath(item.name)
            if (
                path.is_absolute()
                or not path.parts
                or ".." in path.parts
                or path.parts[0] not in {"lawncare-server", "static", "templates"}
                or not (item.isdir() or item.isfile())
            ):
                raise ValueError(f"Unexpected archive entry: {item.name!r}")
        archive.extractall(stage, filter="data")
    if (
        not (stage / "lawncare-server").is_file()
        or not os.access(stage / "lawncare-server", os.X_OK)
        or not all((stage / name).is_dir() for name in ("static", "templates"))
    ):
        raise ValueError("The package is missing the executable, static files, or templates.")


def switch(target):
    temporary = BASE / "next"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(BASE / "current")


def deploy():
    settings = json.loads(CONFIG.read_text())
    tag, url, expected_digest = get_release(settings["repo"])
    current = (BASE / "current").resolve(strict=True)
    release = BASE / tag
    rejected = BASE / (tag + ".rejected")
    if current == release or rejected.exists():
        print(f"{tag} is already installed or was rolled back.")
        return
    if release.exists():
        raise ValueError(f"{release} already exists. Inspect it before retrying deployment.")

    with tempfile.TemporaryDirectory(dir=BASE) as work:
        package = Path(work) / ARTIFACT
        checksum = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=30) as response, package.open("wb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                checksum.update(chunk)
                output.write(chunk)
        if checksum.hexdigest() != expected_digest:
            raise ValueError("Release checksum mismatch. The live site was left alone.")
        stage = Path(work) / "site"
        stage.mkdir(mode=0o755)
        unpack(package, stage)
        # Keep the original private file outside all downloaded releases.
        env_file = Path(settings["original_directory"]) / ".env"
        if env_file.is_file():
            (stage / ".env").symlink_to(env_file)
        stage.rename(release)

    switch(release)
    try:
        systemctl("restart", APP)
        if not healthy():
            raise RuntimeError("New release failed the local health check.")
    except (OSError, subprocess.CalledProcessError, RuntimeError):
        rejected.touch()
        switch(current)
        systemctl("restart", APP)
        if not healthy():
            raise RuntimeError("The previous release also failed its health check.")
        print(f"Restored the previous release after {tag} failed.", file=sys.stderr)
        raise
    print(f"Installed {tag}. The site returned HTTP 200.")


def install(repo):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Supply the GitHub repository as OWNER/lawncare-website.")
    for path in (BASE, CONFIG, PROGRAM, DROP_IN, UNITS / JOB, UNITS / TIMER):
        if os.path.lexists(path):
            raise ValueError(f"{path} already exists. Existing deployment setup was preserved.")
    tag, _, _ = get_release(repo)
    print(f"Found GitHub release {tag}.")

    user = property_value("User")
    workdir = Path(property_value("WorkingDirectory"))
    binary = workdir / "lawncare-server"
    command = property_value("ExecStart")
    argv = re.search(r"argv\[\]=(.*?)\s*;\s*ignore_errors=", command)
    if (
        user in ("", "0", "root")
        or not workdir.is_absolute()
        or not binary.is_file()
        or not argv
        or argv.group(1).strip() != str(binary)
    ):
        raise ValueError("Expected a non-root lawncare.service running lawncare-server from its working directory.")
    if not healthy():
        raise RuntimeError("The existing website service must be running and returning HTTP 200.")

    BASE.mkdir(mode=0o755)
    (BASE / "current").symlink_to(workdir)
    CONFIG.write_text(json.dumps({"repo": repo, "original_directory": str(workdir)}) + "\n")
    shutil.copyfile(Path(__file__).resolve(), PROGRAM)
    PROGRAM.chmod(0o644)
    DROP_IN.parent.mkdir(parents=True, exist_ok=True)
    DROP_IN.write_text(
        f"[Service]\nWorkingDirectory={BASE}/current\nExecStart=\n"
        f"ExecStart={BASE}/current/lawncare-server\n"
    )
    (UNITS / JOB).write_text(
        "[Unit]\nDescription=Install the latest verified Lawn Care release\n"
        "Wants=network-online.target\nAfter=network-online.target\n"
        f"\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {PROGRAM} --run\n"
        "TimeoutStartSec=5min\n"
    )
    (UNITS / TIMER).write_text(
        "[Unit]\nDescription=Check for Lawn Care releases every two minutes\n"
        "\n[Timer]\nOnActiveSec=2min\nOnUnitInactiveSec=2min\nAccuracySec=5s\n"
        "\n[Install]\nWantedBy=timers.target\n"
    )
    systemctl("daemon-reload")
    if property_value("WorkingDirectory") != str(BASE / "current"):
        raise RuntimeError("Another systemd drop-in overrides the release working directory.")
    print("Installed deployment files. Run the first deployment before enabling the timer.")


def main():
    if os.geteuid() != 0:
        raise ValueError("Run this script with sudo.")
    if not hasattr(tarfile, "data_filter"):
        raise ValueError("Update Ubuntu's Python packages to get secure tar extraction support.")
    if len(sys.argv) != 2:
        raise ValueError("Usage: sudo python3 setup-lawncare-cd.py OWNER/lawncare-website")
    if sys.argv[1] == "--run":
        deploy()
    else:
        install(sys.argv[1])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, RuntimeError, tarfile.TarError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
