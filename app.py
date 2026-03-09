import streamlit as st
import io
import os
import glob
import time
import random
import serial
import threading
import requests
import pandas as pd
from datetime import datetime
import logging

from utils import modbus_engine
from utils import crc_calculator
from utils import modbus_comm
from utils import ota_engine

# ==========================================
# 🌟 高级黑魔法：兼容所有新老版本 pymodbus 的动态补丁
# ==========================================
from pymodbus.server import StartSerialServer

try:
    from pymodbus.server import ServerStop
except ImportError:
    try:
        from pymodbus.server import StopServer as ServerStop
    except ImportError:
        ServerStop = None

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


@st.cache_resource
def get_ota_task_state():
    return {
        "is_running": False,
        "progress": 0.0,
        "progress_text": "",
        "logs": [],
        "current_msg": "",
        "msg_status": "info",
        "result": None
    }


ota_state = get_ota_task_state()

st.set_page_config(page_title="工业协议解析工具集", page_icon="🧰", layout="wide")

if 'mon_logs' not in st.session_state:
    st.session_state.mon_logs = []
if 'is_monitoring' not in st.session_state:
    st.session_state.is_monitoring = False
if 'sniffer_thread' not in st.session_state:
    st.session_state.sniffer_thread = None
if 'sniffer_stop_event' not in st.session_state:
    st.session_state.sniffer_stop_event = threading.Event()

st.sidebar.title("🧰 工具集导航")
tool_choice = st.sidebar.radio(
    "请选择功能",
    [
        "1. Modbus 报文解析",
        "2. CRC16 校验计算器",
        "3. Modbus 数据读取",
        "4. OTA 机组固件升级",
        "5. 串口报文监控",
        "6. 跨文件表格字典匹配",
        "7. 网关云端联动检测"
    ]
)

if tool_choice != "7. 网关云端联动检测":
    try:
        if ServerStop: ServerStop()
    except Exception:
        pass

