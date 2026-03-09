import streamlit as st
import pandas as pd
import time
from utils import modbus_comm

def render():
    st.title("💻 Modbus 主站在线调试 (Master)")
    st.markdown("直接通过串口读取或写入现场设备的寄存器数值，支持 03、04、10 功能码。")
    st.divider()
    # ...(将原 app.py 中工具 3 的剩余所有代码贴到这里，注意缩进)
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