import streamlit as st
import time
import threading
from utils import modbus_comm, ota_engine


# ==========================================
# 🌟 高级黑魔法：日志代理拦截器
# 作用：不修改底层 engine 代码，动态给每行日志加前缀
# ==========================================
class LogInterceptor:
    def __init__(self, real_list, prefix):
        self.real_list = real_list
        self.prefix = prefix

    def append(self, item):
        self.real_list.append(f"[{self.prefix}] {item}")

    def extend(self, items):
        self.real_list.extend([f"[{self.prefix}] {i}" for i in items])

    def __getitem__(self, key): return self.real_list[key]

    def __len__(self): return len(self.real_list)

    def __iter__(self): return iter(self.real_list)

    def pop(self, *args): return self.real_list.pop(*args)

    def clear(self): self.real_list.clear()


class OtaStateProxy(dict):
    """全局状态字典的代理封装"""

    def __init__(self, real_state, file_name):
        super().__init__(real_state)
        self.real_state = real_state
        self.log_proxy = LogInterceptor(real_state["logs"], file_name)

    def __getitem__(self, key):
        if key == "logs":
            return self.log_proxy
        return self.real_state[key]

    def __setitem__(self, key, value):
        self.real_state[key] = value

    def get(self, key, default=None):
        if key == "logs":
            return self.log_proxy
        return self.real_state.get(key, default)

    def __contains__(self, key):
        return key in self.real_state


# ==========================================
# 批量排队工作线程 (加入多地址连续写入支持)
# ==========================================
def batch_ota_worker(port, baud, files_data, loop_count, wait_minutes, ota_state, timeout, delay):
    total_runs = loop_count * len(files_data)
    current_run = 0
    wait_seconds = int(wait_minutes * 60)

    success_count = 0
    fail_count = 0

    for loop in range(loop_count):
        # files_data 结构: (file_name, bin_bytes, offset_val, slave_val, pre_cmds, post_cmds)
        for file_name, bin_bytes, offset_val, slave_val, pre_cmds, post_cmds in files_data:
            current_run += 1

            ota_state["is_running"] = True
            ota_state["result"] = None
            ota_state["progress"] = 0.0
            ota_state[
                "progress_text"] = f"🚀 [{current_run}/{total_runs}] 升级: {file_name} (站号: {slave_val}, 循环 {loop + 1}/{loop_count})"
            ota_state["current_msg"] = f"开始向站号 {slave_val} 下发 {file_name} ..."
            ota_state["msg_status"] = "info"

            ota_state["logs"].append(
                f"\n{'=' * 55}\n📍 开始第 {current_run}/{total_runs} 个任务: 【{file_name}】 -> 站号: {slave_val}\n{'=' * 55}")

            proxy_state = OtaStateProxy(ota_state, file_name)

            # ========================================================
            # 🌟 前置操作 (支持多条独立指令)
            # ========================================================
            if pre_cmds:
                ota_state["current_msg"] = f"⏳ 准备升级！正在执行前置操作 (共 {len(pre_cmds)} 条指令)..."
                for p_addr, p_vals in pre_cmds:
                    ota_state["logs"].append(f"▶️ [前置操作] 准备向站号 {slave_val} 地址 {p_addr} 写入: {p_vals}")
                    write_ok, write_res = modbus_comm.master_write_10(port, baud, slave_val, p_addr, p_vals)
                    if write_ok:
                        ota_state["logs"].append(f"✅ [前置操作] 成功: {write_res}")
                    else:
                        ota_state["logs"].append(f"⚠️ [前置操作] 失败: {write_res}")
                    time.sleep(0.3)  # 多条指令之间的小缓冲

                ota_state["logs"].append(f"⏳ 前置操作执行完毕，等待 1.5 秒以便设备完成状态切换...")
                time.sleep(1.5)

            # 阻塞调用底层引擎执行 OTA
            ota_engine.run_ota_upgrade(port, baud, slave_val, bin_bytes, offset_val, proxy_state, timeout, delay)

            is_success = ota_state.get("result", False)
            if is_success:
                success_count += 1
                msg_prefix = f"✅ {file_name} 升级成功！"

                # ========================================================
                # 🌟 后置操作 (支持多条独立指令)
                # ========================================================
                if post_cmds:
                    ota_state["current_msg"] = f"✅ 升级成功！正在执行后置操作 (共 {len(post_cmds)} 条指令)..."
                    time.sleep(0.5)
                    for p_addr, p_vals in post_cmds:
                        ota_state["logs"].append(f"▶️ [后置操作] 准备向站号 {slave_val} 地址 {p_addr} 写入: {p_vals}")
                        write_ok, write_res = modbus_comm.master_write_10(port, baud, slave_val, p_addr, p_vals)
                        if write_ok:
                            ota_state["logs"].append(f"✅ [后置操作] 成功: {write_res}")
                        else:
                            ota_state["logs"].append(f"⚠️ [后置操作] 失败: {write_res}")
                        time.sleep(0.3)
                    msg_prefix += " (且后置指令已执行)"
            else:
                fail_count += 1
                msg_prefix = f"❌ {file_name} 升级失败 (已跳过)！"
                ota_state["logs"].append(
                    f"⚠️ 警告：{file_name} (站号:{slave_val}) 发生错误，系统将忽略此错误并继续执行队列...")

            if current_run < total_runs:
                ota_state["is_running"] = True
                ota_state["result"] = None
                ota_state["msg_status"] = "warning"

                for sec in range(wait_seconds, 0, -1):
                    if not ota_state["is_running"]:
                        return
                    ota_state["progress"] = 1.0
                    ota_state["current_msg"] = f"{msg_prefix} 缓冲中... 等待 {sec} 秒后执行下一包。"
                    ota_state["progress_text"] = f"⏳ 等待间隔中 ({sec}s) ..."
                    time.sleep(1)

    ota_state["is_running"] = False
    ota_state["result"] = True

    if fail_count == 0:
        ota_state["current_msg"] = f"🎉 批量循环升级圆满完成！共成功执行 {success_count} 次刷录。"
        ota_state["msg_status"] = "success"
    else:
        ota_state[
            "current_msg"] = f"批量队列执行结束！✅ 成功: {success_count} 次，❌ 失败: {fail_count} 次。请查看日志排查失败项。"
        ota_state["msg_status"] = "warning"


