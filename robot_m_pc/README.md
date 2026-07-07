# 岐黄智取：PC 端智能问诊与任务调度系统

## 模块简介

`robot_m_pc` 是“岐黄智取”系统的 PC 端模块，负责用户交互、智能问诊、药品方案生成、抓取任务规划以及与 ELFBoard 端通信。

## 主要功能

- Web 问诊界面
- 智能问诊与药品方案生成
- 结构化抓取任务规划
- 任务下发与状态展示
- 与 ELFBoard 端通信

## 运行环境

- Windows 10 / 11
- Python 3.10+
- FastAPI
- Uvicorn

完整依赖见 `requirements.txt`。

## 安装依赖

```bash
cd robot_m_pc
pip install -r requirements.txt
```

## 配置

复制配置示例：

```cmd
copy .env.example .env
```

然后根据实际环境修改 `.env`。

主要配置包括：

```env
DASHSCOPE_API_KEY=your_api_key_here
APP_HOST=127.0.0.1
APP_PORT=18080
ROBOT_BASE_URL=http://your_robot_ip:8000
```

请勿将真实密钥或本地 `.env` 文件提交到公开仓库。

## 启动

Python 启动：

```bash
python run.py
```

或双击：

```text
启动岐黄智取.cmd
```

默认访问地址：

```text
http://127.0.0.1:18080
```

## 工作流程

用户输入  
↓  
智能问诊与药品方案生成  
↓  
抓取任务规划  
↓  
任务发送至 ELFBoard  
↓  
视觉识别与目标定位  
↓  
机械臂执行抓取  
↓  
返回任务状态  

## 相关模块

- `../robot_m_elf/`：ELFBoard 视觉识别与机器人控制
- `../dummy-ref-core-fw/`：机械臂 STM32 固件

## 开源协议

MIT License
