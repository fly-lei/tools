import streamlit as st
import os
import glob
import time
import serial
import threading
from datetime import datetime
from utils import modbus_comm

LOG_DIR = "serial_logs"
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_FOLDER_SIZE = 1024 * 1024 * 1024

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def manage_log_rotation():
    # ... (原文件管理逻辑) ...
    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")), key=os.path.getmtime)
    total_size = sum(os.path.getsize(f) for f in files)
    while total_size > MAX_FOLDER_SIZE and files:
        oldest_file = files.pop(0)
        size = os.path.getsize(oldest_file)
        os.remove(oldest_file)
        total_size -= size


def append_to_serial_log(log_line):
    # ... (原写入逻辑) ...
    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")))
    if not files:
        current_file = os.path.join(LOG_DIR, f"serial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    else:
        current_file = files[-1]
        if os.path.getsize(current_file) >= MAX_FILE_SIZE:
            current_file = os.path.join(LOG_DIR, f"serial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            manage_log_rotation()
    with open(current_file, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")


def background_sniffer(port, baud, stop_event, logs_list):
    # ... (原底层监听逻辑) ...
    try:
        ser = serial.Serial(port, baud, timeout=0.1)
    except Exception as e:
        logs_list.insert(0, f"[系统] 无法打开串口 {port}: {e}")
        return

    while not stop_event.is_set():
        try:
            waiting = ser.in_waiting
            if waiting > 0:
                raw_data = ser.read(waiting)
                hex_str = " ".join([f"{b:02X}" for b in raw_data])
                ts_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                append_to_serial_log(f"[{ts_full}] RX {len(raw_data):02d} 字节: {hex_str}")

                ts_short = ts_full.split(" ")[1]
                logs_list.insert(0, f"[{ts_short}] RX {len(raw_data):02d} 字节: {hex_str}")

                if len(logs_list) > 100:
                    logs_list.pop()
        except Exception as e:
            logs_list.insert(0, f"[系统] 串口读取异常或设备已断开: {e}")
            break
        time.sleep(0.02)

    try:
        ser.close()
    except:
        pass
    pass

def render():
    st.title("📡 串口报文实时监控与行车记录仪")
    st.markdown("利用系统级底层线程抓取 HEX 报文，不受页面切换影响。自动切片并限制容量 1GB。")
    # ...(将原 app.py 中工具 5 的 tab_monitor 和 tab_files 渲染逻辑贴到这里)
    tab_monitor, tab_files = st.tabs(["🔴 实时监控面板", "📁 历史日志管理"])

    with tab_monitor:
        available_ports = modbus_comm.get_available_ports()

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            mon_port = st.selectbox("选择监控串口", available_ports if available_ports else ["无可用串口"],
                                    key="mon_port")
        with c2:
            mon_baud = st.selectbox("选择波特率", [9600, 19200, 38400, 57600, 115200], index=0, key="mon_baud")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ 清空屏幕", use_container_width=True):
                st.session_state.mon_logs = []
                st.rerun()

        st.divider()

        is_monitoring_ui = st.toggle("🟢 开启后台监控探针 (随页面切换不中断)", value=st.session_state.is_monitoring)

        if is_monitoring_ui and not st.session_state.is_monitoring:
            if mon_port == "无可用串口":
                st.error("未检测到串口！")
                st.stop()

            st.session_state.is_monitoring = True
            st.session_state.sniffer_stop_event.clear()

            st.session_state.sniffer_thread = threading.Thread(
                target=background_sniffer,
                args=(mon_port, mon_baud, st.session_state.sniffer_stop_event, st.session_state.mon_logs),
                daemon=True
            )
            st.session_state.sniffer_thread.start()
            st.toast(f"已派生后台线程开始监控 {mon_port}！", icon="✅")
            st.rerun()

        elif not is_monitoring_ui and st.session_state.is_monitoring:
            st.session_state.is_monitoring = False
            st.session_state.sniffer_stop_event.set()
            st.toast("后台监控已收到停止指令，串口已释放。", icon="🛑")
            st.rerun()

        if st.session_state.is_monitoring:
            st.info("🔄 探针运行中，您可以放心切换到左侧其他工具页面。")
            st.code("\n".join(st.session_state.mon_logs), language="text")
            time.sleep(0.5)
            st.rerun()
        else:
            st.code("\n".join(st.session_state.mon_logs), language="text")

    with tab_files:
        st.subheader("🗄️ 本地存储日志 (单文件 10MB，总计 1GB 滚动覆盖)")

        log_files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")), reverse=True)

        if not log_files:
            st.info("💡 暂无历史监控文件。开启监控并收到数据后将自动生成。")
        else:
            total_mb = sum(os.path.getsize(f) for f in log_files) / (1024 * 1024)
            st.markdown(
                f"**当前日志总数：** {len(log_files)} 个 &nbsp;&nbsp;|&nbsp;&nbsp; **总计占用空间：** {total_mb:.2f} MB / 1024.00 MB")

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
                if st.button("⚠️ 一键清空所有", type="primary", use_container_width=True):
                    for file_path in log_files:
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass
                    st.toast("所有历史记录已清空！", icon="🧹")
                    st.rerun()