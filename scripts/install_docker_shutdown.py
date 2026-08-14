"""
安装/卸载「登录后自动关闭 Docker WSL 发行版」脚本。

背景：Docker Desktop 分三层自启，其中 WSL 发行版 docker-desktop（dockerd 引擎）
由 WSL 服务在系统级自动拉起，Docker Desktop 应用内设置管不到。
此脚本在登录后静默运行 `wsl --shutdown`，关掉 docker-desktop 发行版，
让 Docker 引擎不常驻内存。下次需要时双击观察台脚本即可自动重启 Docker。

用法：
  python install_docker_shutdown.py          安装
  python install_docker_shutdown.py --remove 卸载
"""
import argparse
import os

SCRIPT_NAME = "docker-wsl-shutdown.vbs"


def get_startup_dir():
    return os.path.join(
        os.environ["APPDATA"],
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


def build_vbs():
    """生成 .vbs 内容（UTF-16 编码）。静默运行 wsl --shutdown，无窗口。"""
    return (
        "' Docker WSL shutdown on logon (silent, no window)\n"
        "Set ws = CreateObject(\"Wscript.Shell\")\n"
        "ws.Run \"wsl.exe --shutdown\", 0, False\n"
    )


def install():
    startup_dir = get_startup_dir()
    os.makedirs(startup_dir, exist_ok=True)
    vbs_path = os.path.join(startup_dir, SCRIPT_NAME)

    with open(vbs_path, "w", encoding="utf-16") as f:
        f.write(build_vbs())

    print(f"已安装: {vbs_path}")
    print("--- 内容 ---")
    print(build_vbs())


def remove():
    vbs_path = os.path.join(get_startup_dir(), SCRIPT_NAME)
    if os.path.exists(vbs_path):
        os.remove(vbs_path)
        print(f"已卸载: {vbs_path}")
    else:
        print(f"未找到: {vbs_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="安装/卸载登录后关闭 Docker WSL")
    parser.add_argument("--remove", action="store_true", help="卸载")
    args = parser.parse_args()
    if args.remove:
        remove()
    else:
        install()
