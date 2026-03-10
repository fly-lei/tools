import os
import sys
import streamlit.web.cli as stcli


def main():
    # 兼容 PyInstaller 的虚拟路径
    if getattr(sys, 'frozen', False):
        # 如果是打包后的 exe 运行，获取解压后的临时目录路径
        application_path = sys._MEIPASS
    else:
        # 如果是正常 Python 运行，获取当前目录
        application_path = os.path.dirname(os.path.abspath(__file__))

    # 拼接主程序的绝对路径
    script_path = os.path.join(application_path, "app.py")

    # 模拟在终端输入 streamlit run app.py
    sys.argv = [
        "streamlit",
        "run",
        script_path,
        "--server.headless=true",  # 隐藏多余的终端输出
        "--global.developmentMode=false",
        "--server.port=8501"  # 固定端口
    ]

    # 启动 Streamlit
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()