# ==========================================
# 工具 1：Modbus 报文解析
# ==========================================
if tool_choice == "1. Modbus 报文解析":
    st.title("🔌 Modbus RTU 日志提取")
    st.markdown("上传现场串口/网络监控日志文件，快速提取指定站号和地址的读写数值，支持跨行粘包解析与导出。")
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("⚙️ 基础参数设置")
        slave_input = st.text_input("设备站号 (Slave ID)", value="1", help="支持十进制(如 1) 或十六进制(如 0x01)")
        address_input = st.text_input("目标寄存器地址", value="0x09f6",
                                      help="支持十进制(如 2550) 或十六进制(如 0x09f6)")

    with col2:
        st.subheader("🛠️ 解析模式选择")
        scan_writes_only = st.checkbox("🔍 快速扫描所有写入操作 (忽略目标地址，仅抓取 0x06 和 0x10)", value=False)
        st.info("提示：勾选快速扫描后，工具将罗列该站号的所有写入控制报文。")

    st.subheader("📄 上传日志文件")
    uploaded_file = st.file_uploader("支持 txt / log 格式文件", type=['txt', 'log'])

    if st.button("🚀 开始解析日志", type="primary"):
        if uploaded_file is None:
            st.warning("⚠️ 请先上传一个日志文件！")
        else:
            try:
                slave_id = int(slave_input, 0)
                target_address = 0 if scan_writes_only else int(address_input, 0)
                file_content = uploaded_file.getvalue().decode("utf-8")
                file_lines = file_content.splitlines()

                with st.spinner('正在玩命解析中，请稍候...'):
                    result_data = modbus_engine.parse_modbus_data(
                        file_lines, target_address, slave_id, scan_writes_only
                    )

                if not result_data:
                    st.error("😭 未在日志中找到符合条件的完整且配对的读写记录。")
                else:
                    st.success(f"🎉 解析成功！共提取到 {len(result_data)} 条有效记录。")
                    excel_bytes, df = modbus_engine.generate_excel_bytes(result_data)
                    st.dataframe(df, use_container_width=True)

                    st.download_button(
                        label="📥 下载 Excel 结果表",
                        data=excel_bytes,
                        file_name="modbus_parsed_result.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            except ValueError:
                st.error("❌ 参数格式错误！请确保站号和地址填写的是有效的整数或十六进制。")
            except Exception as e:
                st.error(f"❌ 解析发生未知错误: {str(e)}")

# ==========================================
# 工具 2：CRC16 校验计算器
# ==========================================
elif tool_choice == "2. CRC16 校验计算器":
    st.title("🧮 Modbus CRC16 校验计算器")
    st.markdown("快速计算十六进制报文的 Modbus CRC16 校验码，支持带空格或连写的输入。")
    st.divider()

    hex_input = st.text_input("请输入报文 (不含校验码):", value="01 03 00 00 00 0A",
                              help="例如输入 '01 03 00 00 00 0A' 或 '01030000000a' 均可")

    if st.button("🧮 计算 CRC16", type="primary"):
        try:
            crc_result, full_frame = crc_calculator.calculate_crc16(hex_input)
            st.success("✅ 计算成功！")

            col1, col2 = st.columns(2)
            with col1:
                st.metric(label="生成 CRC 校验码 (低位 高位)", value=crc_result)
            with col2:
                st.metric(label="带校验的完整发送报文", value=full_frame)

            st.code(full_frame, language="text")

        except ValueError as e:
            st.error(f"❌ {str(e)}")

# ==========================================
# 工具 3：Modbus 数据读取
# ==========================================
elif tool_choice == "3. Modbus 数据读取":
    st.title("💻 Modbus 主站在线调试 (Master)")
    st.markdown("直接通过串口读取或写入现场设备的寄存器数值，支持 03、04、10 功能码。")
    st.divider()

    available_ports = modbus_comm.get_available_ports()
    if not available_ports:
        st.warning("⚠️ 未检测到可用的串口，请检查硬件连接或使用虚拟串口软件(如 VSPD)。")
        available_ports = ["COM1"]

    st.subheader("🔌 串口通讯配置")
    c1, c2, c3 = st.columns(3)
    with c1:
        com_port = st.selectbox("选择串口", available_ports)
    with c2:
        baudrate = st.selectbox("波特率", [4800, 9600, 19200, 38400, 57600, 115200], index=0)
    with c3:
        slave_id = st.number_input("设备站号 (Slave ID)", min_value=1, max_value=247, value=1)

    st.divider()

    tab_read, tab_write = st.tabs(["📖 读取寄存器 (03 / 04)", "✍️ 写入多寄存器 (10)"])

    with tab_read:
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            read_fc = st.selectbox("功能码", ["03 (读保持寄存器)", "04 (读输入寄存器)"])
        with rc2:
            read_addr = st.number_input("起始地址 (十进制)", min_value=0, max_value=65535, value=0, key="r_addr")
        with rc3:
            read_count = st.number_input("读取数量 (寄存器个数)", min_value=1, max_value=125, value=10, key="r_count")

        st.divider()

        data_format = st.radio(
            "数据解析格式 (16位)",
            options=["无符号整数 (Unsigned: 0 ~ 65535)", "有符号整数 (Signed: -32768 ~ 32767)"],
            horizontal=True
        )

        ac1, ac2 = st.columns([1, 2])
        with ac1:
            auto_refresh = st.toggle("🔄 开启自动刷新 (连续读取)", key="auto_refresh_toggle")
        with ac2:
            refresh_interval = st.number_input("刷新间隔 (秒)", min_value=0.5, max_value=60.0, value=1.0, step=0.5,
                                               disabled=not auto_refresh)


        def parse_signed_16bit(val):
            if val > 32767:
                return val - 65536
            return val


        def do_read_action():
            fc_num = 3 if "03" in read_fc else 4
            success, result = modbus_comm.master_read(com_port, baudrate, slave_id, fc_num, read_addr, read_count)

            if success:
                if "有符号" in data_format:
                    display_values = [parse_signed_16bit(v) for v in result]
                else:
                    display_values = result

                df_res = pd.DataFrame({
                    "寄存器地址 (十进制)": [read_addr + i for i in range(read_count)],
                    "寄存器地址 (十六进制)": [f"0x{read_addr + i:04X}" for i in range(read_count)],
                    "十进制数值": display_values,
                    "原始十六进制": [f"0x{val:04X}" for val in result]
                })
                st.dataframe(df_res, use_container_width=True)
            else:
                st.error(result)


        if auto_refresh:
            st.info(f"🟢 正在连续读取中... 每 {refresh_interval} 秒刷新一次。")
            do_read_action()
            time.sleep(refresh_interval)
            st.rerun()
        else:
            if st.button("🚀 单次读取", type="primary"):
                with st.spinner('正在与设备通讯...'):
                    do_read_action()

    with tab_write:
        wc1, wc2 = st.columns(2)
        with wc1:
            write_addr = st.number_input("起始地址 (十进制)", min_value=0, max_value=65535, value=0, key="w_addr")
        with wc2:
            write_values_str = st.text_input("要写入的数值 (用英文逗号分隔)", value="100, 200, 300",
                                             help="例如输入: 100, 200 意味着向起始地址连续写入两个寄存器")

        if st.button("✍️ 执行写入 (0x10)", type="primary"):
            try:
                values_list = [int(v.strip()) for v in write_values_str.split(",")]
                with st.spinner('正在下发指令...'):
                    success, result = modbus_comm.master_write_10(com_port, baudrate, slave_id, write_addr, values_list)

                if success:
                    st.success(f"✅ {result} (共写入 {len(values_list)} 个寄存器)")
                else:
                    st.error(result)
            except ValueError:
                st.error("❌ 数值格式错误，请确保填入的是用逗号隔开的整数！")

# ==========================================
# 工具 4：OTA 机组固件升级
# ==========================================
elif tool_choice == "4. OTA 机组固件升级":
    st.title("💽 OTA 机组固件在线升级 (Modbus)")
    st.markdown("通过严格的时序校验，支持后台静默刷录。**即使关闭浏览器，任务依然在设备后台执行。**")
    st.divider()

    if ota_state["is_running"] or ota_state["result"] is not None:
        st.subheader("🔄 升级任务监视器")

        if ota_state["is_running"]:
            st.warning("⚠️ 升级任务正在后台疯狂执行中，请勿断开物理设备电源！您可以随意关闭网页，稍后再来查看。")

            st.progress(ota_state["progress"], text=ota_state["progress_text"])

            if ota_state["msg_status"] == "error":
                st.error(ota_state["current_msg"])
            elif ota_state["msg_status"] == "success":
                st.success(ota_state["current_msg"])
            elif ota_state["msg_status"] == "warning":
                st.warning(ota_state["current_msg"])
            else:
                st.info(ota_state["current_msg"])

            with st.expander("查看实时底层通信报文", expanded=True):
                st.code("\n".join(ota_state["logs"][-30:]), language="text")

            time.sleep(1)
            st.rerun()

        else:
            st.progress(1.0, text="任务结束")
            if ota_state["result"]:
                st.success(f"🎉 任务结束！{ota_state['current_msg']}")
            else:
                st.error(f"❌ 任务失败被终止！{ota_state['current_msg']}")

            file_name = f"OTA_Log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            st.download_button(
                label="📥 下载本次任务的完整 TX/RX 报文日志 (.txt)",
                data="\n".join(ota_state["logs"]),
                file_name=file_name,
                mime="text/plain",
                type="secondary",
                use_container_width=True
            )

            st.divider()
            if st.button("🔄 清除当前任务状态，发起新升级", type="primary"):
                ota_state["is_running"] = False
                ota_state["result"] = None
                st.rerun()

    else:
        available_ports = modbus_comm.get_available_ports()
        if not available_ports:
            available_ports = ["COM1"]

        st.subheader("🔌 1. 硬件连接配置")
        c1, c2, c3 = st.columns(3)
        with c1:
            ota_port = st.selectbox("选择串口", available_ports, key="ota_port")
        with c2:
            ota_baudrate = st.selectbox("波特率", [9600, 19200, 38400, 57600, 115200], index=0, key="ota_baud")
        with c3:
            ota_slave = st.number_input("设备站号 (Slave ID)", min_value=1, max_value=247, value=1, key="ota_slave")

        st.divider()
        st.subheader("📁 2. 固件文件与偏移设置")
        c4, c5 = st.columns([2, 1])
        with c4:
            bin_file = st.file_uploader("上传固件升级包 (.bin 文件)", type=['bin'])
        with c5:
            offset_input = st.text_input("文件偏移量 (Offset)", value="0", help="可填十进制或十六进制")

        st.divider()
        st.subheader("⚙️ 3. 高级通讯参数 (Flash写入适配)")
        c6, c7 = st.columns(2)
        with c6:
            ota_timeout = st.number_input("通讯超时 (秒)", min_value=0.1, value=1.0)
        with c7:
            ota_delay = st.number_input("包间延迟 (秒)", min_value=0.0, value=0.0)

        st.divider()

        if st.button("🚀 创建后台升级任务", type="primary", use_container_width=True):
            if bin_file is None:
                st.warning("⚠️ 请先上传 .bin 固件文件！")
            else:
                try:
                    offset_val = int(offset_input, 0)
                    bin_bytes = bin_file.getvalue()
                    if offset_val >= len(bin_bytes):
                        st.error("❌ 偏移量过大！")
                    else:
                        threading.Thread(
                            target=ota_engine.run_ota_upgrade,
                            args=(ota_port, ota_baudrate, ota_slave, bin_bytes, offset_val, ota_state, ota_timeout,
                                  ota_delay),
                            daemon=True
                        ).start()
                        st.rerun()
                except ValueError:
                    st.error("❌ 偏移量格式错误！")

