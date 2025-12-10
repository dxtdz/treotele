import requests
import threading
import time
import os
import json
import random
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
import logging

# Flask app
app = Flask(__name__)

# Cấu hình logging
logging.basicConfig(level=logging.INFO)

# Biến toàn cục
tasks = {}
stop_events = {}
tasks_file = 'telegram_tasks.json'

# Tải tasks từ file
if os.path.exists(tasks_file):
    try:
        with open(tasks_file, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except:
        pass

def save_tasks():
    """Lưu tasks vào file"""
    try:
        with open(tasks_file, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except:
        pass

def send_message(token, chat_id, text):
    """Gửi tin nhắn Telegram"""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": text}
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except:
        return False

def send_loop(task_id):
    """Vòng lặp gửi tin nhắn"""
    task = tasks.get(task_id)
    if not task or not task.get('running'):
        return
    
    stop_event = stop_events.get(task_id)
    if not stop_event:
        return
    
    tokens = task.get('tokens', [])
    chat_ids = task.get('chat_ids', [])
    message = task.get('message', '')
    delay = task.get('delay', 5)
    
    while not stop_event.is_set() and task.get('running'):
        for chat_id in chat_ids:
            if stop_event.is_set():
                break
            
            for token in tokens:
                if stop_event.is_set():
                    break
                
                if send_message(token, chat_id, message):
                    tasks[task_id]['sent_count'] = tasks[task_id].get('sent_count', 0) + 1
                    tasks[task_id]['last_sent'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_tasks()
                
                time.sleep(0.1)
        
        time.sleep(delay)

def start_task(task_data):
    """Bắt đầu task mới"""
    task_id = task_data['id']
    
    # Tạo stop event
    stop_event = threading.Event()
    stop_events[task_id] = stop_event
    
    # Lưu task
    tokens = [t.strip() for t in task_data['tokens'].split(',') if t.strip()]
    chat_ids = [c.strip() for c in task_data['chat_ids'].split(',') if c.strip()]
    
    tasks[task_id] = {
        'id': task_id,
        'name': task_data.get('name', 'Task'),
        'tokens': tokens,
        'chat_ids': chat_ids,
        'message': task_data['message'],
        'delay': float(task_data.get('delay', 5)),
        'running': True,
        'sent_count': 0,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'last_sent': ''
    }
    
    # Bắt đầu thread
    t = threading.Thread(target=send_loop, args=(task_id,), daemon=True)
    t.start()
    
    save_tasks()
    return {'success': True, 'message': 'Task started'}

def stop_task(task_id):
    """Dừng task"""
    if task_id in stop_events:
        stop_events[task_id].set()
    
    if task_id in tasks:
        tasks[task_id]['running'] = False
    
    save_tasks()
    return True

# ====================== ROUTES ======================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Telegram Spammer</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial; background: #f0f0f0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: white; padding: 20px; margin: 20px 0; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        input, textarea { width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }
        button { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .task { border-left: 5px solid #28a745; padding: 10px; margin: 10px 0; background: #f8f9fa; }
        .task-stopped { border-left-color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Telegram Spammer</h1>
        
        <div class="card">
            <h2>➕ Tạo Task Mới</h2>
            <form id="taskForm">
                <input type="text" name="name" placeholder="Tên task" required>
                <textarea name="tokens" placeholder="Bot tokens (phân cách bằng dấu ,)" rows="2" required></textarea>
                <input type="text" name="chat_ids" placeholder="Chat IDs (phân cách bằng dấu ,)" required>
                <textarea name="message" placeholder="Nội dung tin nhắn" rows="3" required></textarea>
                <input type="number" name="delay" placeholder="Delay (giây)" value="5" min="1" step="0.1" required>
                <button type="submit">🚀 Bắt đầu</button>
            </form>
        </div>
        
        <div class="card">
            <h2>📋 Tasks Đang Chạy</h2>
            <div id="tasks"></div>
        </div>
    </div>
    
    <script>
        // Tải tasks
        async function loadTasks() {
            const res = await fetch('/api/tasks');
            const data = await res.json();
            
            let html = '';
            for (const task of data.tasks) {
                html += `
                    <div class="task ${task.running ? '' : 'task-stopped'}">
                        <h3>${task.name}</h3>
                        <p>Tokens: ${task.tokens.length}</p>
                        <p>Đã gửi: ${task.sent_count}</p>
                        <p>Delay: ${task.delay}s</p>
                        <p>Lần cuối: ${task.last_sent || 'Chưa gửi'}</p>
                        ${task.running ? 
                            `<button onclick="stopTask('${task.id}')">⏸ Dừng</button>` : 
                            `<button onclick="startTask('${task.id}')">▶️ Chạy</button>`
                        }
                        <button onclick="deleteTask('${task.id}')">🗑 Xóa</button>
                    </div>
                `;
            }
            
            document.getElementById('tasks').innerHTML = html || '<p>Chưa có task nào</p>';
        }
        
        // Tạo task
        document.getElementById('taskForm').onsubmit = async (e) => {
            e.preventDefault();
            
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            const res = await fetch('/api/tasks', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            
            if (res.ok) {
                alert('Task đã được tạo!');
                e.target.reset();
                loadTasks();
            }
        };
        
        // Dừng task
        async function stopTask(id) {
            await fetch(`/api/tasks/${id}/stop`, {method: 'POST'});
            loadTasks();
        }
        
        // Chạy task
        async function startTask(id) {
            await fetch(`/api/tasks/${id}/start`, {method: 'POST'});
            loadTasks();
        }
        
        // Xóa task
        async function deleteTask(id) {
            if (confirm('Xóa task?')) {
                await fetch(`/api/tasks/${id}`, {method: 'DELETE'});
                loadTasks();
            }
        }
        
        // Auto refresh
        loadTasks();
        setInterval(loadTasks, 3000);
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify({'tasks': list(tasks.values())})

@app.route('/api/tasks', methods=['POST'])
def create_task():
    try:
        data = request.json
        task_id = f"task_{int(time.time())}"
        data['id'] = task_id
        result = start_task(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def api_stop_task(task_id):
    stop_task(task_id)
    return jsonify({'success': True})

@app.route('/api/tasks/<task_id>/start', methods=['POST'])
def api_start_task(task_id):
    if task_id in tasks:
        tasks[task_id]['running'] = True
        stop_events[task_id] = threading.Event()
        threading.Thread(target=send_loop, args=(task_id,), daemon=True).start()
        save_tasks()
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    if task_id in stop_events:
        stop_events[task_id].set()
    if task_id in tasks:
        del tasks[task_id]
    if task_id in stop_events:
        del stop_events[task_id]
    save_tasks()
    return jsonify({'success': True})

# ====================== CHẠY APP ======================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
