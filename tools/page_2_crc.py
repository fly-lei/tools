import streamlit as st
from utils import crc_calculator

def render():
    st.title("🧮 Modbus CRC16 校验计算器")
    st.markdown("快速计算十六进制报文的 Modbus CRC16 校验码，支持带空格或连写的输入。")
    st.divider()
    # ...(将原 app.py 中工具 2 的剩余所有代码贴到这里，注意缩进)
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