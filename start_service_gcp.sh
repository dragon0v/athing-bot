# 1. 重新加载系统管家的配置，让它发现我们的新文件
sudo systemctl daemon-reload

# 2. 设置开机自启（以后 GCP 重启，机器人会自动上线）
sudo systemctl enable discord-bot

# 3. 立即在后台启动机器人！
sudo systemctl start discord-bot

# 实时追踪日志（就像平时在终端看到的那样，按 Ctrl+C 退出追踪）
sudo journalctl -u discord-bot -f