import streamlit as st
from utils import modbus_comm


def render():
    st.title("🏷️ 机组 SN 条码写入")
    st.markdown(
        "通过 Modbus 串口将机组 SN 码（字符串）写入底层设备。自动将字符串处理为 32 位（不足补字符 '0'），并分配为 16 个双字节寄存器。")
    st.divider()

    available_ports = modbus_comm.get_available_ports()
    if not available_ports:
        st.warning("⚠️ 未检测到可用的串口，请检查硬件连接或使用虚拟串口软件(如 VSPD)。")
        available_ports = ["COM1"]

    st.subheader("🔌 1. 硬件连接配置")
    c1, c2, c3 = st.columns(3)
    with c1:
        com_port = st.selectbox("选择串口", available_ports, key="sn_port")
    with c2:
        baudrate = st.selectbox("波特率", [4800,9600, 19200, 38400, 57600, 115200], index=0, key="sn_baud")
    with c3:
        slave_id = st.number_input("设备站号 (Slave ID)", min_value=1, max_value=247, value=1, key="sn_slave")

    st.divider()

    st.subheader("📝 2. SN 数据配置")
    sn_input = st.text_input("请输入机组 SN 码 (仅限英文字母和数字)", value="0001006666661LEIFAYIN00002220000",
                             help="默认要求 32 位长度，不足 32 位会自动在末尾补充字符 '0'。")

    st.divider()

    if st.button("🚀 编码并执行写入", type="primary", use_container_width=True):
        if not sn_input:
            st.warning("⚠️ 请先输入要写入的 SN 码！")
            return

        with st.spinner("正在编码并下发指令..."):
            try:
                # ---------------------------------------------------------
                # 🌟 核心修改：长度处理（截断或补字符 '0' 到恰好 32 位）
                # ---------------------------------------------------------
                processed_sn = sn_input
                if len(processed_sn) > 32:
                    st.warning("⚠️ 输入的 SN 码超过 32 位，已自动截断前 32 个字符！")
                    processed_sn = processed_sn[:32]
                elif len(processed_sn) < 32:
                    # 使用 ljust 在字符串右侧（末尾）填充 '0' 直到 32 位
                    # 如果你希望在左侧（开头）补 '0'，请将 ljust 改为 rjust
                    processed_sn = processed_sn.ljust(32, '0')

                st.info(f"ℹ️ 实际下发的 32 位 SN 字符串为: `{processed_sn}`")

                # 1. 字符串转 ASCII 字节流 (现在长度绝对是 32 字节)
                sn_bytes = processed_sn.encode('ascii')

                # 2. 将字节流按每 2 个字节拼接成一个 16 位的寄存器数值
                sn_registers = []
                for i in range(0, len(sn_bytes), 2):
                    high_byte = sn_bytes[i]
                    low_byte = sn_bytes[i + 1]
                    reg_val = (high_byte << 8) | low_byte
                    sn_registers.append(reg_val)

                # 3. 拼接总负载：地址 950 写入 0xAA (即十进制 170)
                # 其后 951 到 966 开始接 16 个 SN 寄存器
                start_address = 950
                payload = [0x00AA] + sn_registers

                # 4. 触发 0x10 功能码连续写入
                success, result = modbus_comm.master_write_10(
                    com_port, baudrate, slave_id, start_address, payload
                )

                if success:
                    st.success(f"✅ 写入成功！")
                    st.success(f"**数据分布详情：**\n"
                               f"- 地址 **950** 写入指令符: `0x00AA`\n"
                               f"- 地址 **951 - {951 + len(sn_registers) - 1}** 写入 32 位 SN 数据 (共 {len(sn_registers)} 个寄存器):\n"
                               f"`{[f'0x{v:04X}' for v in sn_registers]}`\n"
                               f"(发送的总寄存器数量: {len(payload)} 个)")
                else:
                    st.error(f"❌ 写入失败，请检查串口占用或设备状态: {result}")

            except UnicodeEncodeError:
                st.error("❌ 编码错误！SN 码只能包含标准的英文字母、数字或普通符号，不能包含中文！")
            except Exception as e:
                st.error(f"❌ 发生未知异常: {e}")