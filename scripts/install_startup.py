"""
安装/卸载开机自启动脚本。

开机登录后自动静默运行 daily.py，配合 daily.py 的幂等判断，
实现"开机即推"（当天推过则跳过）。

用法：
  python install_startup.py          安装
  python install_startup.py --remove 卸载
"""
import argparse
import os

SCRIPT_NAME = "daily-push-startup.vbs"
PYTHON_EXE = r"A:\workbuddy项目\论文观察台\scripts\.venv\Scripts\python.exe"
DAILY_PY = r"A:\workbuddy项目\论文观察台\scripts\daily.py"
SCRIPTS_DIR = r"A:\workbuddy项目\论文观察台\scripts"


def get_startup_dir():
    return os.path.join(
        os.environ["APPDATA"],
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


def build_vbs():
    """生成 .vbs 内容（UTF-16 编码，正确处理中文路径）。"""
    return (
        "' 公众号每日论文推送 - 开机自启动（静默运行，无窗口）\n"
        "Set ws = CreateObject(\"Wscript.Shell\")\n"
        f"ws.CurrentDirectory = \"{SCRIPTS_DIR}\"\n"
        f"ws.Run \"\"\"{PYTHON_EXE}\"\" \"\"{DAILY_PY}\"\"\", 0, False\n"
    )


def install():
    startup_dir = get_startup_dir()
    os.makedirs(startup_dir, exist_ok=True)
    vbs_path = os.path.join(startup_dir, SCRIPT_NAME)

    with open(vbs_path, "w", encoding="utf-16") as f:
        f.write(build_vbs())

    print(f"已安装开机自启动脚本: {vbs_path}")
    print("--- 内容 ---")
    print(build_vbs())


def remove():
    vbs_path = os.path.join(get_startup_dir(), SCRIPT_NAME)
    if os.path.exists(vbs_path):
        os.remove(vbs_path)
        print(f"已卸载: {vbs_path}")
    else:
        print(f"未找到启动脚本: {vbs_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="安装/卸载开机自启动脚本")
    parser.add_argument("--remove", action="store_true", help="卸载开机自启动脚本")
    args = parser.parse_args()
    if args.remove:
        remove()
    else:
        install()
