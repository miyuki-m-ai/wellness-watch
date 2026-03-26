chmod +x /home/site/wwwroot/ffmpeg /home/site/wwwroot/ffprobe
gunicorn --bind=0.0.0.0:8000 --timeout 600 line_bot:app & python /home/site/wwwroot/scheduler.py