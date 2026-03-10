import streamlit as st
import time
import threading
import random
import pandas as pd
from utils import modbus_comm

# ==========================================
# 🌟 全局独立内存状态 (脱离浏览器存活)
# ==========================================
GLOBAL_POLL_STATE = {
    "is_running": False,
    "progress": 0.0,
    "progress_text": "",
    "success_cnt": 0,
    "fail_cnt": 0,
    "error_logs": [],
    "completed": False
}


def polling_worker(port, baud, tasks, delay, timeout, rounds, is_random_len, max_len, state):
    total_regs_per_round = sum([(task['end'] - task['start'] + 1) for task in tasks])
    total_regs = total_regs_per_round * rounds
    regs_processed = 0

    last_tx = "无 (这是整个队列的第一条指令)"
    last_rx = "无"

    for current_round in range(rounds):
        for task in tasks:
            slave = task['slave']
            start_addr = task['start']
            end_addr = task['end']

            curr_addr = start_addr
            while curr_addr <= end_addr:
                if not state['is_running']: return

                remaining = end_addr - curr_addr + 1
                count = random.randint(1, min(max_len, remaining, 120)) if is_random_len else min(max_len, remaining,
                                                                                                  120)

                current_tx = f"[读 0x03] 站号:{slave} | 地址:{curr_addr} | 数量:{count}"
                state[
                    'progress_text'] = f"🔄 轮次 [{current_round + 1}/{rounds}] | 📡 读取: 站号 {slave} -> 地址 {curr_addr} (数量: {count})"

                r_success, r_res = modbus_comm.master_read(port, baud, slave, 3, curr_addr, count, timeout=timeout)

                if r_success:
                    state['success_cnt'] += 1
                    last_tx = current_tx
                    rx_str = str(r_res) if len(
                        r_res) <= 5 else f"[{r_res[0]}, {r_res[1]}, {r_res[2]}, ..., {r_res[-1]}] (共 {len(r_res)} 个)"
                    last_rx = f"[读取成功] 返回: {rx_str}"
                    vals_to_write = r_res
                else:
                    state['fail_cnt'] += 1
                    state['error_logs'].append(
                        f"❌ 【读取失败】 站号:{slave} 地址:{curr_addr} 数量:{count}\n"
                        f"   ⏮️ [上次 TX]: {last_tx}\n   ⏪ [上次 RX]: {last_rx}\n"
                        f"   ▶️ [本次 TX]: {current_tx}\n   🛑 [原因]: {r_res}"
                    )
                    last_tx = current_tx
                    last_rx = "[读取超时/错误]"
                    vals_to_write = None

                time.sleep(delay)

                if vals_to_write is not None:
                    if not state['is_running']: return

                    current_tx = f"[写 0x10] 站号:{slave} | 地址:{curr_addr} | 数量:{count}"
                    state[
                        'progress_text'] = f"🔄 轮次 [{current_round + 1}/{rounds}] | 💉 回写: 站号 {slave} -> 地址 {curr_addr} (数量: {count})"

                    w_success, w_res = modbus_comm.master_write_10(port, baud, slave, curr_addr, vals_to_write)

                    if w_success:
                        state['success_cnt'] += 1
                        last_tx = current_tx
                        last_rx = f"[写入成功] 确认: {w_res}"
                    else:
                        state['fail_cnt'] += 1
                        state['error_logs'].append(
                            f"❌ 【写入失败】 站号:{slave} 地址:{curr_addr} 数量:{count}\n"
                            f"   ⏮️ [上次 TX]: {last_tx}\n   ⏪ [上次 RX]: {last_rx}\n"
                            f"   ▶️ [本次 TX]: {current_tx}\n   🛑 [原因]: {w_res}"
                        )
                        last_tx = current_tx
                        last_rx = "[写入超时/错误]"

                    time.sleep(delay)

                curr_addr += count
                regs_processed += count
                state['progress'] = min(1.0, regs_processed / max(1, total_regs))

    state['is_running'] = False
    state['completed'] = True


