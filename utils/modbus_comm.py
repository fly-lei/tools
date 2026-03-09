import serial.tools.list_ports
import inspect
from pymodbus.client import ModbusSerialClient


def _get_slave_kwarg(func):
    sig = inspect.signature(func)
    for param_name in ['device_id', 'slave', 'unit']:
        if param_name in sig.parameters:
            return param_name
    return 'slave'


def get_available_ports():
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]


# 🌟 新增：支持动态 timeout 参数
def master_read(port, baudrate, slave_id, func_code, start_addr, count, timeout=1.0):
    # 将前端传来的 timeout 传递给串口客户端
    client = ModbusSerialClient(port=port, baudrate=baudrate, timeout=timeout)
    if not client.connect():
        return False, f"无法打开串口 {port}"

    try:
        kwarg_name = _get_slave_kwarg(client.read_holding_registers)
        kwargs = {kwarg_name: slave_id}

        if func_code == 3:
            result = client.read_holding_registers(address=start_addr, count=count, **kwargs)
        elif func_code == 4:
            result = client.read_input_registers(address=start_addr, count=count, **kwargs)
        else:
            return False, "不支持的读取功能码"

        if result.isError():
            return False, f"设备异常或响应超时: {result}"

        return True, result.registers

    except Exception as e:
        return False, f"通讯错误: {str(e)}"
    finally:
        client.close()


# 🌟 新增：支持动态 timeout 参数
def master_write_10(port, baudrate, slave_id, start_addr, values, timeout=1.0):
    client = ModbusSerialClient(port=port, baudrate=baudrate, timeout=timeout)
    if not client.connect():
        return False, f"无法打开串口 {port}"

    try:
        kwarg_name = _get_slave_kwarg(client.write_registers)
        kwargs = {kwarg_name: slave_id}

        result = client.write_registers(address=start_addr, values=values, **kwargs)
        if result.isError():
            return False, f"设备拒绝或响应超时: {result}"

        return True, "写入成功！"

    except Exception as e:
        return False, f"通讯错误: {str(e)}"
    finally:
        client.close()