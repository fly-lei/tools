import time
from datetime import datetime
from utils import modbus_comm


def run_ota_upgrade(com_port, baudrate, slave_id, bin_data, offset, task_state, timeout_sec=1.0, packet_delay=0.0):
    """
    纯后台执行引擎，不依赖任何 UI 控件。
    状态通过 task_state 字典与前端跨线程共享。
    包含极度详尽的 TX/RX Modbus 报文级日志打印。
    """
    # 初始化状态
    task_state["logs"].clear()
    task_state["progress"] = 0.0
    task_state["progress_text"] = "准备就绪..."
    task_state["is_running"] = True
    task_state["result"] = None

    log_history = task_state["logs"]

    def record_log(msg, status="info", is_txrx=False):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        prefix = "通信" if is_txrx else "系统"
        log_entry = f"[{ts}] [{prefix}] {msg}"
        log_history.append(log_entry)

        # 将最新的状态文字暴露给前端
        if not is_txrx:
            task_state["current_msg"] = msg
            task_state["msg_status"] = status

    def to_hex_list(data_list):
        """安全地将列表转换为漂亮的 Hex 字符串"""
        if not isinstance(data_list, list):
            return str(data_list)
        return "[" + ", ".join([f"0x{v:04X}" for v in data_list]) + "]"

    try:
        record_log("=" * 50)
        record_log(f"OTA 后台任务启动 - 串口:{com_port}, 站号:{slave_id}")
        record_log("=" * 50)

        size_addr = offset + 8
        if size_addr + 4 > len(bin_data):
            record_log("❌ 上传的文件太小，无法读取固件大小！", "error")
            task_state["is_running"] = False
            task_state["result"] = False
            return

        ota_size = (bin_data[size_addr] | (bin_data[size_addr + 1] << 8) |
                    (bin_data[size_addr + 2] << 16) | (bin_data[size_addr + 3] << 24))

        record_log(f"ℹ️ [文件解析] 解析到固件内部声明的逻辑大小: {ota_size} 字节")

        chunk_size = 240
        actual_chunks = (ota_size + chunk_size - 1) // chunk_size
        total_chunks = actual_chunks + 1

        total_read_bytes = total_chunks * chunk_size
        transfer_file = bin_data[offset: offset + total_read_bytes]

        if len(transfer_file) < 128:
            record_log("❌ 固件长度不足 128 字节！", "error")
            task_state["is_running"] = False
            task_state["result"] = False
            return

        word1 = (transfer_file[2] << 8) | transfer_file[3]
        word2 = (transfer_file[4] << 8) | transfer_file[5]

        # ==========================================
        # 步骤 1: 写入文件头部特征字
        # ==========================================
        record_log(f"▶️ [里程碑] 写入文件头部特征字到 50006, 50007...")
        data_step1 = [word1, word2]
        record_log(f"TX -> [0x10 写多寄存器] 地址:50006, 数量:2, 数据:{to_hex_list(data_step1)}", is_txrx=True)
        s, r = modbus_comm.master_write_10(com_port, baudrate, slave_id, 50006, data_step1, timeout=timeout_sec)
        if s:
            record_log(f"RX <- [0x10 响应] 写入成功: {r}", is_txrx=True)
        else:
            record_log(f"RX <- [0x10 报错] 写入失败: {r}", "error", is_txrx=True)
            task_state["is_running"] = False
            task_state["result"] = False
            return
        time.sleep(1)

        # ==========================================
        # 步骤 2: 下发 0xA1 升级请求
        # ==========================================
        record_log("▶️ [里程碑] 往下发 50004 写入升级请求指令 0xA1...")
        data_step2 = [0x00A1]
        record_log(f"TX -> [0x10 写多寄存器] 地址:50004, 数量:1, 数据:{to_hex_list(data_step2)}", is_txrx=True)
        s, r = modbus_comm.master_write_10(com_port, baudrate, slave_id, 50004, data_step2, timeout=timeout_sec)
        if s:
            record_log(f"RX <- [0x10 响应] 写入成功: {r}", is_txrx=True)
        else:
            record_log(f"RX <- [0x10 报错] 写入失败: {r}", "error", is_txrx=True)
            task_state["is_running"] = False
            task_state["result"] = False
            return
        time.sleep(1)

        # ==========================================
        # 步骤 3: 读取 50004 检查机组状态
        # ==========================================
        record_log("▶️ [里程碑] 读取 50004 检查机组状态...")
        record_log(f"TX -> [0x03 读保持寄存器] 地址:50004, 数量:1", is_txrx=True)
        s, r = modbus_comm.master_read(com_port, baudrate, slave_id, 3, 50004, 1, timeout=timeout_sec)
        if s:
            record_log(f"RX <- [0x03 响应] 读取成功: {to_hex_list(r)}", is_txrx=True)
        else:
            record_log(f"RX <- [0x03 报错] 读取失败: {r}", "error", is_txrx=True)
            task_state["is_running"] = False
            task_state["result"] = False
            return

        status_code = r[0]
        start_chunk, current_uid = 0, 0

        if status_code == 0x00A2:
            record_log("✅ 机组允许【全新升级】！")
        elif status_code == 0x00B1:
            record_log("⚠️ 机组请求【断点续传】！正在获取上次断点...")
            # ==========================================
            # 步骤 4 (可选): 断点续传读取 UID
            # ==========================================
            record_log(f"TX -> [0x03 读保持寄存器] 地址:50010, 数量:1", is_txrx=True)
            s_uid, r_uid = modbus_comm.master_read(com_port, baudrate, slave_id, 3, 50010, 1, timeout=timeout_sec)
            if s_uid:
                record_log(f"RX <- [0x03 响应] 读取成功断点 UID: {to_hex_list(r_uid)}", is_txrx=True)
            else:
                record_log(f"RX <- [0x03 报错] 读取断点失败: {r_uid}", "error", is_txrx=True)
                task_state["is_running"] = False
                task_state["result"] = False
                return

            current_uid = (r_uid[0] + 1) & 0xFFFF
            start_chunk = current_uid
            record_log(f"⏭️ 将跳过前 {start_chunk} 包，从第 {start_chunk + 1} 包开始续传！", "success")
        else:
            record_log(f"❌ 状态异常！50004 返回值: 0x{status_code:02X}", "error")
            task_state["is_running"] = False
            task_state["result"] = False
            return

        if start_chunk > total_chunks:
            record_log(f"❌ 断点超过总包数！", "error")
            task_state["is_running"] = False
            task_state["result"] = False
            return

        if start_chunk == total_chunks:
            record_log("✅ 固件已完整存在，直接结束...", "success")
        else:
            record_log(f"▶️ 开始发包！总计需发 {total_chunks} 包...")

        # ==========================================
        # 步骤 5: 循环发包逻辑
        # ==========================================
        for i in range(start_chunk, total_chunks):
            chunk = transfer_file[i * chunk_size: (i + 1) * chunk_size]
            if len(chunk) < chunk_size:
                chunk += b'\x00' * (chunk_size - len(chunk))

            words = [current_uid]
            for j in range(0, chunk_size, 2):
                words.append((chunk[j] << 8) | chunk[j + 1])

            retry, success_chunk = 0, False

            if i == total_chunks - 1:
                record_log(f"🧹 正在发送第 {i + 1}/{total_chunks} 包 (物理尾部附加包, UID:{current_uid})...", "warning")
            else:
                record_log(f"📤 正在发送第 {i + 1}/{total_chunks} 包 (UID:{current_uid})...", "info")

            while retry < 3:
                # 记录详细的数据包下发 TX
                record_log(
                    f"TX -> [0x10 写固件包] 地址:50100, 重试:{retry}, 数量:{len(words)}, 数据:{to_hex_list(words)}",
                    is_txrx=True)
                s_w, r_w = modbus_comm.master_write_10(com_port, baudrate, slave_id, 50100, words, timeout=timeout_sec)

                if s_w:
                    record_log(f"RX <- [0x10 响应] 写入固件包成功: {r_w}", is_txrx=True)

                    # 立刻查 UID
                    record_log(f"TX -> [0x03 读UID校验] 地址:50010, 数量:1", is_txrx=True)
                    s_r, r_r = modbus_comm.master_read(com_port, baudrate, slave_id, 3, 50010, 1, timeout=timeout_sec)
                    if s_r:
                        record_log(f"RX <- [0x03 响应] 读回设备当前UID: {to_hex_list(r_r)}", is_txrx=True)
                        expected_uid = (current_uid + 0) & 0xFFFF
                        if r_r[0] == expected_uid:
                            current_uid = r_r[0] + 1
                            success_chunk = True
                            if packet_delay > 0 and i < total_chunks - 1:
                                time.sleep(packet_delay)
                            break
                        else:
                            record_log(
                                f"⚠️ UID未更新或错乱(期望:0x{expected_uid:04X}, 实际:0x{r_r[0]:04X})，准备重试...",
                                "warning")
                    else:
                        record_log(f"RX <- [0x03 报错] 读取50010失败: {r_r}", "error", is_txrx=True)
                else:
                    record_log(f"RX <- [0x10 报错] 写入固件包失败: {r_w}", "error", is_txrx=True)

                retry += 1
                time.sleep(0.5)

            if not success_chunk:
                record_log(f"❌ 第 {i + 1} 包连续 3 次失败，被迫终止！", "error")
                task_state["is_running"] = False
                task_state["result"] = False
                return

            task_state["progress"] = (i + 1) / total_chunks
            task_state["progress_text"] = f"固件进度: {int((i + 1) / total_chunks * 100)}% (当前UID:{current_uid})"

        # ==========================================
        # 步骤 6: 传包完成，写 0xC1
        # ==========================================
        record_log("▶️ [里程碑] 传包完成！写 0xC1...")
        data_step6 = [0x00C1]
        record_log(f"TX -> [0x10 写多寄存器] 地址:50008, 数量:1, 数据:{to_hex_list(data_step6)}", is_txrx=True)
        s, r = modbus_comm.master_write_10(com_port, baudrate, slave_id, 50008, data_step6, timeout=timeout_sec)
        if s:
            record_log(f"RX <- [0x10 响应] 写入成功: {r}", is_txrx=True)
        else:
            record_log(f"RX <- [0x10 报错] 写入失败: {r}", "error", is_txrx=True)
            task_state["is_running"] = False
            task_state["result"] = False
            return

        # ==========================================
        # 步骤 7: 读取 50008 检查状态
        # ==========================================
        record_log("▶️ [里程碑] 读取 50008 检查机组状态...")
        record_log(f"TX -> [0x03 读保持寄存器] 地址:50008, 数量:1", is_txrx=True)
        s, r = modbus_comm.master_read(com_port, baudrate, slave_id, 3, 50008, 1, timeout=timeout_sec)
        if s:
            record_log(f"RX <- [0x03 响应] 读取成功: {to_hex_list(r)}", is_txrx=True)
        else:
            record_log(f"RX <- [0x03 报错] 读取失败: {r}", "error", is_txrx=True)

        # 烧录等待期
        record_log("⏳ 进入烧录阶段，等待 1 分钟...")
        for w in range(60):
            time.sleep(1)
            task_state["progress_text"] = f"固件烧录中... 剩余 {60 - w - 1} 秒"
            task_state["progress"] = (w + 1) / 60

        # ==========================================
        # 步骤 8: 最终完整性校验
        # ==========================================
        record_log("▶️ [里程碑] 最终完整性校验...")
        record_log(f"TX -> [0x03 读保持寄存器] 地址:50011, 数量:1", is_txrx=True)
        s, r = modbus_comm.master_read(com_port, baudrate, slave_id, 3, 50011, 1, timeout=timeout_sec)
        if s:
            record_log(f"RX <- [0x03 响应] 最终校验读取成功: {to_hex_list(r)}", is_txrx=True)
        else:
            record_log(f"RX <- [0x03 报错] 最终校验读取失败: {r}", "error", is_txrx=True)
            task_state["is_running"] = False
            task_state["result"] = False
            return

        target_word = (transfer_file[127] << 8) | transfer_file[126]
        if r[0] == target_word:
            record_log(f"🎉 升级圆满成功！校验码:0x{r[0]:04X}", "success")
            task_state["is_running"] = False
            task_state["result"] = True
        else:
            record_log(f"❌ 失败！校验码不匹配 (返回:0x{r[0]:04X} 期望:0x{target_word:04X})", "error")
            task_state["is_running"] = False
            task_state["result"] = False

    except Exception as e:
        record_log(f"❌ 异常: {str(e)}", "error")
        task_state["is_running"] = False
        task_state["result"] = False