import streamlit as st
import threading

# 导入所有拆分出的页面组件
from tools import page_1_parser, page_2_crc, page_3_master, page_4_ota
from tools import page_5_monitor, page_6_dict, page_7_gateway
from tools import page_8_sn_writer, page_9_simulator,page_10_poller

# 尝试导入 ServerStop 用于页面切换时的资源释放
try:
    from pymodbus.server import ServerStop
except ImportError:
    try:
        from pymodbus.server import StopServer as ServerStop
    except ImportError:
        ServerStop = None

# ==========================================
# 1. 页面基础设置与全局状态初始化
# ==========================================
st.set_page_config(page_title="工业协议解析工具集", page_icon="🧰", layout="wide")

# 串口监控全局状态
if 'mon_logs' not in st.session_state:
    st.session_state.mon_logs = []
if 'is_monitoring' not in st.session_state:
    st.session_state.is_monitoring = False
if 'sniffer_thread' not in st.session_state:
    st.session_state.sniffer_thread = None
if 'sniffer_stop_event' not in st.session_state:
    st.session_state.sniffer_stop_event = threading.Event()

# OTA 任务全局状态
if 'ota_state' not in st.session_state:
    st.session_state.ota_state = {
        "is_running": False,
        "progress": 0.0,
        "progress_text": "",
        "logs": [],
        "current_msg": "",
        "msg_status": "info",
        "result": None
    }

# ==========================================
# 2. 侧边栏导航 (Router)
# ==========================================
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
        "7. 网关云端联动检测",
        "8. 机组SN条码写入",
        "9. Modbus 设备镜像模拟器",
        "10. 多网关并发轮询压测"
    ]
)

# ==========================================
# 🌟 智能生命周期管理：当切换页面时，自动释放串口
# ==========================================
# 注意：这部分必须和外层的 if 齐平（不缩进）
if 'last_tool_choice' not in st.session_state:
    st.session_state.last_tool_choice = tool_choice

if st.session_state.last_tool_choice != tool_choice:
    # 检测到用户切换了左侧的菜单！
    try:
        if ServerStop: ServerStop()  # 强行杀掉后台可能占用的 Modbus 模拟器
        # 清除模拟器的运行状态UI
        if 'sim_running' in st.session_state:
            st.session_state.sim_running = False
    except Exception:
        pass
    st.session_state.last_tool_choice = tool_choice

# ==========================================
# 3. 页面路由分发
# ==========================================
# 注意：这部分也必须退回最外层（不缩进）！
if tool_choice == "1. Modbus 报文解析":
    page_1_parser.render()
elif tool_choice == "2. CRC16 校验计算器":
    page_2_crc.render()
elif tool_choice == "3. Modbus 数据读取":
    page_3_master.render()
elif tool_choice == "4. OTA 机组固件升级":
    page_4_ota.render()
elif tool_choice == "5. 串口报文监控":
    page_5_monitor.render()
elif tool_choice == "6. 跨文件表格字典匹配":
    page_6_dict.render()
elif tool_choice == "7. 网关云端联动检测":
    page_7_gateway.render()
elif tool_choice == "8. 机组SN条码写入":
    page_8_sn_writer.render()
elif tool_choice == "9. Modbus 设备镜像模拟器":
    page_9_simulator.render()
elif tool_choice == "10. 多网关并发轮询压测":
    page_10_poller.render()