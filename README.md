# 火车票发票识别与排列工具

## 功能
- 从邮箱获取12306发票PDF
- 支持日期范围筛选
- PDF内容去重
- 自动命名：出发站-到达站_开车时间.pdf
- 合并PDF按开车时间排序

## 部署

### 1. 配置邮箱
编辑 `config.py`：
```python
EMAIL_CONFIG = {
    'email_address': 'your_email@qq.com',
    'password': '授权码',
}
```

### 2. 启动
```bash
docker-compose up -d --build
```

### 3. 访问
`http://NAS_IP:5100`

## 日期筛选
在网页上选择开始日期和结束日期，只获取该时间段内的邮件。不选则搜索最近30天。

## 目录
- `发票/` - 下载的发票
- `output/` - 合并后的PDF