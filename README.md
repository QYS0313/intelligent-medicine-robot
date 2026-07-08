# 云岐智药——远程问诊与机械臂智能配药系统

## 项目简介

“岐黄智取”是一套面向中医药智能服务场景的问诊与机器人抓药协作系统。

系统通过 PC 端 Web 界面接收用户输入，结合智能问诊与药品方案生成能力形成结构化抓取任务，并将任务发送至 ELFBoard 边缘计算平台。ELFBoard 负责药品视觉识别、目标定位与机械臂任务调度，最终由机械臂完成自动抓取。

本仓库包含 PC 端、ELFBoard 端以及机械臂固件三部分主体代码。

## 系统组成

### 1. PC 端

目录：`robot_m_pc/`

主要功能：

- 本地 Web 问诊界面
- 智能问诊与药品方案生成
- 药品任务规划
- 抓取任务下发
- 机器人状态展示
- 与 ELFBoard 端通信

详细说明见 `robot_m_pc/README.md`。

### 2. ELFBoard 端

目录：`robot_m_elf/`

主要功能：

- RKNN 模型推理
- 药品视觉识别
- RealSense 相机采集
- 抓取任务处理
- 机械臂通信与控制
- HTTP 服务接口

### 3. 机械臂固件

目录：`dummy-ref-core-fw/`

主要功能：

- STM32 底层控制
- 机械臂运动控制
- 串口通信
- 执行上位机控制指令

## 系统工作流程

用户输入  
↓  
PC 端 Web 交互  
↓  
智能问诊与药品方案生成  
↓  
任务规划与抓取请求下发  
↓  
ELFBoard 接收任务  
↓  
相机采集与 RKNN 视觉识别  
↓  
目标定位  
↓  
机械臂执行抓取  
↓  
返回任务状态  

## 项目结构

- `robot_m_pc/`：PC 端问诊与任务调度系统
- `robot_m_elf/`：ELFBoard 视觉识别与机器人控制
- `dummy-ref-core-fw/`：机械臂 STM32 固件
- `README.md`：项目总说明
- `LICENSE`：开源协议

## 运行环境

### PC 端

- Windows
- Python 3.x
- FastAPI
- Web Browser
- 智能问诊与方案生成模块

具体依赖见 `robot_m_pc/requirements.txt`。

### ELFBoard 端

- Linux
- Python 3.x
- RKNN Runtime
- RealSense Camera
- Serial Communication

### 机械臂固件

- STM32
- C / C++
- STM32 HAL
- FreeRTOS

## 配置说明

PC 端使用本地环境变量保存运行参数与必要的服务配置。

请复制：

`robot_m_pc/.env.example`

并创建本地：

`robot_m_pc/.env`

然后根据实际运行环境填写配置。

请勿将真实密钥、Token、密码或其他敏感凭据提交到 Git 仓库。

## 快速开始

### PC 端

进入 PC 端目录：

`cd robot_m_pc`

安装依赖：

`pip install -r requirements.txt`

根据 `.env.example` 配置本地 `.env` 后启动程序。

更详细的运行方式见 `robot_m_pc/README.md`。

### ELFBoard 端

进入：

`cd robot_m_elf`

根据 ELFBoard 实际运行环境安装依赖并启动视觉识别与机器人控制服务。

### 机械臂固件

使用对应 STM32 开发环境打开 `dummy-ref-core-fw/`，完成编译并烧录至机械臂控制板。

## 模型文件

项目包含用于药品视觉识别的 RKNN 模型文件，相关模型位于对应 `models/` 目录中。

## 安全说明

本仓库不包含真实密钥、Access Token、密码或私钥。

敏感配置仅保存在本地 `.env` 文件中。

## 开源协议

本项目采用 MIT License 开源，详见 `LICENSE`。
