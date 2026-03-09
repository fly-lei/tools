import streamlit as st
import time
import random
import threading
import requests
import pandas as pd
import logging
from utils import modbus_comm

# ==========================================
# 🌟 Pymodbus 兼容性补丁 (仅在网关模块加载)
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

# 核心解析函数可以直接放在外面
def load_conversion_table(file_obj, header_idx, shift_val):
    # ...(原函数逻辑)...
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
    # ...(原函数逻辑)...
    expected = (raw_value * rule['scale']) + rule['add'] - rule['sub']
    return round(expected, 2)


def extract_value_from_json(json_data, property_name):
    # ...(原函数逻辑)...
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

def render():
    st.title("🌐 智能网关云端联动自动化检测")
    st.markdown("将电脑作为虚拟 Modbus 从站，自动注入随机数据，并等待网关采集后与云端 API 实际接收的数据进行严格比对。")
    st.divider()
    # ...(将原 app.py 中工具 7 下面的所有 UI 搭建、按钮点击、多线程验证逻辑贴到这里)
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