import streamlit as st
from utils import modbus_engine

def render():
    st.title("🔌 Modbus RTU 日志提取")
    st.markdown("上传现场串口/网络监控日志文件，快速提取指定站号和地址的读写数值，支持跨行粘包解析与导出。")
    st.divider()
    # ...(将原 app.py 中工具 1 的剩余所有代码贴到这里，注意缩进)
# ==========================================
# 工具 1：Modbus 报文解析
# ==========================================


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
