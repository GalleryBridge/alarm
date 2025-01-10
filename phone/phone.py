import numpy as np
import paho.mqtt.client as mqtt
import cv2
import json
import base64
import time
import websocket
from ultralytics import YOLO

# 配置 MQTT 服务器信息
MQTT_BROKER = "web.samheos.com"  # 替换为 MQTT 服务器地址
MQTT_PORT = 1884  # 替换为实际端口号
MQTT_TOPIC = "alarm/fire"  # 替换为实际订阅的主题
MQTT_USERNAME = None  # 替换为用户名（如需要）
MQTT_PASSWORD = None  # 替换为密码（如需要）

ws_url = "ws://192.168.110.66:8888/websocket/playPhone/fire_alarm"
test_ws_url = "ws://110.42.214.129:8888/websocket/playPhone/fire_alarm"  # WebSocket URL

# 加载YOLOv8模型
model1_path = "./phone1.pt"
model2_path = "./phone2.pt"

try:
    model1 = YOLO(model1_path)
    model2 = YOLO(model2_path)
except Exception as e:
    model1, model2 = None, None


def encode_image_to_base64(image, file_format='jpg'):
    """将图像编码为Base64格式。
    image: OpenCV读取的图像
    file_format: 图像的格式，默认为'jpg'，支持'jpg'和'png'
    """
    if file_format == 'png':
        _, buffer = cv2.imencode('.png', image)
    else:  # 默认为jpg
        _, buffer = cv2.imencode('.jpg', image)

    return base64.b64encode(buffer).decode('utf-8')


def detect_and_replace_base64(image, json_data, original_key):
    """检测图片中的目标，并返回带有检测框的原图。
    当检测目标为空时返回 None。
    """
    if model1 is None or model2 is None:
        return None  # 模型未加载时返回

    # 模型推理
    results1 = model1(image)[0].boxes.data.cpu().numpy()
    results2 = model2(image)[0].boxes.data.cpu().numpy()

    # 转换为 [x1, y1, x2, y2, confidence, class_name] 格式
    results1 = [[*box[:4], box[4], model1.names[int(box[5])]] for box in results1]
    results2 = [[*box[:4], box[4], model2.names[int(box[5])]] for box in results2]

    # 合并检测结果并根据信心度排序
    final_results = results1 + results2
    final_results = sorted(final_results, key=lambda x: x[4], reverse=True)  # 根据信心度从高到低排序

    # 筛选出置信度不低于 0.8 的目标
    confidence_threshold = 0.7
    final_results = [result for result in final_results if result[4] >= confidence_threshold]

    if not final_results:
        return None

    updated_data = {}
    detected_types = set()

    # 获取目标截图
    for result in final_results:
        x1, y1, x2, y2, _, label = result
        detected_types.add(label)

        # 裁剪出目标区域
        target_image = image[int(y1):int(y2), int(x1):int(x2)]

        # 将目标图像转换为Base64
        base64_target = encode_image_to_base64(target_image)
        updated_data[original_key] = base64_target

    # 更新 JSON 数据，替换原始的 Base64 图像为带框的图像
    base64_image_with_boxes = encode_image_to_base64(image)
    updated_data[original_key] = base64_image_with_boxes

    json_data.pop(original_key, None)

    if detected_types:
        json_data['type'] = ",".join(detected_types)

    json_data.update(updated_data)
    return json_data

# 记录已处理的时间和目标
processed_detections = {}

# MQTT 监听功能
def on_message(client, userdata, msg):
    try:
        json_data = json.loads(msg.payload.decode('utf-8'))
    except json.JSONDecodeError:
        print("JSON解析失败.")
        return

    sn = json_data.get("sn")
    time_str = json_data.get("time")
    image_base64 = json_data.get("image")

    if image_base64 is None:
        print("找不到图片.")
        return

    try:
        padding = len(image_base64) % 4
        if padding != 0:
            image_base64 += '=' * (4 - padding)

        image_data = base64.b64decode(image_base64)
        image = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)

        if image is None:
            print(f"图片识别错误 Sn: {sn}")
            return

        # 调用目标检测和替换函数
        processed_data = detect_and_replace_base64(image, json_data, original_key="image")
        if processed_data is None:
            print(f"未检测到目标 Sn: {sn}")
            return

        # 检查是否重复发送
        detected_type = processed_data.get("type")
        current_time = time.time()

        if detected_type in processed_detections:
            last_time = processed_detections[detected_type]
            if current_time - last_time < 60:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: Detection of type '{detected_type}' occurred within 1 minute. Skipping...")
                return

        # 更新检测时间
        processed_detections[detected_type] = current_time

        client.publish(MQTT_TOPIC, json.dumps(processed_data))
        send_to_websocket(processed_data)
        print("发送成功.")


    except Exception as e:
        print(f"检测图像失败 for Sn {sn}: {e}")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_TOPIC)

def on_disconnect(client, userdata, rc):
    if rc != 0:
        pass

# WebSocket 连接和发送消息
def send_to_websocket(message):
    if isinstance(message, dict):
        # 如果是字典，先转为 JSON 字符串
        message = json.dumps(message)
    elif isinstance(message, bytes):
        # 如果是字节数据，直接发送
        pass
    elif isinstance(message, str):
        # 如果是字符串，直接发送
        pass
    else:
        # 如果 message 不是字典、字符串或字节数据，打印警告
        print(f"Warning: 不支持的消息类型: {type(message)}")
        return

    try:
        # 连接到 WebSocket 服务器
        ws = websocket.create_connection(ws_url)
        # 发送消息
        ws.send(message)
        print(f"发送成功: {message}")
        # 关闭 WebSocket 连接
        ws.close()
    except Exception as e:
        print(f"连接WebSocket失败: {e}")

def main():
    client = mqtt.Client()

    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    client.keepalive = 60

    # 连接到 MQTT 服务器
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception:
        return

    # 开启循环监听
    client.loop_start()

    try:
        # 程序将持续运行，等待接收消息
        while True:
            time.sleep(1)  # 等待接收消息
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()  # 停止网络循环
        client.disconnect()  # 断开连接


if __name__ == "__main__":
    main()
