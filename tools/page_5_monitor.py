import streamlit as st
import os
import glob
import time
import serial
import threading
from datetime import datetime
from collections import deque
from utils import modbus_comm

LOG_DIR = "serial_logs"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 单文件 10MB
MAX_FOLDER_SIZE = 1024 * 1024 * 1024  # 总文件夹 1GB

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# ==========================================
# 🌟 全局独立内存状态 (脱离浏览器存活，带防爆队列)
# ==========================================
GLOBAL_MONITOR_STATE = {
    "is_monitoring": False,
    "stop_event": threading.Event(),
    "mon_logs": deque(maxlen=200),  # UI 实时展示最多保留最新的 200 条，防止网页卡顿
    "received_count": 0,
    "last_error": ""
}


def manage_log_rotation():
    """管理日志文件大小，超过 1GB 删除最老的"""
    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")), key=os.path.getmtime)
    total_size = sum(os.path.getsize(f) for f in files)
    while total_size > MAX_FOLDER_SIZE and files:
        oldest_file = files.pop(0)
        size = os.path.getsize(oldest_file)
        try:
            os.remove(oldest_file)
            total_size -= size
        except Exception:
            break


def append_to_serial_log(log_line):
    """将日志追加到文件中，处理切片"""
    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")))
    if not files:
        current_file = os.path.join(LOG_DIR, f"serial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    else:
        current_file = files[-1]
        if os.path.getsize(current_file) >= MAX_FILE_SIZE:
            current_file = os.path.join(LOG_DIR, f"serial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            manage_log_rotation()

    try:
        with open(current_file, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception:
        pass


def background_sniffer(port, baud, state):
    """底层串口监听守护线程"""
    try:
        ser = serial.Serial(port, baud, timeout=0.1)
    except Exception as e:
        state["last_error"] = f"[系统] 无法打开串口 {port}: {e}"
        state["is_monitoring"] = False
        return

    state["last_error"] = ""

    while not state["stop_event"].is_set():
        try:
            waiting = ser.in_waiting
            if waiting > 0:
                raw_data = ser.read(waiting)
                hex_str = " ".join([f"{b:02X}" for b in raw_data])
                ts_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                # 1. 完整写入本地 1GB 硬盘日志 (永不丢失)
                log_line = f"[{ts_full}] RX {len(raw_data):02d} 字节: {hex_str}"
                append_to_serial_log(log_line)

                # 2. 更新内存队列供 UI 实时展示 (只保留最新 200 条)
                ts_short = ts_full.split(" ")[1]
                ui_line = f"[{ts_short}] RX {len(raw_data):02d} 字节: {hex_str}"
                state["mon_logs"].appendleft(ui_line)  # appendleft 保证最新的在最上面

                state["received_count"] += 1

        except Exception as e:
            state["last_error"] = f"[系统] 串口读取异常或设备已断开: {e}"
            break

        time.sleep(0.01)  # 极短休眠防 CPU 占满

    try:
        ser.close()
    except:
        pass

    state["is_monitoring"] = False


def render():
    st.title("📡 串口报文无损监控大屏")
    st.markdown(
        "利用系统级底层线程抓取 HEX 报文，完全脱离浏览器存活。**关闭网页、断网、锁屏均不中断监控！** 本地自动切片并限制总容量 1GB。")
    st.divider()

    # 🌟 核心绑定：永远指向全局独立内存
    mon_state = GLOBAL_MONITOR_STATE

    tab_monitor, tab_files = st.tabs(["🔴 实时监控面板", "📁 硬盘历史日志管理"])

    with tab_monitor:
        available_ports = modbus_comm.get_available_ports()

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            mon_port = st.selectbox("选择监控串口", available_ports if available_ports else ["无可用串口"],
                                    key="mon_port", disabled=mon_state["is_monitoring"])
        with c2:
            mon_baud = st.selectbox("选择波特率", [9600, 19200, 38400, 57600, 115200], index=0, key="mon_baud",
                                    disabled=mon_state["is_monitoring"])
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ 清空屏幕", use_container_width=True):
                mon_state["mon_logs"].clear()
                st.rerun()

        st.divider()

        # 错误提示
        if mon_state["last_error"]:
            st.error(mon_state["last_error"])

        # 控制开关
        is_monitoring_ui = st.toggle("🟢 开启后台静默监控探针 (随时可关闭网页)", value=mon_state["is_monitoring"])

        # 逻辑：用户在 UI 点击了开启，但后台还没跑
        if is_monitoring_ui and not mon_state["is_monitoring"]:
            if mon_port == "无可用串口":
                st.error("未检测到串口！")
                st.stop()

            mon_state["is_monitoring"] = True
            mon_state["stop_event"].clear()
            mon_state["received_count"] = 0
            mon_state["mon_logs"].clear()

            threading.Thread(
                target=background_sniffer,
                args=(mon_port, mon_baud, mon_state),
                daemon=True
            ).start()

            st.toast(f"已派生后台线程开始死磕 {mon_port}！", icon="✅")
            st.rerun()

        # 逻辑：用户在 UI 点击了关闭，但后台还在跑
        elif not is_monitoring_ui and mon_state["is_monitoring"]:
            mon_state["is_monitoring"] = False
            mon_state["stop_event"].set()
            st.toast("后台监控已收到停止指令，串口已释放。", icon="🛑")
            st.rerun()

        # ==========================================
        # UI 渲染层 (自动刷新机制)
        # ==========================================
        if mon_state["is_monitoring"]:
            st.success(f"🎧 探针正在后台疯狂监听中... 本次已截获 **{mon_state['received_count']}** 帧报文！")
            st.warning("💡 您可以放心关闭浏览器下班。底层进程会将报文完好无损地写入 1GB 本地硬盘环形列阵中。")

            # 使用容器包裹定长队列
            with st.container(border=True, height=400):
                st.code("\n".join(mon_state["mon_logs"]), language="text")

            time.sleep(0.5)
            st.rerun()

        else:
            st.info("当前未开启监听。")
            with st.container(border=True, height=400):
                st.code("\n".join(mon_state["mon_logs"]), language="text")

    # ==========================================
    # 硬盘文件管理
    # ==========================================
    with tab_files:
        st.subheader("🗄️ 本地硬盘存储日志 (单文件 10MB，总计 1GB 滚动覆盖)")

        log_files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")), reverse=True)

        if not log_files:
            st.info("💡 暂无历史监控文件。开启监控并收到数据后将自动生成。")
        else:
            total_mb = sum(os.path.getsize(f) for f in log_files) / (1024 * 1024)
            st.markdown(
                f"**当前日志总数：** {len(log_files)} 个 &nbsp;&nbsp;|&nbsp;&nbsp; **硬盘总计占用：** {total_mb:.2f} MB / 1024.00 MB")

            def format_file_option(filepath):
                name = os.path.basename(filepath)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                return f"{name} ({size_mb:.2f} MB)"

            selected_file = st.selectbox("请选择要操作的文件", log_files, format_func=format_file_option)

            c_down, c_del, c_clear = st.columns([2, 2, 2])
            with c_down:
                with open(selected_file, "rb") as f:
                    st.download_button(
                        label="📥 下载选中文件",
                        data=f,
                        file_name=os.path.basename(selected_file),
                        mime="text/plain",
                        use_container_width=True
                    )
            with c_del:
                if st.button("🗑️ 删除选中文件", use_container_width=True):
                    try:
                        os.remove(selected_file)
                        st.toast(f"{os.path.basename(selected_file)} 已删除！", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除失败: {e}")
            with c_clear:
                if st.button("⚠️ 一键清空所有历史硬盘记录", type="primary", use_container_width=True):
                    for file_path in log_files:
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass
                    st.toast("所有历史硬盘记录已清空！", icon="🧹")
                    st.rerun()