# ==========================================
# 辅助函数：解析带分号的复杂指令字符串
# ==========================================
def parse_multi_cmds(addr_str, val_str, task_name, cmd_type):
    """
    将 "0x00; 0x10" 和 "1; 100, 200"
    解析为 [(0, [1]), (16, [100, 200])]
    """
    addr_str = addr_str.replace('；', ';').strip()
    val_str = val_str.replace('；', ';').strip()

    if not addr_str and not val_str:
        return []
    if bool(addr_str) != bool(val_str):
        raise ValueError(f"❌ 卡片【{task_name}】的【{cmd_type}】配置不完整！地址和数值要么都填，要么都留空。")

    a_parts = [x.strip() for x in addr_str.split(';') if x.strip()]
    v_parts = [x.strip() for x in val_str.split(';') if x.strip()]

    if len(a_parts) != len(v_parts):
        raise ValueError(f"❌ 卡片【{task_name}】的【{cmd_type}】地址数与数值组数不匹配 (分号数量不对)！")

    cmds = []
    try:
        for i in range(len(a_parts)):
            addr = int(a_parts[i], 0)
            vals = [int(v.strip(), 0) for v in v_parts[i].split(',') if v.strip()]
            if not vals:
                raise ValueError
            cmds.append((addr, vals))
    except Exception:
        raise ValueError(f"❌ 卡片【{task_name}】的【{cmd_type}】格式错误！请检查十六进制和标点符号。")
    return cmds