# ==========================================
# 🌟 工具 5：串口报文监控
# ==========================================
elif tool_choice == "5. 串口报文监控":
    st.title("📡 串口报文实时监控与行车记录仪")
    st.markdown("利用系统级底层线程抓取 HEX 报文，不受页面切换影响。自动切片并限制容量 1GB。")

    LOG_DIR = "serial_logs"
    MAX_FILE_SIZE = 10 * 1024 * 1024
    MAX_FOLDER_SIZE = 1024 * 1024 * 1024

    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)


    def manage_log_rotation():
        files = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")), key=os.path.getmtime)
        total_size = sum(os.path.getsize(f) for f in files)
        while total_size > MAX_FOLDER_SIZE and files:
            oldest_file = files.pop(0)
            size = os.path.getsize(oldest_file)
            os.remove(oldest_file)
            total_size -= size


    def append_to_serial_log(log_line):
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

# ==========================================
# 工具 6：跨文件表格字典匹配
# ==========================================
elif tool_choice == "6. 跨文件表格字典匹配":
    st.title("📚 跨文件表格字典批量匹配")
    st.markdown(
        "上传海量字典/翻译文件，支持 **单关键词搜索** 或 **导入文件批量搜索**，极速跨文件跨 Sheet 检索目标词汇，并提取相关属性。")
    st.divider()

    search_mode = st.radio("🔍 请选择检索模式",
                           ["A. 单关键词检索 (手动输入)", "B. 批量文件检索 (上传包含待查字段的 Excel/CSV)"],
                           horizontal=True)

    search_targets = []

    st.subheader("1️⃣ 配置查询目标")
    c_q1, c_q2 = st.columns(2)

    if search_mode.startswith("A"):
        with c_q1:
            single_keyword = st.text_input("要搜索的关键词", value="机组无备妥信号")
            if single_keyword.strip():
                search_targets = [single_keyword.strip()]
    else:
        with c_q1:
            query_file = st.file_uploader("上传待查询的文件 (.xlsx, .csv)", type=['xlsx', 'xls', 'csv'], key='q_file')
        with c_q2:
            query_col = st.text_input("待查询文件中的【列名】", value="待查字段")
            query_header = st.number_input("待查询文件的表头所在行 (0=第1行)", value=0, min_value=0, step=1)

        if query_file is not None and query_col:
            try:
                if query_file.name.endswith('.csv'):
                    df_q = pd.read_csv(query_file, header=query_header)
                else:
                    df_q = pd.read_excel(query_file, header=query_header)

                if query_col in df_q.columns:
                    search_targets = df_q[query_col].dropna().astype(str).str.strip().unique().tolist()
                    st.success(f"✅ 成功从文件中提取了 {len(search_targets)} 个不重复的待查询词汇！")
                else:
                    st.error(f"❌ 找不到列名：'{query_col}'，请检查表头所在行是否设置正确。")
            except Exception as e:
                st.error(f"读取查询文件出错: {e}")

    st.divider()

    st.subheader("2️⃣ 配置字典库读取规则")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        zh_col = st.text_input("查找列 (字典表头)", value="title.cn", help="以此列的内容作为搜索目标")
    with c2:
        extract_cols_str = st.text_input("提取列 (支持多列，逗号隔开)", value="title.en, address, offset, bits",
                                         help="匹配成功后，同时提取这些列的内容")
    with c3:
        dict_header = st.number_input("字典表头所在行 (0=第1行)", value=2, min_value=0, step=1)

    c4, c5 = st.columns([3, 1])
    with c4:
        ffill_cols_str = st.text_input("🛠️ 修复合并单元格 (填入列名，逗号隔开)", value="address, offset",
                                       help="自动向下填充这些列的空值，解决 Excel 合并单元格读取为空的问题。")
    with c5:
        st.markdown("<br>", unsafe_allow_html=True)
        exact_match = st.toggle("🎯 开启精确匹配", value=True)

    st.divider()

    st.subheader("3️⃣ 上传字典库文件并执行")
    uploaded_dicts = st.file_uploader("支持同时框选上传多个 .xlsx / .csv 字典文件", type=['xlsx', 'xls', 'csv'],
                                      accept_multiple_files=True)

    if st.button("🚀 开始跨文件批量匹配", type="primary", use_container_width=True):
        if not search_targets:
            st.warning("⚠️ 没有有效的查询词汇，请检查步骤 1！")
        elif not uploaded_dicts:
            st.warning("⚠️ 请先在步骤 3 上传至少一个字典库文件！")
        else:
            extract_cols = [col.strip() for col in extract_cols_str.split(',') if col.strip()]
            ffill_cols = [col.strip() for col in ffill_cols_str.split(',') if col.strip()]

            results = []
            with st.spinner(f"正在疯狂检索 {len(search_targets)} 个目标词汇..."):
                for file in uploaded_dicts:
                    try:
                        if file.name.endswith('.csv'):
                            dfs = {'默认表': pd.read_csv(file, header=dict_header)}
                        else:
                            xls = pd.ExcelFile(file)
                            dfs = {sheet: pd.read_excel(xls, sheet_name=sheet, header=dict_header) for sheet in
                                   xls.sheet_names}

                        for sheet_name, df in dfs.items():
                            if zh_col in df.columns:
                                for fc in ffill_cols:
                                    if fc in df.columns:
                                        df[fc] = df[fc].ffill()

                                df_clean = df.dropna(subset=[zh_col]).copy()
                                df_clean['__search_col__'] = df_clean[zh_col].astype(str).str.strip()

                                for target in search_targets:
                                    if exact_match:
                                        matches = df_clean[df_clean['__search_col__'] == target]
                                    else:
                                        matches = df_clean[
                                            df_clean['__search_col__'].str.contains(target, na=False, regex=False)]

                                    for _, row in matches.iterrows():
                                        item_result = {
                                            '检索词汇 (目标)': target,
                                            '来源字典文件': file.name,
                                            '所在 Sheet 页': sheet_name,
                                            f'查找内容 ({zh_col})': row[zh_col]
                                        }

                                        for col in extract_cols:
                                            if col in df.columns:
                                                item_result[col] = row[col]
                                            else:
                                                item_result[col] = ""

                                        inferred_type = "integer"
                                        bits_val = row['bits'] if 'bits' in df.columns else None
                                        scale_val = row['scale'] if 'scale' in df.columns else None

                                        if pd.notna(bits_val) and str(bits_val).strip() != "":
                                            inferred_type = "enum"
                                        else:
                                            if pd.notna(scale_val) and str(scale_val).strip() != "":
                                                try:
                                                    if float(scale_val) < 1:
                                                        inferred_type = "float"
                                                except ValueError:
                                                    pass

                                        item_result['推断数据类型 (DataType)'] = inferred_type
                                        results.append(item_result)
                    except Exception as e:
                        st.error(f"❌ 解析字典文件 [{file.name}] 时发生异常: {str(e)}")

            if results:
                st.success(f"🎉 匹配圆满成功！共找到了 {len(results)} 条记录。")
                results_df = pd.DataFrame(results)
                st.dataframe(results_df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    results_df.to_excel(writer, index=False, sheet_name='智能匹配提取结果')
                excel_data = output.getvalue()

                st.download_button(
                    label=f"📥 下载智能匹配提取结果.xlsx",
                    data=excel_data,
                    file_name=f"智能提取结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.warning(f"😭 未能找到匹配项。请确认配置是否正确。")


# ==========================================
# 🌟 工具 7：网关云端联动检测
# ==========================================
elif tool_choice == "7. 网关云端联动检测":
    st.title("🌐 智能网关云端联动自动化检测")
    st.markdown("将电脑作为虚拟 Modbus 从站，自动注入随机数据，并等待网关采集后与云端 API 实际接收的数据进行严格比对。")
    st.divider()

    st.subheader("🔌 1. 硬件连接与协议配置")
    available_ports = modbus_comm.get_available_ports()
    if not available_ports:
        available_ports = ["COM1"]

    c1, c2, c3 = st.columns(3)
    with c1:
        gw_port = st.selectbox("本机模拟串口", available_ports, help="网关的 RS485 采集线应连接到此串口")
    with c2:
        gw_baud = st.selectbox("波特率", [9600, 19200, 38400, 57600, 115200], index=0)
    with c3:
        gw_slave = st.number_input("模拟的站号 (Slave ID)", min_value=1, max_value=247, value=1)

    st.subheader("☁️ 2. 云端 API 抓包凭证配置")
    with st.expander("点击展开配置 API 参数 (Token/Cookie)", expanded=True):
        cloud_url = st.text_input("云端请求接口 URL",
                                  value="https://mibp.midea.com/api/apps-device-cloud/v1/device/v2/getDeviceData?nid=EDGECHILLER/EDGECHILLER_0000CC311625MDG58A60360007920000/magneticLevitationChiller/0001006666661OTA650TEST002470000")
        cloud_cookie = st.text_input("Cookie", placeholder="请填入最新的 Cookie 字符串", type="password")
        cloud_session = st.text_input("SSO-Session", placeholder="请填入最新的 SSO-Session", type="password")

    st.subheader("📄 3. 上传点表与测试参数")
    c4, c5, c6 = st.columns([2, 1, 1])
    with c4:
        dict_file = st.file_uploader("上传解析字典 (.csv / .xlsx)", type=['csv', 'xlsx'])
    with c5:
        test_count = st.number_input("随机测试几个测点?", min_value=1, max_value=100, value=5)
    with c6:
        wait_time = st.number_input("网关上报等待时间 (秒)", min_value=5, max_value=120, value=15,
                                    help="留足时间让网关读取并推送到云端")

    # 🌟 核心新增：地址偏移修正设置项
    c7, c8 = st.columns(2)
    with c7:
        dict_header_row = st.number_input("点表表头所在行 (0=第1行)", value=2, min_value=0, step=1,
                                          help="用来跳过无用的空行")
    with c8:
        addr_shift = st.number_input("🛠️ 底层地址偏移修正", value=-1, step=1,
                                     help="经典 Base-0/Base-1 问题。如果表格地址比实际大1，请保持 -1，程序会自动把读取的地址全部减去 1。")

    st.divider()


    # --- 核心解析：增加对 bits 和 offset 修正的支持 ---
    def load_conversion_table(file_obj, header_idx, shift_val):
        table = {}
        try:
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj, header=header_idx)
            else:
                df = pd.read_excel(file_obj, header=header_idx)

            if 'address' in df.columns: df['address'] = df['address'].ffill()
            if 'offset' in df.columns: df['offset'] = df['offset'].ffill()

            for _, row in df.iterrows():
                name = row.get('name')
                offset = row.get('offset')
                if pd.isna(name) or pd.isna(offset): continue

                bits_val = None
                bits_raw = row.get('bits')
                if pd.notna(bits_raw) and str(bits_raw).strip() != "":
                    try:
                        bits_val = int(float(bits_raw))
                    except Exception:
                        pass

                # 🌟 加入偏移量修正逻辑
                real_offset = int(float(offset)) + shift_val

                table[name] = {
                    'offset': real_offset,
                    'table_original_offset': int(float(offset)),
                    'bits': bits_val,
                    'scale': float(row.get('scale')) if 'scale' in df.columns and pd.notna(row.get('scale')) else 1.0,
                    'add': float(row.get('add')) if 'add' in df.columns and pd.notna(row.get('add')) else 0.0,
                    'sub': float(row.get('sub')) if 'sub' in df.columns and pd.notna(row.get('sub')) else 0.0,
                    'signed': str(row.get('signed', '')).strip().lower() in ['1', 'true', 'y', '1.0']
                }
            return table
        except Exception as e:
            st.error(f"❌ 读取点表失败: {e}")
            return None


    def calculate_expected_value(raw_value, rule):
        expected = (raw_value * rule['scale']) + rule['add'] - rule['sub']
        return round(expected, 2)


    def extract_value_from_json(json_data, property_name):
        if not json_data or not json_data.get("data"): return None
        for group in json_data["data"]:
            for item in group.get("groupRealDatas", []):
                if item.get("key") == property_name:
                    try:
                        return round(float(item.get("value")), 2)
                    except (ValueError, TypeError):
                        val_str = item.get("value")
                        if val_str is True: return 1
                        if val_str is False: return 0
                        return val_str
        return None


    if st.button("🚀 启动全链路联动测试", type="primary", use_container_width=True):
        if dict_file is None:
            st.warning("请先上传解析字典！")
        elif not cloud_cookie or not cloud_session:
            st.warning("云端接口凭证 (Cookie 和 Session) 不能为空！")
        else:
            table = load_conversion_table(dict_file, dict_header_row, addr_shift)
            if table and len(table) > 0:
                st.info(f"✅ 成功加载点表，共解析出 {len(table)} 个有效测点。")

                store = SlaveContext(
                    di=ModbusSequentialDataBlock(0, [0] * 10000),
                    co=ModbusSequentialDataBlock(0, [0] * 10000),
                    hr=ModbusSequentialDataBlock(0, [0] * 10000),
                    ir=ModbusSequentialDataBlock(0, [0] * 10000)
                )

                try:
                    context = ModbusServerContext(slaves=store, single=True)
                except TypeError:
                    try:
                        context = ModbusServerContext(devices=store, single=True)
                    except TypeError:
                        context = ModbusServerContext(store, single=True)


                def run_modbus_rtu_slave():
                    StartSerialServer(
                        context=context, framer=FRAMER, port=gw_port,
                        baudrate=gw_baud, bytesize=8, parity='N', stopbits=1
                    )


                server_thread = threading.Thread(target=run_modbus_rtu_slave, daemon=True)
                server_thread.start()
                time.sleep(1)

                try:

                    # 🌟 核心修改：确保最大测试数量不超过 100，且不超过有效点表的总长度
                    actual_test_count = min(int(test_count), 500, len(table))
                    # 🌟 核心修改：真正的随机打乱抽取，而不是只测最前面的几个！
                    test_targets = random.sample(list(table.keys()), actual_test_count)
                    injected_data = {}

                    st.markdown("### 💉 正在向本机内存注入随机测试数据...")
                    log_text = ""
                    for name in test_targets:
                        rule = table[name]
                        offset = rule['offset']
                        original_offset = rule['table_original_offset']
                        bits_val = rule['bits']

                        current_val = 0
                        try:
                            try:
                                c_vals = context[0].getValues(3, offset, count=1)
                                if c_vals: current_val = c_vals[0]
                            except KeyError:
                                c_vals = context[gw_slave].getValues(3, offset, count=1)
                                if c_vals: current_val = c_vals[0]
                        except Exception:
                            pass

                        if bits_val is not None:
                            raw_val = random.randint(0, 1)
                            write_val = (current_val & ~(1 << bits_val)) | (raw_val << bits_val)
                            log_text += f"- 注入测点 **{name}** (表内地址:{original_offset} -> 底层地址:{offset}, Bit:{bits_val}) -> 随机位: `{raw_val}` (最终寄存器 HEX: `{write_val:04X}`)\n"
                        else:
                            raw_val = random.randint(-50, 200) if rule['signed'] else random.randint(0, 1000)
                            write_val = raw_val & 0xFFFF if raw_val < 0 else raw_val & 0xFFFF
                            log_text += f"- 注入测点 **{name}** (表内地址:{original_offset} -> 底层地址:{offset}) -> 随机值: `{raw_val}` (最终寄存器 HEX: `{write_val:04X}`)\n"

                        try:
                            context[0].setValues(3, offset, [write_val])
                        except KeyError:
                            pass
                        try:
                            context[gw_slave].setValues(3, offset, [write_val])
                        except KeyError:
                            pass

                        injected_data[name] = raw_val

                    st.info(log_text)

                    progress_text = "⏳ 等待网关通过 RS485 采集数据并推送到云端..."
                    my_bar = st.progress(0, text=progress_text)
                    for percent_complete in range(100):
                        time.sleep(wait_time / 100.0)
                        my_bar.progress(percent_complete + 1,
                                        text=f"{progress_text} 剩余 {int(wait_time - (wait_time * percent_complete / 100))} 秒")
                    my_bar.progress(100, text="采集等待结束，开始验证云端数据！")

                    st.markdown("### ☁️ 云端数据校验结果")
                    headers = {
                        "accept": "application/json, text/plain, */*",
                        "cookie": cloud_cookie,
                        "sso-session": cloud_session,
                        "user-agent": "Mozilla/5.0"
                    }

                    try:
                        response = requests.get(cloud_url, headers=headers, timeout=10)
                        response.raise_for_status()
                        cloud_json = response.json()

                        result_list = []
                        passed = failed = 0

                        for name, raw_val in injected_data.items():
                            rule = table[name]
                            expected_val = calculate_expected_value(raw_val, rule)
                            actual_val = extract_value_from_json(cloud_json, name)

                            if actual_val is None:
                                status_icon, actual_str = "❌ 未上报", "获取不到数据"
                                failed += 1
                            elif expected_val == actual_val:
                                status_icon, actual_str = "✅ PASS", str(actual_val)
                                passed += 1
                            else:
                                status_icon, actual_str = "❌ FAIL", str(actual_val)
                                failed += 1

                            result_list.append({
                                "测点名称 (name)": name,
                                "本地注入原始值": raw_val,
                                "预期云端值 (计算后)": expected_val,
                                "实际云端读取值": actual_str,
                                "测试结论": status_icon
                            })

                        res_df = pd.DataFrame(result_list)
                        st.dataframe(res_df, use_container_width=True)

                        if failed == 0:
                            st.balloons()
                            st.success(f"🎉 自动化测试完美通过！测试 {passed + failed} 项，全部 PASS。")
                        else:
                            st.error(f"⚠️ 测试结束。PASS: {passed} 项，FAIL: {failed} 项。请核对转换系数或网关配置。")

                    except Exception as api_err:
                        st.error(f"❌ 云端 API 请求失败，请检查 Cookie 是否过期或网络是否畅通。详细报错: {api_err}")

                finally:
                    try:
                        if ServerStop: ServerStop()
                        time.sleep(0.5)
                    except Exception:
                        pass
            else:
                st.error("未能从点表中解析出有效的参数，请检查表头所在行。")