import streamlit as st
import os
import glob
import json
import time
import threading
import pandas as pd
from datetime import datetime
import logging

from utils import modbus_comm

# ==========================================
# 🌟 Pymodbus 兼容性补丁
# ==========================================
from pymodbus.server import StartSerialServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

try:
    from pymodbus.datastore import ModbusDeviceContext as SlaveContext
except ImportError:
    from pymodbus.datastore import ModbusSlaveContext as SlaveContext

try:
    from pymodbus.framer import FramerType

    FRAMER = FramerType.RTU
except ImportError:
    from pymodbus.transaction import ModbusRtuFramer

    FRAMER = ModbusRtuFramer

logging.getLogger('pymodbus').setLevel(logging.ERROR)

# 数据保存目录
SNAPSHOT_DIR = "device_snapshots"
if not os.path.exists(SNAPSHOT_DIR):
    os.makedirs(SNAPSHOT_DIR)


def render():
    st.title("🪞 Modbus 设备镜像抓取与克隆模拟器")
    st.markdown("从真实设备中批量抓取并保存寄存器数据，随后可以作为**虚拟从站**完美克隆并重放这些数据。")
    st.divider()

    tab_record, tab_simulate = st.tabs(["📥 抓取真实设备 (录制镜像)", "📤 启动克隆设备 (模拟从站)"])

    # ==========================================
    # 模式一：抓取真实设备
    # ==========================================
    with tab_record:
        st.subheader("1. 连接真实设备")
        available_ports = modbus_comm.get_available_ports()
        if not available_ports:
            available_ports = ["COM1"]

        c1, c2, c3 = st.columns(3)
        with c1:
            rec_port = st.selectbox("串口", available_ports, key="rec_port")
        with c2:
            rec_baud = st.selectbox("波特率", [4800,9600, 19200, 38400, 57600, 115200], index=0, key="rec_baud")
        with c3:
            rec_slave = st.number_input("真实设备站号", min_value=1, max_value=247, value=1, key="rec_slave")

        st.subheader("2. 设置抓取范围与参数")
        c4, c5, c6 = st.columns(3)
        with c4:
            start_addr = st.number_input("起始地址 (十进制)", min_value=0, max_value=65535, value=0)
        with c5:
            end_addr = st.number_input("结束地址 (十进制)", min_value=1, max_value=65535, value=10000)
        with c6:
            chunk_size = st.number_input("单次读取块大小 (最大125)", min_value=1, max_value=125, value=100,
                                         help="为了防止断点报错，分块读取。如果设备极其严格，可设为更小的值。")

        device_name = st.text_input("💾 给这个设备起个名字 (用于保存镜像)", placeholder="例如：水冷螺杆机_V1_现场A")

        if st.button("🚀 开始雷达扫描并抓取数据", type="primary"):
            if not device_name:
                st.warning("⚠️ 请先输入设备名称！")
            else:
                st.info(f"正在扫描 {start_addr} 到 {end_addr} 的数据，这可能需要一些时间...")
                progress_bar = st.progress(0.0)
                status_text = st.empty()

                captured_data = {}
                success_chunks = 0
                fail_chunks = 0

                total_registers = end_addr - start_addr + 1

                for offset in range(start_addr, end_addr + 1, chunk_size):
                    read_len = min(chunk_size, end_addr - offset + 1)

                    # 尝试读取
                    success, res = modbus_comm.master_read(rec_port, rec_baud, rec_slave, 3, offset, read_len,
                                                           timeout=0.3)

                    if success:
                        success_chunks += 1
                        for idx, val in enumerate(res):
                            captured_data[str(offset + idx)] = val
                    else:
                        fail_chunks += 1

                    # 更新进度
                    current_progress = min(1.0, (offset - start_addr + chunk_size) / total_registers)
                    progress_bar.progress(current_progress)
                    status_text.text(
                        f"📡 扫描中: 当前地址 {offset} | 成功块: {success_chunks} | 跳过断点块: {fail_chunks}")

                if not captured_data:
                    st.error("❌ 未能抓取到任何有效数据，请检查接线、站号或尝试缩小读取范围！")
                else:
                    # 保存到 JSON
                    save_path = os.path.join(SNAPSHOT_DIR, f"{device_name}.json")
                    snapshot = {
                        "metadata": {
                            "device_name": device_name,
                            "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "original_slave_id": rec_slave,
                            "valid_registers_count": len(captured_data)
                        },
                        "data": captured_data
                    }
                    with open(save_path, "w", encoding="utf-8") as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=4)

                    st.success(
                        f"🎉 抓取成功！共捕获到 {len(captured_data)} 个有效寄存器数据。已保存为 `{device_name}.json`。")

                    # 展示前 20 个抓取到的数据
                    st.write("📊 预览抓取到的部分数据：")
                    preview_items = list(captured_data.items())[:20]
                    preview_df = pd.DataFrame(preview_items, columns=["寄存器地址", "十进制数值"])
                    st.dataframe(preview_df, use_container_width=True)

    # ==========================================
    # 模式二：作为从站模拟克隆设备
    # ==========================================
    with tab_simulate:
        st.subheader("1. 选择要模拟的设备镜像")

        saved_files = glob.glob(os.path.join(SNAPSHOT_DIR, "*.json"))
        if not saved_files:
            st.info("📂 暂无保存的设备镜像。请先在左侧标签页抓取真实设备！")
            return

        file_options = [os.path.basename(f) for f in saved_files]
        selected_file = st.selectbox("选择镜像文件", file_options)

        # 加载并预览镜像
        file_path = os.path.join(SNAPSHOT_DIR, selected_file)
        with open(file_path, "r", encoding="utf-8") as f:
            snapshot_data = json.load(f)

        st.markdown(
            f"**镜像信息:** 录制时间 `{snapshot_data['metadata']['capture_time']}` | 包含 `{snapshot_data['metadata']['valid_registers_count']}` 个寄存器数据")

        st.subheader("2. 配置虚拟克隆从站")
        available_ports_sim = modbus_comm.get_available_ports()
        if not available_ports_sim:
            available_ports_sim = ["COM1"]

        c7, c8, c9 = st.columns(3)
        with c7:
            sim_port = st.selectbox("本机模拟串口 (供主站读取)", available_ports_sim, key="sim_port")
        with c8:
            sim_baud = st.selectbox("波特率", [9600, 19200, 38400, 57600, 115200], index=0, key="sim_baud")
        with c9:
            sim_slave = st.number_input("模拟的站号 (Slave ID)", min_value=1, max_value=247,
                                        value=snapshot_data['metadata']['original_slave_id'], key="sim_slave")

        st.divider()

        # 线程启停逻辑
        if 'sim_running' not in st.session_state:
            st.session_state.sim_running = False

        is_simulate_ui = st.toggle("🟢 开启后台虚拟设备 (随时接受主站读取)", value=st.session_state.sim_running)

        if is_simulate_ui and not st.session_state.sim_running:
            # 1. 准备内存空间 (65536 涵盖全地址)
            store = SlaveContext(
                di=ModbusSequentialDataBlock(0, [0] * 65536),
                co=ModbusSequentialDataBlock(0, [0] * 65536),
                hr=ModbusSequentialDataBlock(0, [0] * 65536),
                ir=ModbusSequentialDataBlock(0, [0] * 65536)
            )

            # 2. 将抓取的 JSON 数据注入到内存里
            reg_data = snapshot_data["data"]
            for addr_str, val in reg_data.items():
                store.setValues(3, int(addr_str), [val])

            # 3. 启动 Server (兼容性包裹)
            try:
                context = ModbusServerContext(slaves=store, single=True)
            except TypeError:
                try:
                    context = ModbusServerContext(devices=store, single=True)
                except TypeError:
                    context = ModbusServerContext(store, single=True)

            def run_modbus_rtu_simulator():
                StartSerialServer(
                    context=context, framer=FRAMER, port=sim_port,
                    baudrate=sim_baud, bytesize=8, parity='N', stopbits=1
                )

            st.session_state.sim_thread = threading.Thread(target=run_modbus_rtu_simulator, daemon=True)
            st.session_state.sim_thread.start()
            st.session_state.sim_running = True

            st.toast("虚拟设备已启动，正在后台运行！", icon="✅")
            st.rerun()

        elif not is_simulate_ui and st.session_state.sim_running:
            st.session_state.sim_running = False
            # 发送停止指令
            try:
                if ServerStop: ServerStop()
            except Exception:
                pass
            st.toast("虚拟设备已停止。", icon="🛑")
            st.rerun()

        if st.session_state.sim_running:
            st.success(
                f"🎉 **虚拟设备运行中！** 你的主站现在可以通过串口 `{sim_port}`，站号 `{sim_slave}` 来读取它了！(哪怕切到其他页面它也会在后台运行)")