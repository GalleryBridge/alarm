# 使用官方的Python基础镜像
FROM python:3.8-slim

# 设置工作目录
WORKDIR /app

# 将当前目录下的所有文件复制到工作目录
COPY . /app

# 安装依赖
RUN pip install ultralytics

pip install numpy

pip install cv2

pip install paho-mqtt

# 暴露端口
EXPOSE 80

# 定义环境变量
ENV NAME World

# 运行命令
CMD ["python", "app.py"]
