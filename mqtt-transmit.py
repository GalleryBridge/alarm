import numpy as np
import json
import base64
import time
import cv2
from ultralytics import YOLO
import paho.mqtt.client as mqtt

# 配置 MQTT 服务器信息
MQTT_BROKER = "web.samheos.com"  # 替换为 MQTT 服务器地址
MQTT_PORT = 1884  # 替换为实际端口号
MQTT_TOPIC = "test/image"  # 替换为实际订阅的主题
MQTT_USERNAME = None  # 替换为用户名（如需要）
MQTT_PASSWORD = None  # 替换为密码（如需要）

# 加载YOLOv8模型
model_path = "best.pt"
try:
    model = YOLO(model_path)
except Exception as e:
    model = None

def encode_image_to_base64(image, file_format='jpg'):
    """
    将图像编码为Base64格式。
    image: OpenCV读取的图像
    file_format: 图像的格式，默认为'jpg'，支持'jpg'和'png'
    """
    if file_format == 'png':
        _, buffer = cv2.imencode('.png', image)
    else:  # 默认为jpg
        _, buffer = cv2.imencode('.jpg', image)

    return base64.b64encode(buffer).decode('utf-8')


def detect_and_replace_base64(image, json_data, original_key):
    """
    检测图片中的目标，并替换原始 JSON 中的 Base64 编码值。
    当检测目标为空时返回 None。
    """
    if model is None:
        return None  # 模型未加载时返回 None

    # YOLOv8目标检测
    results = model(image)
    if not results or len(results[0].boxes.data) == 0:
        return None  # 如果没有检测到目标，返回 None

    # 从检测结果中提取目标信息
    detections = [d for d in results[0].boxes.data.tolist() if d[4] >= 0.5]  # 筛选高置信度目标
    if not detections:
        return None  # 如果没有高置信度目标，返回 None

    # 用于保存替换后的键值对
    updated_data = {}
    detected_types = set()

    for detection in detections:
        x1, y1, x2, y2, _, class_id = map(int, detection[:6])
        label = model.names[class_id]

        # 截取检测到的目标区域
        cropped_image = image[y1:y2, x1:x2]

        # 将截取的目标区域保存为 Base64 编码
        base64_cropped = encode_image_to_base64(cropped_image)

        # 将 Base64 编码添加到原始 JSON 中
        key_with_label = f"{original_key}-{label}"
        updated_data[key_with_label] = base64_cropped

        # 添加到检测到的类型中（去重）
        detected_types.add(label)

    # 删除原始图像的键值对
    json_data.pop(original_key, None)

    # 设置 'type' 键
    if detected_types:
        if "fire" in detected_types and "smoke" in detected_types:
            json_data['type'] = "fire,smoke"
        elif "fire" in detected_types:
            json_data['type'] = "fire"
        elif "smoke" in detected_types:
            json_data['type'] = "smoke"

    # 将新的键值对合并到原始 JSON 数据中
    json_data.update(updated_data)

    # 直接复制 "message" 键的值到更新后的 JSON 中
    if "message" in json_data:
        json_data["message"] = json_data["message"]

    return json_data


def on_message(client, userdata, msg):
    print(f"{msg.payload.decode('utf-8')}")
    try:
        # 尝试将数据解析为 JSON 格式
        json_data = json.loads(msg.payload.decode('utf-8'))
        print(f"Received JSON: {json_data}")
    except json.JSONDecodeError:
        print("Failed to parse JSON.")
        return

    # 提取 Sn, time, message 和 image 键
    sn = json_data.get("Sn")
    time_str = json_data.get("time")
    message = json_data.get("message")
    image_base64 = json_data.get("image")

    # 如果没有 "image" 键，返回
    if image_base64 is None:
        print("No image data found in the message.")
        return

    try:
        # 修正 Base64 填充问题
        padding = len(image_base64) % 4
        if padding != 0:
            image_base64 += '=' * (4 - padding)

        # 解码 Base64 数据
        image_data = base64.b64decode(image_base64)
        image = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)

        if image is None:
            print(f"Failed to decode image for Sn: {sn}")
            return

        # 调用目标检测和替换函数
        processed_data = detect_and_replace_base64(image, json_data, original_key="image")
        if processed_data is None:
            print(f"No detections for Sn: {sn}")
            return

        # 发送处理后的 JSON 数据
        client.publish(MQTT_TOPIC, json.dumps(processed_data))
        print("Processed data sent back.")
    except Exception as e:
        print(f"Error processing image for Sn {sn}: {e}")


def on_connect(client, userdata, flags, rc):
    """客户端连接时触发"""
    if rc == 0:
        client.subscribe(MQTT_TOPIC)  # 连接成功后自动订阅主题


def on_disconnect(client, userdata, rc):
    """断开连接时触发"""
    if rc != 0:
        pass


# 创建 MQTT 客户端
def main():
    client = mqtt.Client()

    # 如果需要身份认证，设置用户名和密码
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    # 绑定回调函数
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # 设置心跳间隔为60秒
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
