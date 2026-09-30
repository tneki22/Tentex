from app.storage.host_paths import _from_mountinfo

DOCKER_DESKTOP_WSL = (
    "678 668 0:68 /Users/nekit/Desktop/Tentex/data /data rw,noatime - 9p C:\\134 "
    "rw,aname=drvfs;path=C:\\;uid=0;gid=0;metadata;symlinkroot=/mnt/host/,cache=5"
)
LEGACY_HOST_MOUNT = (
    "701 668 0:70 /host_mnt/d/Учёба/Tentex/data /data rw - fuse.grpcfuse grpcfuse rw"
)
UNRELATED = "679 668 8:48 /docker/resolv.conf /etc/resolv.conf rw,relatime - ext4 /dev/sdd rw"


def test_drvfs_mount_gives_windows_path() -> None:
    mountinfo = f"{UNRELATED}\n{DOCKER_DESKTOP_WSL}"

    assert _from_mountinfo(mountinfo, "/data") == "C:\\Users\\nekit\\Desktop\\Tentex\\data"


def test_legacy_host_mount_gives_windows_path() -> None:
    assert _from_mountinfo(LEGACY_HOST_MOUNT, "/data") == "D:\\Учёба\\Tentex\\data"


def test_unknown_mount_is_not_guessed() -> None:
    assert _from_mountinfo(UNRELATED, "/data") is None