# ==========================================
# UI 渲染层
# ==========================================
def render():
    st.title("💽 OTA 机组固件在线升级 (Modbus)")
    st.markdown("支持**可视化添加多任务卡片**、**连续下发多条自动化控制指令**以及循环压测。")
    st.divider()

    ota_state = st.session_state.ota_state

    if ota_state["is_running"] or ota_state["result"] is not None:
        st.subheader("🔄 升级任务监视器")

        if ota_state["is_running"]:
            st.warning("⚠️ 批量升级任务正在后台排队执行中，请勿断开物理设备电源！您可以随意关闭网页，稍后再来查看。")
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
                if ota_state["msg_status"] == "warning":
                    st.warning(f"🏁 {ota_state['current_msg']}")
                else:
                    st.success(f"🎉 {ota_state['current_msg']}")
            else:
                st.error(f"❌ 任务被强制终止！{ota_state['current_msg']}")

            file_name = f"OTA_Batch_Log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            st.download_button(
                label="📥 下载本次批量任务的完整 TX/RX 报文日志 (.txt)",
                data="\n".join(ota_state["logs"]),
                file_name=file_name,
                mime="text/plain",
                type="secondary",
                use_container_width=True
            )

            st.divider()
            if st.button("🔄 清除当前任务状态，发起新队列", type="primary"):
                ota_state["is_running"] = False
                ota_state["result"] = None
                ota_state["logs"] = []
                st.rerun()

    else:
        available_ports = modbus_comm.get_available_ports()
        if not available_ports:
            available_ports = ["COM1"]

        st.subheader("🔌 1. 全局通讯口配置")
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            ota_port = st.selectbox("选择串口", available_ports, key="ota_port")
        with c_p2:
            ota_baudrate = st.selectbox("波特率", [4800, 9600, 19200, 38400, 57600, 115200], index=0, key="ota_baud")

        st.divider()

        st.subheader("📁 2. 升级设备与固件队列")

        if 'ota_task_count' not in st.session_state:
            st.session_state.ota_task_count = 1

        c_add, c_del, _ = st.columns([2, 2, 6])
        with c_add:
            if st.button("➕ 添加一个升级设备", use_container_width=True):
                st.session_state.ota_task_count += 1
                st.rerun()
        with c_del:
            if st.button("➖ 移除最后一个设备", use_container_width=True):
                if st.session_state.ota_task_count > 1:
                    st.session_state.ota_task_count -= 1
                    st.rerun()
                else:
                    st.toast("至少需要保留一个设备任务！", icon="⚠️")

        task_configs = []
        for i in range(st.session_state.ota_task_count):
            with st.container(border=True):
                st.markdown(f"**📦 设备任务 {i + 1}**")
                tc1, tc2, tc3 = st.columns([1, 1, 2])
                with tc1:
                    slave_val = st.number_input("设备站号", min_value=1, max_value=247, value=1, key=f"slave_{i}")
                with tc2:
                    offset_val = st.text_input("文件偏移地址", value="0", help="支持十六进制(如 0x1000)或十进制",
                                               key=f"offset_{i}")
                with tc3:
                    bin_file = st.file_uploader("上传专属固件 (.bin)", type=['bin'], key=f"file_{i}")

                # 🌟 前置/后置附加操作UI (更新提示说明)
                with st.expander("🛠️ 高级：升级前/后附加操作 (支持多指令分号隔开)", expanded=False):
                    st.markdown("**➡️ 升级前操作 (例如：进入 Bootloader 模式)**")
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        pre_addr = st.text_input("触发指令地址 (多个用分号 ; 隔开)", value="", key=f"pre_addr_{i}",
                                                 help="例如: 0x00 ; 0x10")
                    with ec2:
                        pre_val = st.text_input("写入数值 (多组用分号 ; 隔开)", value="", key=f"pre_val_{i}",
                                                help="例如: 1 ; 100, 200")

                    st.markdown("**⬅️ 升级后操作 (例如：校验生效 / 软重启)**")
                    ec3, ec4 = st.columns(2)
                    with ec3:
                        post_addr = st.text_input("触发指令地址 (多个用分号 ; 隔开)", value="", key=f"post_addr_{i}",
                                                  help="留空则不执行")
                    with ec4:
                        post_val = st.text_input("写入数值 (多组用分号 ; 隔开)", value="", key=f"post_val_{i}",
                                                 help="如: 0x55AA ; 1")

                task_configs.append({
                    "slave": slave_val,
                    "offset": offset_val,
                    "file": bin_file,
                    "pre_addr": pre_addr,
                    "pre_val": pre_val,
                    "post_addr": post_addr,
                    "post_val": post_val
                })

        st.divider()
        st.subheader("⚙️ 3. 循环压测与高级参数")
        c6, c7, c8, c9 = st.columns(4)
        with c6:
            loop_count = st.number_input("♻️ 队列循环执行次数", min_value=1, max_value=10000, value=1,
                                         help="上面所有卡片按顺序执行完算 1 次。")
        with c7:
            wait_minutes = st.number_input("⏱️ 设备间冷却等待(分钟)", min_value=0.0, max_value=60.0, value=1.0,
                                           step=0.5, help="遇到错误或正常刷完后，等待设备的缓冲时间。")
        with c8:
            ota_timeout = st.number_input("通讯超时 (秒)", min_value=0.1, value=1.0)
        with c9:
            ota_delay = st.number_input("包间延迟 (秒)", min_value=0.0, value=0.0)

        st.divider()

        if st.button("🚀 压入队列并启动后台升级任务", type="primary", use_container_width=True):
            files_data = []
            has_error = False

            for i, task in enumerate(task_configs):
                if task["file"] is None:
                    st.error(f"❌ 卡片【设备任务 {i + 1}】未上传固件！")
                    has_error = True
                    break

                try:
                    offset_int = int(task["offset"], 0)
                except ValueError:
                    st.error(f"❌ 卡片【设备任务 {i + 1}】的偏移地址格式错误！")
                    has_error = True
                    break

                bin_bytes = task["file"].getvalue()
                if offset_int >= len(bin_bytes):
                    st.error(f"❌ 卡片【设备任务 {i + 1}】的偏移量 ({offset_int}) 大于文件本身的大小！")
                    has_error = True
                    break

                # 🌟 调用强大的分号解析函数
                try:
                    pre_cmds = parse_multi_cmds(task["pre_addr"], task["pre_val"], f"设备任务 {i + 1}", "前置操作")
                    post_cmds = parse_multi_cmds(task["post_addr"], task["post_val"], f"设备任务 {i + 1}", "后置操作")
                except ValueError as e:
                    st.error(str(e))
                    has_error = True
                    break

                files_data.append((
                    task["file"].name,
                    bin_bytes,
                    offset_int,
                    task["slave"],
                    pre_cmds,  # 传入解析好的前置指令列表 [(addr, [v]), (addr, [v,v])]
                    post_cmds  # 传入解析好的后置指令列表
                ))

            if not has_error:
                ota_state["logs"] = []
                threading.Thread(
                    target=batch_ota_worker,
                    args=(ota_port, ota_baudrate, files_data, loop_count, wait_minutes, ota_state, ota_timeout,
                          ota_delay),
                    daemon=True
                ).start()

                st.rerun()