def render():
    st.title("🛰️ 多网关并发轮询压测工具")
    st.markdown(
        "支持自动并发压力测试，严格记录掉线瞬间的前后文。具备全局断线重连能力，**关闭网页去喝杯咖啡，随时重连随时看现场**。")
    st.divider()

    # 🌟 核心绑定：永远指向全局独立内存
    poll_state = GLOBAL_POLL_STATE

    if poll_state["is_running"] or poll_state["completed"]:
        st.subheader("📊 轮询压测实时监控")
        st.progress(poll_state["progress"], text=poll_state["progress_text"])

        m1, m2, m3 = st.columns(3)
        m1.metric("✅ 成功通信次数", poll_state["success_cnt"])
        m2.metric("❌ 失败/超时次数", poll_state["fail_cnt"])
        m3.metric("📈 丢包率",
                  f"{(poll_state['fail_cnt'] / max(1, poll_state['success_cnt'] + poll_state['fail_cnt'])) * 100:.2f}%")

        if poll_state["completed"]:
            st.success("🎉 所有轮询任务已圆满结束！")
        else:
            st.warning("⚠️ 压测正在疯狂进行中。您可以随意关闭网页，数据绝不会丢失！")

        if poll_state["error_logs"]:
            st.error(f"发现 {len(poll_state['error_logs'])} 条失败记录！")
            with st.expander("查看【带前后文快照】的失败日志", expanded=True):
                log_text = "\n\n" + "-" * 60 + "\n\n".join(poll_state["error_logs"])
                st.code(log_text, language="text")
                st.download_button("📥 下载完整追溯日志 (.txt)", log_text,
                                   f"Error_Trace_{time.strftime('%Y%m%d_%H%M%S')}.txt")
        elif poll_state["completed"]:
            st.balloons();
            st.info("全程没有发生任何通信错误。")

        st.divider()
        if st.button("🔄 清除任务状态，返回配置界面", type="primary"):
            poll_state["is_running"] = False
            poll_state["completed"] = False
            poll_state["success_cnt"] = 0
            poll_state["fail_cnt"] = 0
            poll_state["error_logs"] = []
            st.rerun()

        # 如果正在运行，开启自动刷新循环获取底层数据
        if poll_state["is_running"]:
            time.sleep(1)
            st.rerun()
    else:
        available_ports = modbus_comm.get_available_ports()
        if not available_ports: available_ports = ["COM1"]

        st.subheader("🔌 1. 通讯口与压测策略配置")
        c_p1, c_p2, c_p3, c_p4 = st.columns(4)
        with c_p1:
            poll_port = st.selectbox("选择串口", available_ports, key="poll_port")
        with c_p2:
            poll_baud = st.selectbox("波特率", [9600, 19200, 38400, 57600, 115200], index=0)
        with c_p3:
            poll_timeout = st.number_input("响应超时(秒)", min_value=0.1, value=0.5, step=0.1)
        with c_p4:
            poll_delay = st.number_input("指令间隔延迟(秒)", min_value=0.0, value=0.05, step=0.05)

        st.divider()
        c_p5, c_p6, c_p7 = st.columns([1, 1.5, 1.5])
        with c_p5:
            poll_rounds = st.number_input("♻️ 测试轮数", min_value=1, value=1)
        with c_p6:
            len_mode = st.radio("读写长度模式", ["固定数量", "随机数量 (1~上限)"], horizontal=True)
        with c_p7:
            max_len = st.number_input("寄存器个数上限(最大120)", min_value=1, max_value=120, value=10)

        st.divider()
        st.subheader("📋 2. 网关轮询目标列表")
        if 'poll_task_count' not in st.session_state: st.session_state.poll_task_count = 1

        c_add, c_del, _ = st.columns([2, 2, 6])
        with c_add:
            if st.button("➕ 增加节点", use_container_width=True):
                st.session_state.poll_task_count += 1
                st.rerun()
        with c_del:
            if st.button("➖ 移除节点", use_container_width=True):
                if st.session_state.poll_task_count > 1:
                    st.session_state.poll_task_count -= 1
                    st.rerun()

        tasks_config = []
        for i in range(st.session_state.poll_task_count):
            with st.container(border=True):
                t1, t2, t3 = st.columns(3)
                with t1: slave = st.number_input(f"节点 {i + 1} 站号", min_value=1, max_value=247, value=i + 1,
                                                 key=f"ps_{i}")
                with t2: start_addr = st.number_input(f"起始地址", min_value=0, max_value=65535, value=0,
                                                      key=f"pstart_{i}")
                with t3: end_addr = st.number_input(f"结束地址", min_value=0, max_value=65535, value=100,
                                                    key=f"pend_{i}")
                tasks_config.append({"slave": slave, "start": start_addr, "end": end_addr})

        st.divider()
        if st.button("🚀 启动自动化轮询压测", type="primary", use_container_width=True):
            has_error = False
            for i, task in enumerate(tasks_config):
                if task['start'] > task['end']:
                    st.error(f"❌ 节点 {i + 1} 的起始地址不能大于结束地址！")
                    has_error = True;
                    break
            if not has_error:
                poll_state["is_running"] = True
                poll_state["completed"] = False
                poll_state["success_cnt"] = 0
                poll_state["fail_cnt"] = 0
                poll_state["error_logs"] = []

                is_random = (len_mode == "随机数量 (1~上限)")
                threading.Thread(
                    target=polling_worker,
                    args=(poll_port, poll_baud, tasks_config, poll_delay, poll_timeout, poll_rounds, is_random, max_len,
                          poll_state),
                    daemon=True
                ).start()
                st.rerun()