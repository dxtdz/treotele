import requests
import threading
import time
import os
import random
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import logging

# Flask app
app = Flask(__name__)
CORS(app)

# Cấu hình logging
logging.basicConfig(level=logging.INFO)

# Biến toàn cục
treo_threads = {}
current_tokens = set()
stop_events = {}
tasks = {}  # Dictionary để lưu các task đang chạy
tasks_file = 'telegram_tasks.json'

# Tải tasks từ file nếu có
if os.path.exists(tasks_file):
    try:
        with open(tasks_file, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
            # Khởi tạo các biến từ tasks
            for task_id, task in tasks.items():
                if task.get('running', False):
                    current_tokens.update(task.get('tokens', []))
    except:
        pass

def save_tasks():
    """Lưu tasks vào file"""
    try:
        with open(tasks_file, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi lưu tasks: {e}")

def send_typing_action(token, chat_id):
    """Send typing action to simulate user typing"""
    try:
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        data = {"chat_id": chat_id, "action": "typing"}
        response = requests.post(url, data=data, timeout=5)
        return response.status_code == 200
    except:
        return False

def send_loop(task_id, tokens, chat_ids, caption, photo, delay, use_typing=False):
    """Vòng lặp gửi tin nhắn cho một task"""
    task_info = tasks.get(task_id)
    if not task_info:
        return
    
    stop_event = stop_events.get(task_id)
    if not stop_event:
        return
    
    while not stop_event.is_set():
        for chat_id in chat_ids:
            if stop_event.is_set():
                break
            
            # Luân phiên sử dụng các token
            for token in tokens:
                if stop_event.is_set():
                    break
                
                # Gửi typing action nếu bật
                if use_typing:
                    typing_duration = random.uniform(0.5, 1.5)
                    typing_start = time.time()
                    
                    while time.time() - typing_start < typing_duration and not stop_event.is_set():
                        if random.random() < 0.7:
                            send_typing_action(token, chat_id)
                        time.sleep(random.uniform(1, 2))
                
                try:
                    if photo and photo.startswith("http"):
                        url = f"https://api.telegram.org/bot{token}/sendPhoto"
                        data = {"chat_id": chat_id, "caption": caption, "photo": photo}
                        response = requests.post(url, data=data, timeout=5)
                    elif photo and os.path.exists(photo):
                        url = f"https://api.telegram.org/bot{token}/sendPhoto"
                        with open(photo, "rb") as f:
                            files = {"photo": f}
                            data = {"chat_id": chat_id, "caption": caption}
                            response = requests.post(url, data=data, files=files, timeout=5)
                    else:
                        url = f"https://api.telegram.org/bot{token}/sendMessage"
                        data = {"chat_id": chat_id, "text": caption}
                        response = requests.post(url, data=data, timeout=5)

                    if response.status_code == 200:
                        # Cập nhật số tin đã gửi
                        tasks[task_id]['sent_count'] = tasks[task_id].get('sent_count', 0) + 1
                        tasks[task_id]['last_sent'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_tasks()
                        print(f"[+] {token[:10]}... gửi OK tới {chat_id}")
                    elif response.status_code == 429:
                        retry = response.json().get("parameters", {}).get("retry_after", 5)
                        print(f"[!] Token {token[:10]} bị chặn 429! Đợi {retry}s...")
                        time.sleep(retry)
                    else:
                        print(f"[!] Token {token[:10]} lỗi: {response.status_code} - {response.text}")
                except Exception as e:
                    print(f"[!] Token {token[:10]} lỗi kết nối: {e}")
                
                time.sleep(0.1)  # Delay giữa các token
        
        time.sleep(delay)  # Delay giữa các vòng lặp

def check_token(token):
    """Kiểm tra token có hợp lệ không"""
    try:
        res = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=3)
        if res.status_code == 200 and res.json().get("ok", False):
            bot_info = res.json().get("result", {})
            return {
                'valid': True,
                'username': f"@{bot_info.get('username', 'N/A')}",
                'name': bot_info.get('first_name', 'N/A')
            }
        return {'valid': False}
    except:
        return {'valid': False}

def validate_tokens(token_list):
    """Validate nhiều tokens"""
    valid_tokens = []
    invalid_tokens = []
    
    for token in token_list:
        token = token.strip()
        if token:
            result = check_token(token)
            if result['valid']:
                valid_tokens.append({
                    'token': token,
                    'username': result['username'],
                    'name': result['name']
                })
            else:
                invalid_tokens.append(token)
    
    return valid_tokens, invalid_tokens

def start_task(task_data):
    """Bắt đầu một task mới"""
    task_id = task_data['id']
    
    # Kiểm tra và validate tokens
    token_list = [t.strip() for t in task_data['tokens'].split(',') if t.strip()]
    valid_tokens_info, invalid_tokens = validate_tokens(token_list)
    
    if not valid_tokens_info:
        return {'success': False, 'message': 'Không có token hợp lệ'}
    
    valid_tokens = [t['token'] for t in valid_tokens_info]
    
    # Tạo stop event cho task
    stop_event = threading.Event()
    stop_events[task_id] = stop_event
    
    # Lưu thông tin task
    tasks[task_id] = {
        'id': task_id,
        'name': task_data['name'],
        'tokens': valid_tokens,
        'tokens_info': valid_tokens_info,
        'invalid_tokens': invalid_tokens,
        'chat_ids': task_data['chat_ids'],
        'message': task_data['message'],
        'photo': task_data.get('photo', ''),
        'delay': float(task_data['delay']),
        'use_typing': task_data.get('use_typing', False),
        'running': True,
        'sent_count': 0,
        'last_sent': '',
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'started_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Bắt đầu thread
    t = threading.Thread(
        target=send_loop,
        args=(task_id, valid_tokens, task_data['chat_ids'], 
              task_data['message'], task_data.get('photo', ''), 
              float(task_data['delay']), task_data.get('use_typing', False)),
        daemon=True
    )
    t.start()
    
    treo_threads[task_id] = {
        'thread': t,
        'stop_event': stop_event,
        'start': datetime.now()
    }
    
    # Thêm tokens vào current_tokens
    current_tokens.update(valid_tokens)
    
    # Lưu tasks
    save_tasks()
    
    return {
        'success': True,
        'message': f'Đã bắt đầu task {task_data["name"]} với {len(valid_tokens)} token',
        'valid_tokens': len(valid_tokens),
        'invalid_tokens': len(invalid_tokens)
    }

def stop_task(task_id):
    """Dừng một task"""
    if task_id in stop_events:
        stop_events[task_id].set()
        time.sleep(0.5)
    
    if task_id in treo_threads:
        del treo_threads[task_id]
    
    if task_id in tasks:
        tasks[task_id]['running'] = False
        save_tasks()
    
    return True

def delete_task(task_id):
    """Xóa một task"""
    stop_task(task_id)
    
    if task_id in tasks:
        del tasks[task_id]
    
    if task_id in stop_events:
        del stop_events[task_id]
    
    save_tasks()
    return True

def get_stats():
    """Lấy thống kê"""
    total_tasks = len(tasks)
    running_tasks = sum(1 for t in tasks.values() if t.get('running', False))
    total_tokens = sum(len(t.get('tokens', [])) for t in tasks.values())
    total_sent = sum(t.get('sent_count', 0) for t in tasks.values())
    
    return {
        'total_tasks': total_tasks,
        'running_tasks': running_tasks,
        'total_tokens': total_tokens,
        'total_sent': total_sent
    }

# ====================== ROUTES FLASK ======================

@app.route('/')
def index():
    """Trang chủ"""
    return render_template('index.html')

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """API lấy danh sách tasks"""
    return jsonify({'tasks': tasks, 'stats': get_stats()})

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """API tạo task mới"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'})
        
        # Tạo ID cho task
        task_id = f"task_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Validate dữ liệu
        if not data.get('tokens'):
            return jsonify({'success': False, 'message': 'Vui lòng nhập tokens'})
        
        if not data.get('chat_ids'):
            return jsonify({'success': False, 'message': 'Vui lòng nhập chat IDs'})
        
        if not data.get('message'):
            return jsonify({'success': False, 'message': 'Vui lòng nhập nội dung tin nhắn'})
        
        # Chuyển chat_ids thành list
        chat_ids = [cid.strip() for cid in data['chat_ids'].split(',') if cid.strip()]
        
        # Thêm thông tin task
        task_data = {
            'id': task_id,
            'name': data.get('name', f'Task {len(tasks) + 1}'),
            'tokens': data['tokens'],
            'chat_ids': chat_ids,
            'message': data['message'],
            'photo': data.get('photo', ''),
            'delay': data.get('delay', 5),
            'use_typing': data.get('use_typing', False)
        }
        
        # Bắt đầu task
        result = start_task(task_data)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def api_stop_task(task_id):
    """API dừng task"""
    try:
        stop_task(task_id)
        return jsonify({'success': True, 'message': f'Đã dừng task {task_id}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

@app.route('/api/tasks/<task_id>/start', methods=['POST'])
def api_start_task(task_id):
    """API khởi động lại task"""
    try:
        if task_id in tasks:
            task = tasks[task_id]
            
            # Dừng nếu đang chạy
            if task_id in stop_events:
                stop_events[task_id].set()
                time.sleep(1)
            
            # Bắt đầu lại
            task_data = {
                'id': task_id,
                'name': task['name'],
                'tokens': ','.join(task['tokens']),
                'chat_ids': ','.join(task['chat_ids']),
                'message': task['message'],
                'photo': task.get('photo', ''),
                'delay': task['delay'],
                'use_typing': task.get('use_typing', False)
            }
            
            result = start_task(task_data)
            return jsonify(result)
        else:
            return jsonify({'success': False, 'message': 'Task không tồn tại'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    """API xóa task"""
    try:
        delete_task(task_id)
        return jsonify({'success': True, 'message': f'Đã xóa task {task_id}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

@app.route('/api/validate', methods=['POST'])
def validate_token():
    """API validate token"""
    try:
        data = request.json
        token = data.get('token', '').strip()
        
        if not token:
            return jsonify({'valid': False, 'message': 'Vui lòng nhập token'})
        
        result = check_token(token)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'valid': False, 'message': f'Lỗi: {str(e)}'})

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """API lấy thống kê"""
    return jsonify(get_stats())

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """API upload file nội dung"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'Không có file'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'Không có file'})
        
        if file and file.filename.endswith('.txt'):
            content = file.read().decode('utf-8')
            return jsonify({
                'success': True, 
                'content': content,
                'filename': file.filename
            })
        else:
            return jsonify({'success': False, 'message': 'Chỉ hỗ trợ file .txt'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

# Tạo thư mục templates nếu chưa có
if not os.path.exists('templates'):
    os.makedirs('templates')

# Tạo file HTML template
index_html = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔥 Telegram Multi-Token Spammer</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 20px;
            color: #e6e6e6;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 15px;
            border: 1px solid #00adb5;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            color: #00adb5;
            text-shadow: 0 0 10px rgba(0, 173, 181, 0.5);
        }
        
        .header p {
            font-size: 1.2em;
            opacity: 0.8;
        }
        
        .alert {
            padding: 15px;
            margin: 15px 0;
            border-radius: 10px;
            text-align: center;
            font-weight: 600;
            display: none;
        }
        
        .alert-success {
            background: rgba(46, 213, 115, 0.2);
            color: #2ed573;
            border: 1px solid #2ed573;
        }
        
        .alert-error {
            background: rgba(255, 71, 87, 0.2);
            color: #ff4757;
            border: 1px solid #ff4757;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 25px;
            border: 1px solid #393e46;
            backdrop-filter: blur(10px);
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #00adb5;
        }
        
        .form-control {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #393e46;
            border-radius: 8px;
            font-size: 16px;
            transition: all 0.3s;
            background: rgba(255, 255, 255, 0.1);
            color: #e6e6e6;
        }
        
        .form-control:focus {
            outline: none;
            border-color: #00adb5;
            box-shadow: 0 0 0 3px rgba(0, 173, 181, 0.1);
        }
        
        textarea.form-control {
            min-height: 120px;
            resize: vertical;
        }
        
        .file-upload {
            border: 3px dashed #00adb5;
            border-radius: 8px;
            padding: 30px 20px;
            text-align: center;
            transition: all 0.3s;
            background: rgba(0, 173, 181, 0.05);
            cursor: pointer;
        }
        
        .file-upload:hover {
            background: rgba(0, 173, 181, 0.1);
        }
        
        .file-icon {
            font-size: 2.5em;
            margin-bottom: 10px;
            color: #00adb5;
        }
        
        .btn {
            padding: 12px 20px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #00adb5, #0097a7);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 173, 181, 0.4);
        }
        
        .btn-success {
            background: linear-gradient(135deg, #2ed573, #1dd1a1);
            color: white;
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #ff4757, #ff3838);
            color: white;
        }
        
        .btn-warning {
            background: linear-gradient(135deg, #ff9f43, #ffaf40);
            color: white;
        }
        
        .task-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .task-card {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 20px;
            border-left: 5px solid #00adb5;
            border: 1px solid #393e46;
            transition: transform 0.3s;
            position: relative;
            overflow: hidden;
        }
        
        .task-card.running {
            border-left-color: #2ed573;
            background: rgba(46, 213, 115, 0.05);
        }
        
        .task-card.running::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #2ed573, #7bed9f);
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        
        .task-card.stopped {
            border-left-color: #ff4757;
            opacity: 0.8;
        }
        
        .task-card:hover {
            transform: translateY(-5px);
        }
        
        .task-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .task-title {
            font-weight: bold;
            color: #00adb5;
            font-size: 1.2em;
        }
        
        .task-status {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        
        .status-running {
            background: #2ed573;
            color: white;
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 50% { opacity: 1; }
            51%, 100% { opacity: 0.7; }
        }
        
        .status-stopped {
            background: #ff4757;
            color: white;
        }
        
        .task-info {
            margin-bottom: 15px;
        }
        
        .task-info p {
            margin-bottom: 5px;
            color: #aaa;
            font-size: 0.9em;
        }
        
        .task-info strong {
            color: #e6e6e6;
        }
        
        .task-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: rgba(0, 173, 181, 0.2);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            border: 1px solid #00adb5;
        }
        
        .stat-number {
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 5px;
            color: #00adb5;
        }
        
        .token-badge {
            display: inline-block;
            background: rgba(0, 173, 181, 0.2);
            padding: 2px 8px;
            border-radius: 4px;
            margin: 2px;
            font-size: 0.8em;
            border: 1px solid #00adb5;
        }
        
        .token-valid {
            background: rgba(46, 213, 115, 0.2);
            border-color: #2ed573;
        }
        
        .token-invalid {
            background: rgba(255, 71, 87, 0.2);
            border-color: #ff4757;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
        }
        
        .spinner {
            border: 4px solid rgba(0, 0, 0, 0.1);
            border-radius: 50%;
            border-top: 4px solid #00adb5;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 10px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .switch {
            position: relative;
            display: inline-block;
            width: 60px;
            height: 34px;
        }
        
        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #393e46;
            transition: .4s;
            border-radius: 34px;
        }
        
        .slider:before {
            position: absolute;
            content: "";
            height: 26px;
            width: 26px;
            left: 4px;
            bottom: 4px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        
        input:checked + .slider {
            background-color: #00adb5;
        }
        
        input:checked + .slider:before {
            transform: translateX(26px);
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1><i class="fas fa-fire"></i> Telegram Multi-Token Spammer</h1>
            <p>Gửi tin nhắn tự động với nhiều token cùng lúc</p>
            <div id="alert" class="alert"></div>
        </div>

        <!-- Statistics -->
        <div class="stats" id="stats">
            <div class="stat-card">
                <div class="stat-number" id="total-tasks">0</div>
                <div>Tổng Task</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="running-tasks">0</div>
                <div>Đang chạy</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="total-tokens">0</div>
                <div>Tổng Token</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="total-sent">0</div>
                <div>Tin đã gửi</div>
            </div>
        </div>

        <!-- Create Task Form -->
        <div class="card">
            <h2 style="color: #00adb5; margin-bottom: 20px;"><i class="fas fa-plus"></i> Tạo Task Mới</h2>
            <form id="create-task-form">
                <div class="form-group">
                    <label><i class="fas fa-tag"></i> Tên Task</label>
                    <input type="text" id="task-name" class="form-control" placeholder="Nhập tên task..." value="Task 1">
                </div>
                
                <div class="form-group">
                    <label><i class="fas fa-key"></i> Bot Tokens (phân cách bằng dấu ,)</label>
                    <textarea id="tokens" class="form-control" placeholder="Nhập các bot token, mỗi token một dòng hoặc phân cách bằng dấu phẩy..." rows="3" required></textarea>
                    <small style="color: #aaa;">Có thể nhập nhiều token, mỗi token một dòng hoặc phân cách bằng dấu phẩy</small>
                </div>
                
                <div class="form-group">
                    <label><i class="fas fa-users"></i> Chat IDs (phân cách bằng dấu ,)</label>
                    <input type="text" id="chat-ids" class="form-control" placeholder="Nhập các Chat ID, phân cách bằng dấu phẩy..." required>
                </div>
                
                <div class="form-group">
                    <label><i class="fas fa-comment-alt"></i> Nội dung tin nhắn</label>
                    <textarea id="message" class="form-control" placeholder="Nhập nội dung tin nhắn hoặc upload file .txt..." rows="4" required></textarea>
                </div>
                
                <div class="form-group">
                    <div class="file-upload" onclick="document.getElementById('file-input').click()">
                        <div class="file-icon"><i class="fas fa-file-upload"></i></div>
                        <div>Click để upload file .txt hoặc kéo thả file vào đây</div>
                        <div id="file-info" style="color: #2ed573; margin-top: 10px; font-weight: 600;">Chưa có file nào được chọn</div>
                        <input type="file" id="file-input" style="display: none;" accept=".txt">
                    </div>
                </div>
                
                <div class="form-group">
                    <label><i class="fas fa-image"></i> Ảnh (Link URL hoặc để trống)</label>
                    <input type="text" id="photo" class="form-control" placeholder="Nhập link ảnh hoặc để trống...">
                </div>
                
                <div class="form-group">
                    <label><i class="fas fa-clock"></i> Delay (giây)</label>
                    <input type="number" id="delay" class="form-control" value="5" min="1" step="0.1" required>
                </div>
                
                <div class="form-group">
                    <label style="display: flex; align-items: center; gap: 10px;">
                        <i class="fas fa-keyboard"></i> Fake Typing
                        <label class="switch">
                            <input type="checkbox" id="use-typing">
                            <span class="slider"></span>
                        </label>
                    </label>
                </div>
                
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-rocket"></i> Bắt đầu Spam
                </button>
            </form>
        </div>

        <!-- Tasks List -->
        <div class="card">
            <h2 style="color: #00adb5; margin-bottom: 20px;"><i class="fas fa-tasks"></i> Danh sách Task</h2>
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p>Đang tải...</p>
            </div>
            <div id="tasks-container">
                <div style="text-align: center; padding: 40px; color: #aaa;">
                    <i class="fas fa-inbox" style="font-size: 3em; margin-bottom: 10px;"></i>
                    <p>Chưa có task nào được tạo</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        let refreshInterval;
        
        // Hiển thị thông báo
        function showAlert(message, type = 'success') {
            const alert = document.getElementById('alert');
            alert.textContent = message;
            alert.className = `alert alert-${type}`;
            alert.style.display = 'block';
            
            setTimeout(() => {
                alert.style.display = 'none';
            }, 5000);
        }
        
        // Cập nhật thống kê
        function updateStats(stats) {
            document.getElementById('total-tasks').textContent = stats.total_tasks;
            document.getElementById('running-tasks').textContent = stats.running_tasks;
            document.getElementById('total-tokens').textContent = stats.total_tokens;
            document.getElementById('total-sent').textContent = stats.total_sent;
        }
        
        // Tải danh sách tasks
        async function loadTasks() {
            try {
                const response = await fetch('/api/tasks');
                const data = await response.json();
                
                updateStats(data.stats);
                
                const container = document.getElementById('tasks-container');
                if (Object.keys(data.tasks).length === 0) {
                    container.innerHTML = `
                        <div style="text-align: center; padding: 40px; color: #aaa;">
                            <i class="fas fa-inbox" style="font-size: 3em; margin-bottom: 10px;"></i>
                            <p>Chưa có task nào được tạo</p>
                        </div>
                    `;
                    return;
                }
                
                let html = '<div class="task-grid">';
                for (const [taskId, task] of Object.entries(data.tasks)) {
                    const statusClass = task.running ? 'running' : 'stopped';
                    const statusText = task.running ? '🟢 ĐANG CHẠY' : '🔴 ĐÃ DỪNG';
                    const statusBadgeClass = task.running ? 'status-running' : 'status-stopped';
                    
                    // Hiển thị tokens
                    let tokensHtml = '';
                    if (task.tokens_info) {
                        task.tokens_info.forEach(tokenInfo => {
                            tokensHtml += `<span class="token-badge token-valid">${tokenInfo.username}</span> `;
                        });
                    }
                    
                    if (task.invalid_tokens && task.invalid_tokens.length > 0) {
                        task.invalid_tokens.forEach(token => {
                            tokensHtml += `<span class="token-badge token-invalid">${token.substring(0, 10)}...</span> `;
                        });
                    }
                    
                    html += `
                        <div class="task-card ${statusClass}">
                            <div class="task-header">
                                <span class="task-title">${task.name}</span>
                                <span class="task-status ${statusBadgeClass}">${statusText}</span>
                            </div>
                            
                            <div class="task-info">
                                <p><strong>📊 Đã gửi:</strong> <span style="color: #00adb5; font-weight: bold;">${task.sent_count}</span> tin</p>
                                <p><strong>⏱ Delay:</strong> ${task.delay}s</p>
                                <p><strong>⌨️ Typing:</strong> ${task.use_typing ? 'CÓ' : 'KHÔNG'}</p>
                                <p><strong>📝 Lần cuối:</strong> ${task.last_sent || 'Chưa gửi'}</p>
                                <p><strong>🕐 Tạo lúc:</strong> ${task.created_at}</p>
                                <p><strong>🤖 Tokens:</strong><br>${tokensHtml}</p>
                            </div>
                            
                            <div class="task-actions">
                                ${task.running ? 
                                    `<button onclick="stopTask('${taskId}')" class="btn btn-danger"><i class="fas fa-stop"></i> Dừng</button>` : 
                                    `<button onclick="startTask('${taskId}')" class="btn btn-success"><i class="fas fa-play"></i> Chạy</button>`
                                }
                                <button onclick="deleteTask('${taskId}')" class="btn btn-danger"><i class="fas fa-trash"></i> Xóa</button>
                            </div>
                        </div>
                    `;
                }
                html += '</div>';
                container.innerHTML = html;
                
            } catch (error) {
                console.error('Lỗi tải tasks:', error);
            }
        }
        
        // Tạo task mới
        document.getElementById('create-task-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const taskData = {
                name: document.getElementById('task-name').value,
                tokens: document.getElementById('tokens').value,
                chat_ids: document.getElementById('chat-ids').value,
                message: document.getElementById('message').value,
                photo: document.getElementById('photo').value,
                delay: document.getElementById('delay').value,
                use_typing: document.getElementById('use-typing').checked
            };
            
            try {
                const response = await fetch('/api/tasks', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(taskData)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showAlert(result.message, 'success');
                    // Reset form
                    document.getElementById('task-name').value = `Task ${Object.keys(await (await fetch('/api/tasks')).json()).length + 1}`;
                    document.getElementById('tokens').value = '';
                    loadTasks();
                } else {
                    showAlert(result.message, 'error');
                }
            } catch (error) {
                showAlert('Lỗi kết nối đến server', 'error');
            }
        });
        
        // Upload file
        document.getElementById('file-input').addEventListener('change', async function(e) {
            if (!e.target.files.length) return;
            
            const file = e.target.files[0];
            if (!file.name.endsWith('.txt')) {
                showAlert('Chỉ hỗ trợ file .txt', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    document.getElementById('message').value = result.content;
                    document.getElementById('file-info').textContent = `📄 ${result.filename}`;
                    showAlert('Đã tải file thành công', 'success');
                } else {
                    showAlert(result.message, 'error');
                }
            } catch (error) {
                showAlert('Lỗi upload file', 'error');
            }
        });
        
        // Dừng task
        async function stopTask(taskId) {
            if (!confirm('Bạn có chắc muốn dừng task này?')) return;
            
            try {
                const response = await fetch(`/api/tasks/${taskId}/stop`, {
                    method: 'POST'
                });
                
                const result = await response.json();
                showAlert(result.message, result.success ? 'success' : 'error');
                loadTasks();
            } catch (error) {
                showAlert('Lỗi kết nối', 'error');
            }
        }
        
        // Chạy task
        async function startTask(taskId) {
            try {
                const response = await fetch(`/api/tasks/${taskId}/start`, {
                    method: 'POST'
                });
                
                const result = await response.json();
                showAlert(result.message, result.success ? 'success' : 'error');
                loadTasks();
            } catch (error) {
                showAlert('Lỗi kết nối', 'error');
            }
        }
        
        // Xóa task
        async function deleteTask(taskId) {
            if (!confirm('Bạn có chắc muốn xóa task này?')) return;
            
            try {
                const response = await fetch(`/api/tasks/${taskId}`, {
                    method: 'DELETE'
                });
                
                const result = await response.json();
                showAlert(result.message, result.success ? 'success' : 'error');
                loadTasks();
            } catch (error) {
                showAlert('Lỗi kết nối', 'error');
            }
        }
        
        // Kéo thả file
        const fileUpload = document.querySelector('.file-upload');
        fileUpload.addEventListener('dragover', (e) => {
            e.preventDefault();
            fileUpload.style.background = 'rgba(0, 173, 181, 0.2)';
        });
        
        fileUpload.addEventListener('dragleave', () => {
            fileUpload.style.background = 'rgba(0, 173, 181, 0.05)';
        });
        
        fileUpload.addEventListener('drop', async (e) => {
            e.preventDefault();
            fileUpload.style.background = 'rgba(0, 173, 181, 0.05)';
            
            const file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.txt')) {
                document.getElementById('file-input').files = e.dataTransfer.files;
                
                const formData = new FormData();
                formData.append('file', file);
                
                try {
                    const response = await fetch('/api/upload', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        document.getElementById('message').value = result.content;
                        document.getElementById('file-info').textContent = `📄 ${result.filename}`;
                        showAlert('Đã tải file thành công', 'success');
                    } else {
                        showAlert(result.message, 'error');
                    }
                } catch (error) {
                    showAlert('Lỗi upload file', 'error');
                }
            } else {
                showAlert('Chỉ hỗ trợ file .txt', 'error');
            }
        });
        
        // Auto refresh
        function startAutoRefresh() {
            loadTasks();
            refreshInterval = setInterval(loadTasks, 3000); // Refresh mỗi 3 giây
        }
        
        // Khởi động
        document.addEventListener('DOMContentLoaded', function() {
            loadTasks();
            startAutoRefresh();
        });
    </script>
</body>
</html>
'''

# Lưu template
with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(index_html)

# Hàm chạy tool từ terminal (giữ nguyên tính năng cũ)
def terminal_main():
    print("""
    ╔══════════════════════════════╗
    ║      TOOL SPAM TELEGRAM      ║
    ║     (FAST MODE - TURBO)      ║
    ╚══════════════════════════════╝
    """)

    # Nhập thông tin cơ bản
    chat_ids = input("Nhập ID group (phân tách bởi dấu ,): ").strip().split(",")
    chat_ids = [cid.strip() for cid in chat_ids if cid.strip()]

    file_path = input("Nhập đường dẫn file nội dung .txt: ").strip()
    if not os.path.isfile(file_path):
        print(f"[!] File không tồn tại: {file_path}")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"[!] Lỗi đọc file: {e}")
        return

    choice = input("Bạn có muốn gửi kèm ảnh? (1 = Có, 2 = Không): ").strip()
    if choice == "1":
        img = input("Nhập link ảnh hoặc đường dẫn ảnh local: ").strip()
    else:
        img = None

    # Delay nhanh hơn với giá trị mặc định nhỏ
    delay_input = input("Nhập delay giữa mỗi vòng lặp (giây) [mặc định: 1]: ").strip()
    if delay_input:
        try:
            delay = float(delay_input)
            if delay < 0.1:
                delay = 0.1
        except:
            delay = 1.0
    else:
        delay = 1.0

    typing_choice = input("Bật fake typing? (1 = Có, 2 = Không): ").strip()
    use_typing = (typing_choice == "1")

    # Nhập token ban đầu
    print("\n=== NHẬP TOKEN BAN ĐẦU ===")
    raw_tokens = input("Nhập token bot (phân tách bởi dấu ,): ").strip().split(",")
    initial_tokens = []
    for token in raw_tokens:
        token = token.strip()
        if token:
            result = check_token(token)
            if result['valid']:
                initial_tokens.append(token)
                print(f"[✓] Token {token[:10]}... hợp lệ")
            else:
                print(f"[✗] Token {token[:10]}... không hợp lệ")
    
    if not initial_tokens:
        print("Không có token hợp lệ.")
        return

    # Tạo task ID
    task_id = f"term_{int(time.time())}"
    
    # Bắt đầu task từ terminal
    task_data = {
        'id': task_id,
        'name': 'Terminal Task',
        'tokens': ','.join(initial_tokens),
        'chat_ids': ','.join(chat_ids),
        'message': text,
        'photo': img if img else '',
        'delay': delay,
        'use_typing': use_typing
    }
    
    result = start_task(task_data)
    
    if result['success']:
        print(f"\n✅ {result['message']}")
        print(f"📊 Token hợp lệ: {result['valid_tokens']}")
        print(f"📊 Token không hợp lệ: {result['invalid_tokens']}")
        print(f"\n🌐 Web Interface đang chạy tại: http://localhost:5000")
        print("📋 Gõ 'web' để mở giao diện web")
        print("📋 Gõ 'stop' để dừng task")
        print("📋 Gõ 'exit' để thoát\n")
        
        # Menu terminal
        while True:
            cmd = input("Nhập lệnh: ").strip().lower()
            
            if cmd == 'web':
                print("Mở trình duyệt và truy cập: http://localhost:5000")
            elif cmd == 'stop':
                stop_task(task_id)
                print("Đã dừng task")
                break
            elif cmd == 'exit':
                stop_task(task_id)
                break
            elif cmd == 'status':
                if task_id in tasks:
                    task = tasks[task_id]
                    print(f"\n=== TRẠNG THÁI TASK ===")
                    print(f"Tên: {task['name']}")
                    print(f"Trạng thái: {'Đang chạy' if task['running'] else 'Đã dừng'}")
                    print(f"Đã gửi: {task['sent_count']} tin")
                    print(f"Lần gửi cuối: {task['last_sent']}")
                    print(f"Tokens: {len(task['tokens'])} token")
                else:
                    print("Task không tồn tại")
            else:
                print("Lệnh không hợp lệ. Các lệnh: web, stop, status, exit")
    else:
        print(f"❌ {result['message']}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'web':
        print("🚀 Khởi động Telegram Multi-Token Spammer Web Interface...")
        print("🌐 Truy cập: http://localhost:5000")
        app.run(host='0.0.0.0', port=5000, debug=True)
    elif len(sys.argv) > 1 and sys.argv[1] == 'term':
        terminal_main()
    else:
        print("""
        🔧 Telegram Multi-Token Spammer
        
        Cách sử dụng:
        python treotle.py web    - Chạy giao diện web
        python treotle.py term   - Chạy terminal mode
        
        Web Interface:
        - Quản lý nhiều task cùng lúc
        - Thêm/xóa/sửa task
        - Upload file .txt
        - Xem thống kê chi tiết
        
        Terminal Mode:
        - Chạy nhanh từ terminal
        - Kiểm tra token
        - Fake typing effect
        """)
        
        choice = input("Chọn mode (1 = Web, 2 = Terminal): ").strip()
        if choice == '1':
            print("\n🚀 Khởi động Web Interface...")
            print("🌐 Truy cập: http://localhost:5000")
            app.run(host='0.0.0.0', port=5000, debug=True)
        else:
            terminal_main()
