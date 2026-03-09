import streamlit as st
import time
import threading
from utils import modbus_comm, ota_engine


def render():
    st.title("💽 OTA 机组固件在线升级 (Modbus)")
    st.markdown("通过严格的时序校验，支持后台静默刷录。**即使关闭浏览器，任务依然在设备后台执行。**")
    st.divider()

    # 获取全局状态
    ota_state = st.session_state.ota_state
    # ...(将原 app.py 中工具 4 的剩余所有代码贴到这里，注意将原代码中的 ota_state 直接使用当前变量)
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