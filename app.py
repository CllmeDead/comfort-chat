from flask import Flask, render_template, request, jsonify, session
import sqlite3
import uuid
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

DATABASE = 'comfort_chat.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            author_token TEXT NOT NULL,
            replier_token TEXT,
            reply_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            replied_at TIMESTAMP,
            is_read INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# Initialize database when app starts
with app.app_context():
    init_db()

@app.before_request
def ensure_token():
    if 'user_token' not in session:
        session['user_token'] = str(uuid.uuid4())

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    content = data.get('content', '').strip()

    if not content or len(content) < 10:
        return jsonify({'error': 'Message too short. Share a little more.'}), 400

    if len(content) > 2000:
        return jsonify({'error': 'Message too long. Keep it under 2000 characters.'}), 400

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    message_id = str(uuid.uuid4())[:8]
    c.execute(
        'INSERT INTO messages (id, content, author_token) VALUES (?, ?, ?)',
        (message_id, content, session['user_token'])
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message_id': message_id})

@app.route('/api/receive')
def receive_message():
    # Get a message that:
    # 1. Hasn't been replied to yet
    # 2. Isn't from the current user
    # 3. Oldest first (waiting longest)
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        SELECT id, content, created_at FROM messages
        WHERE replier_token IS NULL
        AND author_token != ?
        ORDER BY created_at ASC
        LIMIT 1
    ''', (session['user_token'],))

    row = c.fetchone()
    conn.close()

    if row:
        return jsonify({
            'found': True,
            'message': {
                'id': row[0],
                'content': row[1],
                'sent_at': row[2]
            }
        })
    return jsonify({'found': False})

@app.route('/api/reply', methods=['POST'])
def reply_message():
    data = request.json
    message_id = data.get('message_id')
    reply = data.get('reply', '').strip()

    if not reply or len(reply) < 10:
        return jsonify({'error': 'Reply too short. Be a bit more thoughtful.'}), 400

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Check message exists and isn't already replied
    c.execute('SELECT replier_token FROM messages WHERE id = ?', (message_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Message not found'}), 404

    if row[0] is not None:
        conn.close()
        return jsonify({'error': 'Already replied to'}), 409

    c.execute('''
        UPDATE messages
        SET replier_token = ?, reply_content = ?, replied_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (session['user_token'], reply, message_id))

    conn.commit()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/my-messages')
def my_messages():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Messages I sent that got replies
    c.execute('''
        SELECT id, content, reply_content, replied_at, is_read
        FROM messages
        WHERE author_token = ? AND reply_content IS NOT NULL
        ORDER BY replied_at DESC
    ''', (session['user_token'],))

    my_sent = [{
        'id': r[0],
        'my_message': r[1],
        'their_reply': r[2],
        'replied_at': r[3],
        'is_read': r[4]
    } for r in c.fetchall()]

    # Messages I replied to
    c.execute('''
        SELECT id, content, reply_content
        FROM messages
        WHERE replier_token = ?
        ORDER BY replied_at DESC
    ''', (session['user_token'],))

    my_replies = [{
        'id': r[0],
        'their_message': r[1],
        'my_reply': r[2]
    } for r in c.fetchall()]

    conn.close()

    return jsonify({
        'received_replies': my_sent,
        'sent_replies': my_replies
    })

@app.route('/api/mark-read', methods=['POST'])
def mark_read():
    data = request.json
    message_id = data.get('message_id')

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        'UPDATE messages SET is_read = 1 WHERE id = ? AND author_token = ?',
        (message_id, session['user_token'])
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/stats')
def stats():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM messages')
    total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM messages WHERE reply_content IS NOT NULL')
    replied = c.fetchone()[0]
    conn.close()

    return jsonify({
        'total_messages': total,
        'replied_messages': replied,
        'waiting_messages': total - replied
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
