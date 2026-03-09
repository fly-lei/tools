def calculate_crc16(hex_string):
    """
    计算 Modbus RTU 的 CRC16 校验码
    输入: 包含十六进制字符的字符串 (可带空格)
    输出: 格式化后的 CRC16 字符串 (例如 "C5 CD") 和 完整拼接报文
    """
    # 清洗输入：转大写，去空格
    clean_hex = hex_string.replace(" ", "").upper()

    # 验证输入是否为空或包含非十六进制字符
    if not clean_hex:
        raise ValueError("输入不能为空。")
    if len(clean_hex) % 2 != 0:
        raise ValueError("输入无效：请输入偶数个十六进制字符（完整字节）。")

    try:
        # 测试是否全为有效的十六进制
        int(clean_hex, 16)
    except ValueError:
        raise ValueError("输入包含非十六进制字符（如字母 G-Z 或标点符号）！")

    # 开始计算 CRC
    crc = 0xFFFF
    for i in range(0, len(clean_hex), 2):
        crc ^= int(clean_hex[i:i + 2], 16)
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    # Modbus CRC 是低位在前，高位在后
    low_byte = crc & 0xFF
    high_byte = (crc >> 8) & 0xFF

    # 格式化输出为 "XX XX" 的形式
    crc_result = f"{low_byte:02X} {high_byte:02X}"

    # 顺便把用户的原始输入也规范化成 "XX XX XX" 的形式
    formatted_input = " ".join([clean_hex[i:i + 2] for i in range(0, len(clean_hex), 2)])
    full_frame = f"{formatted_input} {crc_result}"

    return crc_result, full_frame