import pandas as pd
import re
import io


def check_crc(hex_string):
    """严格校验 Modbus RTU 的 CRC16"""
    if len(hex_string) < 4: return False
    data = hex_string[:-4]
    expected_crc = hex_string[-4:]
    crc = 0xFFFF
    try:
        for i in range(0, len(data), 2):
            crc ^= int(data[i:i + 2], 16)
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        calculated_crc = f"{crc & 0xFF:02x}{(crc >> 8) & 0xFF:02x}"
        return calculated_crc.lower() == expected_crc.lower()
    except ValueError:
        return False


def to_signed_16(val):
    """将无符号的 16 位整数转换为有符号（负数）"""
    if isinstance(val, int) and val > 32767:
        return val - 65536
    return val


def parse_modbus_data(file_lines, target_address, slave_id, scan_writes_only):
    """
    核心解析引擎：接收文本行和参数，返回解析后的字典列表。
    """
    # 强制站号和地址按纯净的无符号处理，防止溢出污染
    slave_hex = f"{slave_id & 0xFF:02x}".lower()
    target_address = target_address & 0xFFFF

    parsed_data = []
    pending_03 = []
    pending_06 = {}
    pending_10 = {}

    for line_num, line in enumerate(file_lines, 1):
        line = line.strip()
        if not line: continue

        # 智能正则清洗
        ts_match = re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+', line)
        if ts_match:
            timestamp = ts_match.group(0)
            raw_data = line[ts_match.end():]
        else:
            seq_match = re.search(r'(Tx|Rx):\d+-', line, re.IGNORECASE)
            if seq_match:
                timestamp = seq_match.group(0).strip('-')
                raw_data = line[seq_match.end():]
            else:
                timestamp = f"Line_{line_num}"
                raw_data = line

        hex_data = raw_data.replace(" ", "").lower()
        if not hex_data: continue

        search_idx = 0
        while search_idx < len(hex_data):
            idx = hex_data.find(slave_hex, search_idx)
            if idx == -1: break
            if idx + 4 > len(hex_data):
                search_idx = idx + 1
                continue

            func_code = hex_data[idx + 2:idx + 4]
            matched = False

            # 0x03
            if func_code == "03" and not scan_writes_only:
                if idx + 16 <= len(hex_data):
                    req_frame = hex_data[idx:idx + 16]
                    if check_crc(req_frame):
                        start_addr = int(req_frame[4:8], 16)
                        reg_count = int(req_frame[8:12], 16)
                        if start_addr <= target_address < start_addr + reg_count:
                            pending_03.append({
                                "timestamp": timestamp, "line_num": line_num,
                                "req_frame": req_frame, "start_addr": start_addr, "reg_count": reg_count
                            })
                        search_idx = idx + 16
                        matched = True
                        continue

                if idx + 6 <= len(hex_data):
                    try:
                        byte_count = int(hex_data[idx + 4:idx + 6], 16)
                        resp_len = 6 + byte_count * 2 + 4
                        if idx + resp_len <= len(hex_data):
                            resp_frame = hex_data[idx:idx + resp_len]
                            if check_crc(resp_frame):
                                for i, req in enumerate(pending_03):
                                    if req["reg_count"] * 2 == byte_count:
                                        data_hex = hex_data[idx + 6: idx + 6 + (byte_count * 2)]
                                        offset = target_address - req["start_addr"]
                                        target_val_hex = data_hex[offset * 4: (offset + 1) * 4]

                                        val_un = int(target_val_hex, 16)
                                        parsed_data.append({
                                            "标识/时间": req["timestamp"], "请求行号": req["line_num"],
                                            "响应行号": line_num,
                                            "操作类型": "读取 (0x03)", "目标地址": f"0x{target_address:04x}",
                                            "数据 (16进制)": f"0x{target_val_hex}",
                                            "数据 (无符号10进制)": val_un,
                                            "数据 (有符号10进制)": to_signed_16(val_un),
                                            "请求报文": req["req_frame"], "响应报文": resp_frame
                                        })
                                        pending_03.pop(i)
                                        break
                                search_idx = idx + resp_len
                                matched = True
                                continue
                    except ValueError:
                        pass

            # 0x06
            elif func_code == "06":
                if idx + 16 <= len(hex_data):
                    frame = hex_data[idx:idx + 16]
                    if check_crc(frame):
                        start_addr = int(frame[4:8], 16)
                        if scan_writes_only or start_addr == target_address:
                            data_hex = frame[8:12]
                            val_un = int(data_hex, 16)
                            fingerprint = frame
                            if fingerprint not in pending_06:
                                pending_06[fingerprint] = {
                                    "标识/时间": timestamp, "请求行号": line_num,
                                    "操作类型": "单写 (0x06)", "目标地址": f"0x{start_addr:04x}",
                                    "数据 (16进制)": f"0x{data_hex}",
                                    "数据 (无符号10进制)": val_un,
                                    "数据 (有符号10进制)": to_signed_16(val_un),
                                    "请求报文": frame,
                                }
                            else:
                                record = pending_06.pop(fingerprint)
                                record["响应行号"] = line_num
                                record["响应报文"] = frame
                                parsed_data.append(record)
                        search_idx = idx + 16
                        matched = True
                        continue

            # 0x10
            elif func_code == "10":
                if idx + 14 <= len(hex_data):
                    try:
                        byte_count = int(hex_data[idx + 12:idx + 14], 16)
                        req_len = 14 + byte_count * 2 + 4
                        if idx + req_len <= len(hex_data):
                            req_frame = hex_data[idx:idx + req_len]
                            if check_crc(req_frame):
                                start_addr = int(req_frame[4:8], 16)
                                reg_count = int(req_frame[8:12], 16)
                                if scan_writes_only or (start_addr <= target_address < start_addr + reg_count):
                                    data_hex = hex_data[idx + 14: idx + 14 + (byte_count * 2)]
                                    if scan_writes_only:
                                        target_val_hex = data_hex
                                        display_addr = f"0x{start_addr:04x}"
                                        val_un = "N/A"
                                    else:
                                        offset = target_address - start_addr
                                        target_val_hex = data_hex[offset * 4: (offset + 1) * 4]
                                        display_addr = f"0x{target_address:04x}"
                                        val_un = int(target_val_hex, 16)

                                    fingerprint = req_frame[4:12]
                                    pending_10[fingerprint] = {
                                        "标识/时间": timestamp, "请求行号": line_num,
                                        "操作类型": "多写 (0x10)", "目标地址": display_addr,
                                        "数据 (16进制)": f"0x{target_val_hex}",
                                        "数据 (无符号10进制)": val_un,
                                        "数据 (有符号10进制)": to_signed_16(val_un) if val_un != "N/A" else "N/A",
                                        "请求报文": req_frame,
                                    }
                                search_idx = idx + req_len
                                matched = True
                                continue
                    except ValueError:
                        pass

                if idx + 16 <= len(hex_data):
                    resp_frame = hex_data[idx:idx + 16]
                    if check_crc(resp_frame):
                        fingerprint = resp_frame[4:12]
                        if fingerprint in pending_10:
                            record = pending_10.pop(fingerprint)
                            record["响应行号"] = line_num
                            record["响应报文"] = resp_frame
                            parsed_data.append(record)
                        search_idx = idx + 16
                        matched = True
                        continue

            if not matched:
                search_idx = idx + 1

    return parsed_data


def generate_excel_bytes(parsed_data):
    """
    将解析后的字典列表转换为 Excel 字节流，供前端下载使用。
    """
    parsed_data.sort(key=lambda x: x["请求行号"])
    columns_order = [
        "标识/时间", "请求行号", "响应行号", "操作类型", "目标地址",
        "数据 (16进制)", "数据 (无符号10进制)", "数据 (有符号10进制)", "请求报文", "响应报文"
    ]
    df = pd.DataFrame(parsed_data)[columns_order]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='解析结果')
    return output.getvalue(), df